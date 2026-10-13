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
BUILTINS = {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'PASS-RULE', 'COMPATIBLE'}
PLACEHOLDER = 'https://example.com/REPLACE_WITH_YOUR_SUBSCRIPTION_URL'
SELFHOST_PLACEHOLDER = 'https://example.com/REPLACE_WITH_YOUR_SELFHOST_SUBSCRIPTION_URL'
UPSTREAM_FILES = {v + '.yaml': 'cfg/yaml/' + v + '.yaml' for v in VARIANTS.values()}
UPSTREAM_FILES.update({v + '.ini': 'cfg/' + v + '.ini' for v in INI_VARIANTS.values()})
UPSTREAM_FILES['LICENSE'] = 'LICENCE'


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
        base['proxy-groups'].insert(0, {'name': ads['group'], 'type': 'select', 'proxies': ['REJECT', 'PASS']})
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


def _personal_for(personal: dict, slug: str) -> dict:
    unknown = set(personal) - {'before_ads', 'after_ads', 'variants'}
    variants = personal.get('variants', {})
    if unknown or not isinstance(variants, dict) or set(variants) - set(VARIANTS):
        raise ValueError('Unknown personal rule section or template variant')
    extra = variants.get(slug, {})
    if not isinstance(extra, dict) or set(extra) - {'before_ads', 'after_ads'}:
        raise ValueError('Invalid variant-specific personal rule section')
    merged = {}
    for key in ['before_ads', 'after_ads']:
        left, right = personal.get(key, []), extra.get(key, [])
        if not isinstance(left, list) or not isinstance(right, list):
            raise ValueError('Personal rule sections must be lists')
        merged[key] = left + right
    return merged


def _header(commit: str, private=False) -> str:
    return (f'# Generated by personal-clash-rules; upstream {REPOSITORY}@{commit}\n'
            '# Aethersailor derivatives: CC BY-SA 4.0. See LICENSE and NOTICE.md.\n'
            '# Edit rules/custom.yaml and rebuild; do not edit generated routing.\n'
            + ('# PRIVATE: contains your subscription/node credentials. Do not publish.\n' if private
               else '# PUBLIC TEMPLATE: fill provider URLs locally, or use the render command.\n'))


def prepare_outputs(root: Path, vendor_dir: Path | None = None, subscription_url=None) -> dict[str, str]:
    if subscription_url is not None:
        raise ValueError('Use render_private for credentials; public builds only contain placeholders')
    vendor = vendor_dir or root / 'vendor/aethersailor'
    meta = json.loads((vendor / 'upstream.json').read_text())
    settings = load_yaml(root / 'config/settings.yaml')
    personal = load_yaml(root / 'rules/custom.yaml')
    runtime = load_yaml(root / 'templates/mihomo-runtime.yaml')
    outputs = {}
    from ini_support import build_ini
    for slug, stem in VARIANTS.items():
        upstream = load_yaml(vendor / (stem + '.yaml'))
        rules = _personal_for(personal, slug)
        for platform in ['openclash', 'mihomo']:
            config = build_config(upstream, rules, settings, runtime if platform == 'mihomo' else None)
            outputs[f'{platform}/{slug}.yaml'] = _header(meta['commit']) + yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=160)
    for slug, stem in INI_VARIANTS.items():
        source_slug = 'standard' if slug == 'mainland' else slug
        base = load_yaml(vendor / (VARIANTS[source_slug] + '.yaml'))
        with (vendor / (stem + '.ini')).open(encoding='utf-8', newline='') as handle:
            ini = build_ini(handle.read(), _personal_for(personal, source_slug), settings, _primary(base))
        outputs[f'subconverter/{slug}.ini'] = _header(meta['commit']).replace('# ', '; ') + ini
    return outputs


def _write_outputs(directory: Path, outputs: dict[str, str], commit: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in outputs.items():
        target = directory / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8', newline='\n')
    manifest = {'upstream_commit': commit, 'files': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(outputs.items())}}
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


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


def build(root: Path) -> None:
    outputs = prepare_outputs(root)
    commit = json.loads((root / 'vendor/aethersailor/upstream.json').read_text())['commit']
    with tempfile.TemporaryDirectory(prefix='.sync-', dir=root) as tmp:
        staged = Path(tmp) / 'generated'
        _write_outputs(staged, outputs, commit)
        _replace_trees([(staged, root / 'dist')])
    print(f'Built {len(outputs)} public templates (no subscription credentials).')


def check(root: Path) -> None:
    vendor = root / 'vendor/aethersailor'
    meta = json.loads((vendor / 'upstream.json').read_text())
    for name in UPSTREAM_FILES:
        if hashlib.sha256((vendor / name).read_bytes()).hexdigest() != meta['files'].get(name):
            raise ValueError('Vendored source hash mismatch; sync upstream instead of editing snapshots')
    outputs = prepare_outputs(root)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp)
        _write_outputs(staged, outputs, meta['commit'])
        expected = {p.relative_to(staged): p.read_bytes() for p in staged.rglob('*') if p.is_file()}
        actual = {p.relative_to(root / 'dist'): p.read_bytes() for p in (root / 'dist').rglob('*') if p.is_file()}
        if actual != expected:
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
    public = prepare_outputs(root)
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
    with tempfile.TemporaryDirectory(dir=local) as tmp:
        staged = Path(tmp) / 'rendered'
        _write_outputs(staged, private, 'private-local')
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


def sync(root: Path, ref: str) -> None:
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
        _replace_trees([(vendor, root / 'vendor/aethersailor'), (staged, root / 'dist')])
    print(f'Synced upstream {commit}; regenerated {len(outputs)} templates. Personal rules preserved.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('build', help='Build all public templates offline')
    commands.add_parser('check', help='Check snapshots and generated output without rewriting')
    syncing = commands.add_parser('sync', help='Fetch a pinned upstream revision and rebuild all templates')
    syncing.add_argument('--ref', default='main')
    rendering = commands.add_parser('render', help='Render private configurations only into .local')
    rendering.add_argument('--secrets', default='.local/secrets.yaml')
    rendering.add_argument('--output', default='.local/rendered')
    rendering.add_argument('--variant', action='append', choices=VARIANTS)
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            build(ROOT)
        elif args.command == 'check':
            check(ROOT)
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
