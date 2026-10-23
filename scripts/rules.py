#!/usr/bin/env python3
"""Reproducible Aethersailor templates with separately maintained personal rules."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'Aethersailor/Custom_OpenClash_Rules'
VARIANTS = {
    'standard': 'Custom_Clash',
    'standard-fallback': 'Custom_Clash_Fallback',
    'lite': 'Custom_Clash_Lite',
    'lite-fallback': 'Custom_Clash_Lite_Fallback',
    'gfw': 'Custom_Clash_GFW',
    'gfw-fallback': 'Custom_Clash_GFW_Fallback',
    'full': 'Custom_Clash_Full',
    'full-fallback': 'Custom_Clash_Full_Fallback',
    'selfhosted-provider-fallback': 'Custom_Clash_Selfhosted_Provider_Fallback',
    'selfhosted-manual-fallback': 'Custom_Clash_Selfhosted_Manual_Fallback',
}
INI_VARIANTS = {k: v for k, v in VARIANTS.items() if not k.startswith('selfhosted-')}
INI_VARIANTS['mainland'] = 'Custom_Clash_Mainland'
STASH_INI_VARIANTS = dict(INI_VARIANTS)
BUILTINS = {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'PASS-RULE', 'COMPATIBLE'}
PLACEHOLDER = 'https://example.com/REPLACE_WITH_YOUR_SUBSCRIPTION_URL'
SELFHOST_PLACEHOLDER = 'https://example.com/REPLACE_WITH_YOUR_SELFHOST_SUBSCRIPTION_URL'
UPSTREAM_FILES = {v + '.yaml': 'cfg/yaml/' + v + '.yaml' for v in VARIANTS.values()}
UPSTREAM_FILES.update({v + '.ini': 'cfg/' + v + '.ini' for v in INI_VARIANTS.values()})
UPSTREAM_FILES['LICENSE'] = 'LICENCE'
UPSTREAM_FILES['Custom_Direct.list'] = 'rule/Custom_Direct.list'


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError('YAML contains a duplicate key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_yaml(path: Path) -> dict:
    try:
        value = yaml.load(Path(path).read_text(encoding='utf-8'), Loader=UniqueLoader)
    except yaml.YAMLError:
        raise ValueError('Invalid YAML; check indentation and value types') from None
    if not isinstance(value, dict):
        raise ValueError('Expected a YAML mapping')
    return value


def validate_public_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        valid = (parts.scheme in {'https', 'http'} and parts.hostname and not parts.username
                 and not parts.password and not parts.query and not parts.fragment)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Public resource URL must be HTTP(S) without credentials, query, or fragment')


def _private_url(url) -> str:
    try:
        parts = urlsplit(url)
        valid = parts.scheme in {'https', 'http'} and parts.hostname and 'REPLACE_WITH_' not in url
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Fill in a valid private HTTP(S) subscription URL in .local/secrets.yaml')
    return url


def _primary(upstream: dict) -> str:
    names = {g['name'] for g in upstream.get('proxy-groups', [])}
    for name in ['🚀 手动选择', '🚀 故障转移']:
        if name in names:
            return name
    raise ValueError('Upstream primary proxy group changed; review the new template')


def _replace_aliases(value, primary):
    if isinstance(value, str):
        return value.replace('@proxy', primary).replace('@direct', 'DIRECT').replace('@reject', 'REJECT')
    if isinstance(value, list):
        return [_replace_aliases(v, primary) for v in value]
    if isinstance(value, dict):
        return {k: _replace_aliases(v, primary) for k, v in value.items()}
    return value


def _personal_rules(personal: dict, key: str, primary: str) -> list[str]:
    values = personal.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f'{key} must be a list')
    result = []
    for rule in values:
        if (not isinstance(rule, str) or '\n' in rule or len(rule.split(',')) < 3
                or rule.split(',')[0].upper() in {'MATCH', 'FINAL'}):
            raise ValueError('Personal rules must be individual rules, without MATCH/FINAL catch-all')
        fields = rule.split(',')
        index = -2 if fields[-1] in {'no-resolve', 'src'} else -1
        aliases = {'@proxy': primary, '@direct': 'DIRECT', '@reject': 'REJECT'}
        fields[index] = aliases.get(fields[index], fields[index])
        result.append(','.join(fields))
    return result


def _ads(settings: dict) -> dict:
    ads = settings.get('ads', {})
    if not isinstance(ads, dict) or not isinstance(ads.get('enabled'), bool):
        raise ValueError('settings.ads.enabled must be true or false')
    if set(ads) - {'enabled', 'name', 'group', 'url', 'interval'}:
        raise ValueError('Unknown advertising setting; use the documented ads fields')
    if not ads['enabled']:
        return ads
    validate_public_url(ads.get('url'))
    if not isinstance(ads.get('interval'), int) or ads['interval'] <= 0:
        raise ValueError('settings.ads.interval must be a positive integer')
    for key in ['name', 'group']:
        value = ads.get(key)
        if not isinstance(value, str) or not value or any(c in value for c in ',\n`@'):
            raise ValueError('Invalid advertising provider/group name')
    return ads


def build_config(upstream: dict, personal: dict, settings: dict, runtime: dict | None = None) -> dict:
    base = copy.deepcopy(upstream)
    primary = _primary(base)
    ads = _ads(settings)
    if runtime:
        if set(runtime) & {'proxy-providers', 'proxy-groups', 'rule-providers', 'rules', 'proxies'}:
            raise ValueError('Runtime template may not replace routing or node sections')
        base = {**_replace_aliases(copy.deepcopy(runtime), primary), **base}
    for name, provider in base.get('proxy-providers', {}).items():
        if provider.get('type') == 'http':
            provider['url'] = SELFHOST_PLACEHOLDER if name == 'selfhost' else PLACEHOLDER
        if provider.get('header') is None:
            provider.pop('header', None)
    before = _personal_rules(personal, 'before_ads', primary)
    after = _personal_rules(personal, 'after_ads', primary)
    added = []
    if ads['enabled']:
        if ads['group'] in {g['name'] for g in base['proxy-groups']} or ads['group'] in BUILTINS:
            raise ValueError('Advertising group collides with an upstream/built-in group')
        if ads['name'] in base.get('rule-providers', {}):
            raise ValueError('Advertising provider collides with an upstream provider')
        # Stash has no PASS built-in. Use the existing primary policy as the
        # explicit non-blocking choice and keep the utility group last in the UI.
        base['proxy-groups'].append({'name': ads['group'], 'type': 'select', 'proxies': ['REJECT', primary]})
        base.setdefault('rule-providers', {})[ads['name']] = {
            'type': 'http', 'behavior': 'classical', 'format': 'yaml', 'url': ads['url'],
            'path': './rule_provider/' + ads['name'] + '.yaml', 'interval': ads['interval'],
        }
        added = [f"RULE-SET,{ads['name']},{ads['group']}"]
    base['rules'] = before + added + after + base['rules']
    validate_config(base)
    return base


def validate_config(config: dict) -> None:
    groups = config.get('proxy-groups', [])
    names = [g['name'] for g in groups]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate proxy group name')
    static = [p['name'] for p in config.get('proxies', [])]
    if len(static) != len(set(static)) or set(static) & (set(names) | BUILTINS):
        raise ValueError('Duplicate/conflicting static node name')
    targets = set(names) | set(static) | BUILTINS
    providers = config.get('proxy-providers', {})
    rule_providers = config.get('rule-providers', {})
    for group in groups:
        if not set(group.get('proxies', [])) <= targets:
            raise ValueError('Proxy group references an unknown target')
        if not set(group.get('use', [])) <= set(providers):
            raise ValueError('Proxy group references an unknown node provider')
    rules = config.get('rules', [])
    if not rules or not rules[-1].startswith('MATCH,'):
        raise ValueError('Missing final upstream MATCH rule')
    for rule in rules:
        fields = rule.split(',')
        index = -2 if fields[-1] in {'no-resolve', 'src'} else -1
        if fields[index] not in targets:
            raise ValueError('Rule references an unknown policy/group')
        if fields[0] == 'RULE-SET' and fields[1] not in rule_providers:
            raise ValueError('Rule references an unknown rule provider')
    paths = [p['path'] for family in [providers, rule_providers] for p in family.values() if 'path' in p]
    if len(paths) != len(set(paths)):
        raise ValueError('Provider cache paths must be distinct')


def _personal_for(personal: dict, slug: str, format_name: str = 'yaml') -> dict:
    unknown = set(personal) - {'before_ads', 'after_ads', 'variants', 'formats'}
    variants = personal.get('variants', {})
    if unknown or not isinstance(variants, dict) or set(variants) - set(VARIANTS):
        raise ValueError('Unknown personal rule section or template variant')
    extra = variants.get(slug, {})
    if not isinstance(extra, dict) or set(extra) - {'before_ads', 'after_ads', 'formats'}:
        raise ValueError('Invalid variant-specific personal rule section')
    def format_layer(block):
        formats = block.get('formats', {})
        if not isinstance(formats, dict) or set(formats) - {'yaml', 'ini', 'stash'}:
            raise ValueError('Personal formats must contain only yaml, ini and stash sections')
        selected = formats.get(format_name, {})
        if not isinstance(selected, dict) or set(selected) - {'before_ads', 'after_ads'}:
            raise ValueError('Invalid format-specific personal rule section')
        return selected
    layers = [personal, format_layer(personal), extra, format_layer(extra)]
    merged = {}
    for key in ['before_ads', 'after_ads']:
        merged[key] = []
        for layer in layers:
            rules = layer.get(key, [])
            if not isinstance(rules, list):
                raise ValueError('Personal rule sections must be lists')
            merged[key].extend(rules)
    return merged


def _header(commit: str, private=False) -> str:
    return (f'# Generated by personal-clash-rules; upstream {REPOSITORY}@{commit}\n'
            '# Aethersailor derivatives: CC BY-SA 4.0. See LICENSE and NOTICE.md.\n'
            '# Edit rules/custom.yaml and rebuild; do not edit generated routing.\n'
            + ('# PRIVATE: contains your subscription/node credentials. Do not publish.\n' if private
               else '# PUBLIC TEMPLATE: fill provider URLs locally, or use the render command.\n'))


def _selection(formats='all', platform='all', variants=None):
    if formats not in {'all', 'yaml', 'ini'} or platform not in {'all', 'openclash', 'mihomo', 'stash'}:
        raise ValueError('Unknown output format or platform')
    if platform == 'stash' and formats != 'ini':
        raise ValueError('Stash conversion templates require --format ini --platform stash')
    if platform not in {'all', 'stash'} and formats != 'yaml':
        raise ValueError('--platform requires --format yaml')
    selected = set(variants) if variants is not None else set(VARIANTS) | {'mainland'}
    if not selected or selected - (set(VARIANTS) | {'mainland'}):
        raise ValueError('Unknown or empty variant selection')
    if variants is not None and formats == 'yaml' and 'mainland' in selected:
        raise ValueError('Mainland is an INI alias; select standard for YAML')
    if variants is not None and formats == 'ini' and selected - set(INI_VARIANTS):
        raise ValueError('Selected selfhosted variants do not have upstream INI templates')
    yaml_variants = {k: v for k, v in VARIANTS.items() if k in selected and formats != 'ini'}
    ini_variants = {k: v for k, v in INI_VARIANTS.items() if k in selected and formats != 'yaml' and platform != 'stash'}
    stash_variants = {k: v for k, v in STASH_INI_VARIANTS.items() if k in selected and formats != 'yaml' and platform in {'all', 'stash'}}
    platforms = ['openclash', 'mihomo'] if platform == 'all' else [platform]
    return yaml_variants, ini_variants, stash_variants, platforms


def prepare_outputs(root: Path, vendor_dir: Path | None = None, subscription_url=None,
                    *, formats='all', platform='all', variants=None) -> dict[str, str]:
    if subscription_url is not None:
        raise ValueError('Use render_private for credentials; public builds only contain placeholders')
    vendor = vendor_dir or root / 'vendor/aethersailor'
    meta = json.loads((vendor / 'upstream.json').read_text())
    settings = load_yaml(root / 'config/settings.yaml')
    _ads(settings)
    personal = load_yaml(root / 'rules/custom.yaml')
    yaml_variants, ini_variants, stash_variants, platforms = _selection(formats, platform, variants)
    runtime = load_yaml(root / 'templates/mihomo-runtime.yaml') if yaml_variants and 'mihomo' in platforms else None
    outputs = {}
    for slug, stem in yaml_variants.items():
        upstream = load_yaml(vendor / (stem + '.yaml'))
        rules = _personal_for(personal, slug, 'yaml')
        for client in platforms:
            config = build_config(upstream, rules, settings, runtime if client == 'mihomo' else None)
            outputs[f'{client}/{slug}.yaml'] = _header(meta['commit']) + yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=160)
    if ini_variants:
        from ini_support import build_ini
    for slug, stem in ini_variants.items():
        source_slug = 'standard' if slug == 'mainland' else slug
        base = load_yaml(vendor / (VARIANTS[source_slug] + '.yaml'))
        with (vendor / (stem + '.ini')).open(encoding='utf-8', newline='') as handle:
            ini = build_ini(handle.read(), _personal_for(personal, source_slug, 'ini'), settings, _primary(base))
        outputs[f'subconverter/{slug}.ini'] = _header(meta['commit']).replace('# ', '; ') + ini
    if stash_variants:
        from stash_support import build_stash_ini
        direct_source = (vendor / 'Custom_Direct.list').read_text(encoding='utf-8')
        for slug, stem in stash_variants.items():
            source_slug = 'standard' if slug == 'mainland' else slug
            base = load_yaml(vendor / (VARIANTS[source_slug] + '.yaml'))
            with (vendor / (stem + '.ini')).open(encoding='utf-8', newline='') as handle:
                ini = build_stash_ini(handle.read(), _personal_for(personal, source_slug, 'stash'), settings, _primary(base), direct_source)
            outputs[f'subconverter-stash/{slug}.ini'] = _header(meta['commit']).replace('# ', '; ') + ini
    return outputs


def _write_outputs(directory: Path, outputs: dict, commit: str, file_commits=None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for filename, content in outputs.items():
        target = directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, bytes) else content.encode('utf-8')
        target.write_bytes(data)
        hashes[filename] = hashlib.sha256(data).hexdigest()
    provenance = {k: (file_commits or {}).get(k, commit) for k in sorted(outputs)}
    revisions = set(provenance.values())
    manifest = {'upstream_commit': next(iter(revisions)) if len(revisions) == 1 else None,
                'files': dict(sorted(hashes.items())), 'file_upstream_commits': provenance}
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def _merge_existing(directory: Path, updates: dict[str, str], commit: str):
    """Keep untouched bytes and their original revision; never follow existing links."""
    merged, provenance = {}, {}
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValueError('Generated output target must be a regular directory')
    if directory.exists():
        paths = list(directory.rglob('*'))
        if any(path.is_symlink() for path in paths):
            raise ValueError('Existing generated output must not contain symlinks')
        meta_path = directory / 'manifest.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
        for path in paths:
            if path.is_file() and path != meta_path:
                name = path.relative_to(directory).as_posix()
                merged[name] = path.read_bytes()
                provenance[name] = meta.get('file_upstream_commits', {}).get(name, meta.get('upstream_commit'))
    merged.update(updates)
    provenance.update({name: commit for name in updates})
    return merged, provenance


def _replace_trees(pairs) -> None:
    backups, installed = [], []
    for _, target in pairs:
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise ValueError('Generated output target must be a regular directory, not a file or symlink')
    try:
        for staged, target in pairs:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = staged.parent / (target.name + '.previous')
            if target.exists():
                target.rename(backup)
                backups.append((backup, target))
            staged.rename(target)
            installed.append(target)
    except BaseException:
        for target in reversed(installed):
            shutil.rmtree(target)
        for backup, target in reversed(backups):
            backup.rename(target)
        raise
    for backup, _ in backups:
        shutil.rmtree(backup)


def _same_tree(left: Path, right: Path) -> bool:
    """Compare generated trees without touching existing timestamps or links."""
    if not right.is_dir() or right.is_symlink():
        return False
    expected = {p.relative_to(left): p for p in left.rglob('*') if p.is_file()}
    paths = list(right.rglob('*'))
    if any(p.is_symlink() for p in paths):
        return False
    actual = {p.relative_to(right): p for p in paths if p.is_file()}
    return expected.keys() == actual.keys() and all(expected[name].read_bytes() == actual[name].read_bytes() for name in expected)


def _publish_outputs(root: Path, outputs: dict, commit: str, provenance=None) -> bool:
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=root) as tmp:
        staged = Path(tmp) / 'generated'
        _write_outputs(staged, outputs, commit, provenance)
        if _same_tree(staged, root / 'dist'):
            return False
        _replace_trees([(staged, root / 'dist')])
    return True


def build(root: Path, *, formats='all', platform='all', variants=None) -> None:
    outputs = prepare_outputs(root, formats=formats, platform=platform, variants=variants)
    commit = json.loads((root / 'vendor/aethersailor/upstream.json').read_text())['commit']
    partial = formats != 'all' or platform != 'all' or variants is not None
    merged, provenance = _merge_existing(root / 'dist', outputs, commit) if partial else (outputs, None)
    changed = _publish_outputs(root, merged, commit, provenance)
    state = 'updated' if changed else 'unchanged'
    print(f'Built {len(outputs)} public templates: {state} (no subscription credentials).')


def check(root: Path, *, formats='all', platform='all', variants=None) -> None:
    vendor = root / 'vendor/aethersailor'
    meta = json.loads((vendor / 'upstream.json').read_text())
    yaml_variants, ini_variants, stash_variants, _ = _selection(formats, platform, variants)
    required = {'LICENSE'} | {stem + '.yaml' for stem in yaml_variants.values()}
    for slug, stem in {**ini_variants, **stash_variants}.items():
        required.update({stem + '.ini', VARIANTS['standard' if slug == 'mainland' else slug] + '.yaml'})
    if stash_variants:
        required.add('Custom_Direct.list')
    for name in required:
        if hashlib.sha256((vendor / name).read_bytes()).hexdigest() != meta['files'].get(name):
            raise ValueError('Vendored source hash mismatch; sync upstream instead of editing snapshots')
    outputs = prepare_outputs(root, formats=formats, platform=platform, variants=variants)
    dist = root / 'dist'
    manifest = json.loads((dist / 'manifest.json').read_text(encoding='utf-8'))
    files = {p.relative_to(dist).as_posix(): p.read_bytes() for p in dist.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    hashes = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
    if hashes != manifest.get('files') or set(manifest.get('file_upstream_commits', {})) != set(files):
        raise ValueError('Generated manifest does not match files; rebuild the affected outputs')
    revisions = list(manifest['file_upstream_commits'].values())
    if any(value is not None and not isinstance(value, str) for value in revisions):
        raise ValueError('Generated manifest contains invalid source revisions')
    unique_revisions = set(revisions)
    summary = next(iter(unique_revisions)) if len(unique_revisions) == 1 else None
    if manifest.get('upstream_commit') != summary:
        raise ValueError('Generated manifest source summary does not match per-file revisions')
    if formats == 'all' and platform == 'all' and variants is None and set(files) != set(outputs):
        raise ValueError('Generated output set is stale; run python scripts/rules.py build')
    for filename, content in outputs.items():
        if files.get(filename) != content.encode('utf-8') or manifest['file_upstream_commits'][filename] != meta['commit']:
            raise ValueError('Generated output is stale; run python scripts/rules.py build')
    print(f'Checked hashes, YAML keys, references and reproducibility for {len(outputs)} templates.')


def render_private(root: Path, secrets_path: Path, output: Path, variants=None) -> list[Path]:
    local = root.resolve() / '.local'
    resolved = output.resolve()
    if not resolved.is_relative_to(local) or resolved == local:
        raise ValueError('Private output must be a subdirectory of .local, never dist or a symlink outside .local')
    if not secrets_path.resolve().is_relative_to(local) or secrets_path.resolve().is_relative_to(resolved):
        raise ValueError('Private secrets must be in .local and outside the render output directory')
    secrets = load_yaml(secrets_path)
    url = _private_url(secrets.get('subscription_url'))
    selected = list(variants or [k for k in VARIANTS if not k.startswith('selfhosted-')])
    if not variants:
        if secrets.get('selfhost_subscription_url'):
            selected.append('selfhosted-provider-fallback')
        if secrets.get('selfhost_proxy'):
            selected.append('selfhosted-manual-fallback')
    if set(selected) - set(VARIANTS):
        raise ValueError('Unknown variant')
    public = prepare_outputs(root, formats='yaml', variants=selected)
    private = {}
    for filename, content in public.items():
        if not filename.endswith('.yaml') or Path(filename).stem not in selected:
            continue
        config = yaml.safe_load(content)
        config['proxy-providers']['provider1']['url'] = url
        if 'selfhost' in config['proxy-providers']:
            config['proxy-providers']['selfhost']['url'] = _private_url(secrets.get('selfhost_subscription_url'))
        if config.get('proxies'):
            node = secrets.get('selfhost_proxy')
            if not isinstance(node, dict) or not all(node.get(k) for k in ['type', 'server', 'port']):
                raise ValueError('selfhosted-manual-fallback requires a complete selfhost_proxy in private secrets')
            original_name = config['proxies'][0]['name']
            config['proxies'] = [{**node, 'name': original_name}]
        validate_config(config)
        private[filename] = '# PRIVATE: do not publish or commit.\n' + yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=160)
    local.mkdir(parents=True, exist_ok=True)
    commit = json.loads((root / 'vendor/aethersailor/upstream.json').read_text())['commit']
    merged, provenance = _merge_existing(resolved, private, commit)
    with tempfile.TemporaryDirectory(dir=local) as tmp:
        staged = Path(tmp) / 'rendered'
        _write_outputs(staged, merged, commit, provenance)
        for path in staged.rglob('*'):
            if path.is_file():
                path.chmod(0o600)
        _replace_trees([(staged, resolved)])
    return [resolved / name for name in private]


def _fetch(url: str) -> bytes:
    request = Request(url, headers={'User-Agent': 'personal-clash-rules/1.0'})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            break
        except OSError as error:
            retryable = not isinstance(error, HTTPError) or error.code in {408, 429, 500, 502, 503, 504}
            if not retryable or attempt == 2:
                raise ValueError('Upstream download failed; existing snapshots and outputs were preserved') from None
            time.sleep(attempt + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError('Unexpectedly large upstream resource')
    return data


def _snapshot_matches(vendor: Path, commit: str) -> bool:
    """Reuse only a complete, integrity-checked snapshot of this exact revision."""
    try:
        meta = json.loads((vendor / 'upstream.json').read_text(encoding='utf-8'))
        if (not isinstance(meta, dict) or meta.get('repository') != REPOSITORY
                or meta.get('commit') != commit or not isinstance(meta.get('files'), dict)
                or set(meta['files']) != set(UPSTREAM_FILES)):
            return False
        return all((vendor / name).is_file() and not (vendor / name).is_symlink()
                   and hashlib.sha256((vendor / name).read_bytes()).hexdigest() == meta['files'][name]
                   for name in UPSTREAM_FILES)
    except (OSError, ValueError, TypeError):
        return False


def sync(root: Path, ref: str | None = None) -> None:
    if ref is None:
        upstream = load_yaml(root / 'config/upstream.yaml')
        if set(upstream) != {'ref'} or not isinstance(upstream['ref'], str):
            raise ValueError('config/upstream.yaml must contain a ref string (main or full commit SHA)')
        ref = upstream['ref']
    if re.fullmatch(r'[0-9a-fA-F]{40}', ref):
        commit = ref.lower()
    elif ref == 'main':
        try:
            data = json.loads(_fetch(f'https://api.github.com/repos/{REPOSITORY}/commits/main'))
            commit = data.get('sha', '')
        except ValueError:
            # Git's public ref advertisement is independent of the REST API rate limit.
            try:
                result = subprocess.run(
                    ['git', 'ls-remote', f'https://github.com/{REPOSITORY}.git', 'refs/heads/main'],
                    capture_output=True, text=True, timeout=45, check=True,
                    env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
                )
                commit = result.stdout.split()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                raise ValueError('Unable to resolve upstream main through GitHub API or Git; try a pinned SHA') from None
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Unable to resolve upstream commit')
    else:
        raise ValueError('--ref must be main or a full 40-character commit SHA')
    if _snapshot_matches(root / 'vendor/aethersailor', commit):
        # Personal rules, runtime settings or generator code may have changed,
        # even when upstream has not. Recompose locally before checking outputs.
        outputs = prepare_outputs(root)
        changed = _publish_outputs(root, outputs, commit)
        state = 'updated from local inputs' if changed else 'unchanged'
        print(f'Upstream {commit} is unchanged; verified cached sources reused, outputs {state}.')
        return
    # Fetch fixed paths from one immutable commit; never execute code from upstream.
    with ThreadPoolExecutor(max_workers=4) as pool:
        names = list(UPSTREAM_FILES)
        blobs = dict(zip(names, pool.map(lambda name: _fetch(f'https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{quote(UPSTREAM_FILES[name])}'), names)))
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=root) as tmp:
        vendor = Path(tmp) / 'sources'
        vendor.mkdir()
        for name, blob in blobs.items():
            (vendor / name).write_bytes(blob)
        meta = {'repository': REPOSITORY, 'commit': commit, 'files': {k: hashlib.sha256(v).hexdigest() for k, v in sorted(blobs.items())}}
        (vendor / 'upstream.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8', newline='\n')
        outputs = prepare_outputs(root, vendor_dir=vendor)
        staged = Path(tmp) / 'generated'
        _write_outputs(staged, outputs, commit)
        replacements = [(vendor, root / 'vendor/aethersailor')]
        if not _same_tree(staged, root / 'dist'):
            replacements.append((staged, root / 'dist'))
        _replace_trees(replacements)
    print(f'Synced upstream {commit}; regenerated {len(outputs)} templates. Personal rules preserved.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, help_text in [('build', 'Build selected public templates offline'),
                            ('check', 'Check selected snapshots and generated output without rewriting')]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument('--format', dest='formats', choices=['all', 'yaml', 'ini'], default='all')
        command.add_argument('--platform', choices=['all', 'openclash', 'mihomo', 'stash'], default='all')
        command.add_argument('--variant', action='append', choices=list(VARIANTS) + ['mainland'])
    syncing = commands.add_parser('sync', help='Fetch a pinned upstream revision and rebuild all templates')
    syncing.add_argument('--ref', help='One-shot override; otherwise use config/upstream.yaml')
    rendering = commands.add_parser('render', help='Render private configurations only into .local')
    rendering.add_argument('--secrets', default='.local/secrets.yaml')
    rendering.add_argument('--output', default='.local/rendered')
    rendering.add_argument('--variant', action='append', choices=VARIANTS)
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            build(ROOT, formats=args.formats, platform=args.platform, variants=args.variant)
        elif args.command == 'check':
            check(ROOT, formats=args.formats, platform=args.platform, variants=args.variant)
        elif args.command == 'sync':
            sync(ROOT, args.ref)
        else:
            paths = render_private(ROOT, ROOT / args.secrets, ROOT / args.output, args.variant)
            print(f'Rendered {len(paths)} private YAML files inside .local (credentials not printed).')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Never include YAML excerpts or URL values in diagnostics.
        message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else 'Invalid input or filesystem/network error; check input files and permissions'
        print('Error: ' + message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
