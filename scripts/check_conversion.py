#!/usr/bin/env python3
"""Check candidate INI files through a pinned real SubConverter-Extended server.

Uses only six synthetic documentation-address nodes plus an example.com remote
provider. No private subscription is accepted. The temporary conversion service
listens on loopback, validates candidate files rather than published main, and
is stopped on success or failure. Both shared target=clash and additional
target=stash candidate templates are checked. This does not run the Stash app
or infer its capabilities from the converter's filtering behavior.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener

import yaml

from check_mihomo import PublicResources, fetch_public, locate_binary, run_native
from filter_profiles import FILTER_PROFILES, profile_settings
from rules import ROOT, INI_VARIANTS, load_yaml, validate_public_url


PIN = 'v1.10.5'
REVISION = '7a75c1491012d96f5821ceddc8aa25ccbc0220da'
# Official release asset API digests, reviewed alongside the pinned source.
# https://api.github.com/repos/Aethersailor/SubConverter-Extended/releases/tags/v1.10.5
CHECKSUMS = {
    'amd64': '9d13fc3a1d1d922627a5e80e0b600347ea701ccec302d00027ad133166b5b030',
    'arm64': 'd81914387e0b28742465c3c6b648097d786efcb07af02fc5eae957f8911a9680',
}
SYNTHETIC_PROVIDER = 'https://example.com/converter-fixture.yaml'
LIMIT = 16 * 1024 * 1024
BEHAVIORS = {'clash-domain': 'domain', 'clash-ipcidr': 'ipcidr', 'clash-classic': 'classical'}
BUILTINS = {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'PASS-RULE', 'COMPATIBLE'}


class ConversionError(ValueError):
    """Safe diagnostic that never contains a source URL or node credentials."""


def synthetic_sources() -> str:
    credential = base64.b64encode(b'aes-128-gcm:public-conversion-test-only').decode()
    nodes = [f'ss://{credential}@192.0.2.{index}:443#{region}-fixture'
             for index, region in enumerate(('HK', 'US', 'JP', 'SG', 'TW', 'KR'), 1)]
    return '|'.join(nodes + [SYNTHETIC_PROVIDER])


def locate_archive(root: Path, download: bool = False) -> Path:
    if (root / 'config/converter-version.txt').read_text(encoding='utf-8').strip() != PIN:
        raise ConversionError('Converter version pin and reviewed checksums disagree')
    machine = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine().lower(), platform.machine().lower())
    if platform.system() != 'Linux' or machine not in CHECKSUMS:
        raise ConversionError('Pinned converter check runs on Linux amd64/arm64, including WSL and GitHub Actions')
    name = f'SubConverter-Extended-{PIN}-linux-{machine}.tar.gz'
    path = root / '.local/tools' / name
    if not path.is_file():
        if not download:
            raise ConversionError('Pinned converter archive is missing; pass --download')
        blob = fetch_public(f'https://github.com/Aethersailor/SubConverter-Extended/releases/download/{PIN}/{name}')
        if hashlib.sha256(blob).hexdigest() != CHECKSUMS[machine]:
            raise ConversionError('Official converter archive checksum mismatch')
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(blob)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != CHECKSUMS[machine]:
        raise ConversionError('Cached converter archive checksum mismatch; refusing execution')
    return path


def unpack_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, 'r:gz') as bundle:
        for item in bundle.getmembers():
            path = root / item.name
            if item.name.startswith('/') or not path.resolve().is_relative_to(root) or item.isdev() or item.isfifo():
                raise ConversionError('Unsafe path in converter archive')
            if item.issym() or item.islnk():
                link = (path.parent if item.issym() else root) / item.linkname
                if not link.resolve().is_relative_to(root):
                    raise ConversionError('Unsafe link in converter archive')
        # Archive contents are hash-pinned above. Validate paths explicitly for
        # Python 3.10 support, which does not universally offer tar data filters.
        if hasattr(tarfile, 'data_filter'):
            bundle.extractall(root, filter='data')
        else:
            bundle.extractall(root)
    tool = root / 'SubConverter-Extended'
    info = json.loads((tool / 'BUILD-INFO.json').read_text(encoding='utf-8'))
    if info.get('version') != PIN or info.get('revision') != REVISION:
        raise ConversionError('Official converter build identity does not match the pin')
    return tool


def _preference(port: int) -> str:
    return f'''[common]
clash_rule_base=base/all_base.tpl
stash_rule_base=base/stash.yaml
base_path=base
default_external_config=
fallback_to_default_external_config=false
enable_insert=false
enable_filter=false
proxy_config=NONE
proxy_ruleset=NONE
proxy_subscription=NONE
[node_pref]
clash_use_new_field_name=true
[managed_config]
managed_config_prefix=http://127.0.0.1:{port}
[security]
profile=lan
[statistics]
enabled=false
[rulesets]
enabled=true
overwrite_original_rules=true
[server]
listen=127.0.0.1
port={port}
serve_file_root=
[advanced]
log_level=error
print_debug_info=false
max_concurrent_threads=2
max_server_threads=4
max_allowed_rulesets=256
request_deadline_ms=90000
enable_cache=false
'''


class LocalConverter:
    def __init__(self, endpoint: str, home: Path):
        self.endpoint, self.home = endpoint, home
        self.opener = build_opener(ProxyHandler({}))

    def convert(self, source_text: str, target: str) -> dict:
        if target not in {'clash', 'stash'}:
            raise ConversionError('Conversion target must be clash or stash')
        parse_template(source_text)  # forbid executable template/source features
        name = 'candidate-' + hashlib.sha256(source_text.encode()).hexdigest() + '.ini'
        (self.home / name).write_text(source_text, encoding='utf-8', newline='')
        query = urlencode({'target': target, 'url': synthetic_sources(), 'config': name,
                           'new_name': 'true', 'expand': 'false', 'list': 'false'})
        try:
            with self.opener.open(self.endpoint + '/sub?' + query, timeout=100) as response:
                data = response.read(LIMIT + 1)
        except HTTPError as error:
            # Converter responses may embed arbitrary template strings. Never log them.
            raise ConversionError(f'{target} converter returned HTTP {error.code}') from None
        except (OSError, URLError):
            raise ConversionError(f'{target} conversion request did not complete') from None
        if len(data) > LIMIT:
            raise ConversionError('Converted configuration exceeds the response size limit')
        try:
            config = yaml.safe_load(data)
        except (ValueError, yaml.YAMLError):
            raise ConversionError('Converter did not return valid YAML') from None
        if not isinstance(config, dict) or not config.get('proxy-groups') or not config.get('rules'):
            raise ConversionError('Converter did not return a full configuration')
        return config


@contextmanager
def local_converter(root: Path, archive: Path):
    parent = root / '.local/conversion-check'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=parent) as temporary:
        home = Path(temporary).resolve()
        tool = unpack_archive(archive, home / 'bundle')
        shutil.copytree(tool / 'base/base', home / 'base')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        preference = home / 'pref.ini'
        preference.write_text(_preference(port), encoding='utf-8')
        loaders = [(tool / 'lib64/ld-linux-x86-64.so.2', 'x86_64-linux-gnu'),
                   (tool / 'lib/ld-linux-aarch64.so.1', 'aarch64-linux-gnu'),
                   (tool / 'lib/aarch64-linux-gnu/ld-linux-aarch64.so.1', 'aarch64-linux-gnu')]
        found = next(((loader, arch) for loader, arch in loaders if loader.is_file()), None)
        if found is None:
            raise ConversionError('Bundled converter loader is missing')
        loader, arch = found
        libraries = ':'.join(str(tool / p) for p in (f'lib/{arch}', f'usr/lib/{arch}', 'lib', 'lib64', 'usr/lib'))
        command = [str(loader), '--library-path', libraries, str(tool / 'subconverter'), '-f', str(preference)]
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('SUBCONVERTER_', 'CLASH_', 'MIHOMO_')) and key not in {'PORT', 'PREF_PATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH'}}
        env['SUBCONVERTER_RUNTIME_STATE_FILE'] = str(home / 'runtime-state.json')
        converter = LocalConverter(f'http://127.0.0.1:{port}', home)
        with (home / 'converter.log').open('wb') as log:
            process = subprocess.Popen(command, cwd=home, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise ConversionError('Pinned loopback converter did not start')
                    try:
                        with converter.opener.open(converter.endpoint + '/healthz', timeout=1) as response:
                            if response.status == 200:
                                break
                    except (OSError, URLError):
                        time.sleep(0.1)
                yield converter
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


def parse_template(text: str) -> dict:
    groups, rules = [], []
    active = False
    allowed = {'ruleset', 'custom_proxy_group', 'enable_rule_generator', 'overwrite_original_rules'}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((';', '#')):
            continue
        if line.startswith('[') and line.endswith(']'):
            if line != '[custom]':
                raise ConversionError('Conversion fixture accepts only the generated custom section')
            if active:
                raise ConversionError('Duplicate custom section')
            active = True
            continue
        key, separator, value = line.partition('=')
        if not active or not separator or key not in allowed or any(token in value for token in ('!!import', 'script:', '!!script')):
            raise ConversionError('Unexpected executable or external-source directive in candidate INI')
        if key == 'custom_proxy_group':
            parts = value.split('`')
            if len(parts) < 3 or parts[1] not in {'select', 'url-test', 'fallback', 'load-balance'}:
                raise ConversionError('Unsupported candidate group shape')
            groups.append({'name': parts[0], 'type': parts[1], 'members': [p[2:] for p in parts[2:] if p.startswith('[]')]})
        elif key == 'ruleset':
            target, comma, source = value.partition(',')
            if not comma:
                raise ConversionError('Invalid candidate ruleset definition')
            if source.startswith('[]'):
                fields = source[2:].split(',')
                if fields[0] in {'MATCH', 'FINAL'}:
                    rules.append(('inline', 'MATCH,' + target))
                elif len(fields) >= 2:
                    rules.append(('inline', ','.join(fields[:2] + [target] + fields[2:])))
                else:
                    raise ConversionError('Invalid inline candidate rule')
            else:
                kind, colon, rest = source.partition(':')
                if not colon or kind not in BEHAVIORS:
                    raise ConversionError('Candidate rules must use explicitly typed public providers')
                fields = rest.split(',')
                if len(fields) not in {1, 2}:
                    raise ConversionError('Invalid candidate provider metadata')
                url = fields[0]
                validate_public_url(url)
                extension = Path(urlsplit(url).path).suffix.lower()
                format = {'.mrs': 'mrs', '.yaml': 'yaml', '.yml': 'yaml', '.txt': 'text'}.get(extension)
                if not format or (format == 'mrs' and kind == 'clash-classic'):
                    raise ConversionError('Provider source has an incompatible behavior or format')
                options = fields[1].split('|')[1:] if len(fields) == 2 else []
                if set(options) - {'no-resolve'}:
                    raise ConversionError('Unexpected provider options in candidate template')
                rules.append(('provider', url, BEHAVIORS[kind], format, target, tuple(options)))
        elif value.lower() != 'true':
            raise ConversionError('Candidate must generate rules and overwrite default base rules')
    if not active or not groups or not rules:
        raise ConversionError('Candidate INI is missing groups or rules')
    return {'groups': groups, 'rules': rules}


def canonical_rules(config: dict) -> list[tuple]:
    providers = config.get('rule-providers', {})
    result = []
    for rule in config['rules']:
        if not isinstance(rule, str):
            raise ConversionError('Converted rules must be strings')
        fields = rule.split(',')
        if fields[0] == 'RULE-SET':
            if len(fields) < 3 or fields[1] not in providers:
                raise ConversionError('Converted rule references a missing provider')
            provider = providers[fields[1]]
            result.append(('provider', provider.get('url'), provider.get('behavior'), provider.get('format', 'yaml'), fields[2], tuple(fields[3:])))
        else:
            result.append(('inline', rule))
    return result


def validate_converted(config: dict, source: str, target: str, settings: dict) -> None:
    expected = parse_template(source)
    groups = config.get('proxy-groups', [])
    if [group.get('name') for group in groups] != [group['name'] for group in expected['groups']]:
        raise ConversionError('Final strategy-group order differs from the candidate template')
    if canonical_rules(config) != expected['rules']:
        raise ConversionError('Final rule sequence, policies or provider formats differ from the candidate template')
    names = {group['name'] for group in groups}
    if len(names) != len(groups):
        raise ConversionError('Final strategy groups contain duplicate names')
    node_names = {node['name'] for node in config.get('proxies', [])}
    providers = config.get('proxy-providers', {})
    if not node_names or not providers or any(provider.get('url') != SYNTHETIC_PROVIDER for provider in providers.values()):
        raise ConversionError('Synthetic nodes or synthetic remote provider did not survive conversion')
    for node in config.get('proxies', []):
        if node.get('server') not in {f'192.0.2.{index}' for index in range(1, 7)}:
            raise ConversionError('Converted output unexpectedly contains a non-fixture node')
    primary = next((name for name in ('🚀 手动选择', '🚀 故障转移') if name in names), None)
    ads = settings.get('filter', {})
    if ads.get('enabled'):
        ad = groups[-1]
        if ad.get('name') != ads.get('group') or ad.get('type') != 'select' or ad.get('proxies') != ['REJECT', primary]:
            raise ConversionError('Advertising selector must be last with REJECT and the existing primary group')
        if not any(rule[0] == 'provider' and rule[1] == ads.get('url') and rule[4] == ads.get('group') for rule in canonical_rules(config)):
            raise ConversionError('Advertising provider or routing policy was lost in conversion')
    for original, group in zip(expected['groups'], groups):
        if group.get('type') != original['type']:
            raise ConversionError('Converter changed a requested strategy-group type')
        if not set(group.get('proxies', [])) <= names | node_names | BUILTINS or not set(group.get('use', [])) <= set(providers):
            raise ConversionError('Converted strategy group contains an unresolved reference')
        if {'PASS', 'PASS-RULE'} & set(group.get('proxies', [])):
            raise ConversionError('Converted groups must not reintroduce PASS policies')
    graph = {group['name']: [name for name in group.get('proxies', []) if name in names] for group in groups}
    visiting, visited = set(), set()
    def visit(name):
        if name in visiting:
            raise ConversionError('Converted strategy-group references contain a cycle')
        if name in visited:
            return
        visiting.add(name)
        for child in graph[name]:
            visit(child)
        visiting.remove(name)
        visited.add(name)
    for name in graph:
        visit(name)
    if target == 'stash':
        # Verify that the selected target used its own bundled base. Do not
        # maintain a speculative client field blacklist: Stash supports many
        # newer Clash fields, independently of this converter's projection.
        dns = config.get('dns', {})
        if not isinstance(dns, dict) or not dns.get('nameserver') or 'follow-rule' not in dns:
            raise ConversionError('Stash-target conversion did not use its expected native DNS base')


def validate_resources(root: Path, configs: list[dict], binary: Path) -> int:
    """Parse actual public Stash-target rule resources, without node sources."""
    unique = {}
    for config in configs:
        for provider in config.get('rule-providers', {}).values():
            url = provider.get('url')
            validate_public_url(url)
            key = (url, provider.get('behavior'), provider.get('format', 'yaml'))
            unique[key] = {'type': 'http', **provider}
    parent = root / '.local/conversion-check'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='resources-', dir=parent) as temporary:
        home = Path(temporary).resolve()
        resources = PublicResources(binary, home)
        native = {'mode': 'rule', 'geodata-mode': True, 'rule-providers': {}, 'rules': []}
        needs_geodata = False
        for index, provider in enumerate(unique.values()):
            try:
                payload = resources.payload(provider)
            except (ValueError, OSError, yaml.YAMLError):
                raise ConversionError(f'Public Stash-target rule resource {index + 1} could not be downloaded or decoded') from None
            name = f'resource-{index + 1}'
            native['rule-providers'][name] = {'type': 'inline', 'behavior': provider['behavior'], 'payload': payload}
            native['rules'].append(f'RULE-SET,{name},DIRECT')
            if provider['behavior'] == 'classical':
                needs_geodata |= any(any(token in rule for token in ('GEOIP,', 'GEOSITE,', 'IP-ASN,')) for rule in payload)
        native['rules'].append('MATCH,DIRECT')
        if needs_geodata:
            resources.prepare(native)
        path = home / 'resources.yaml'
        path.write_text(yaml.safe_dump(native, allow_unicode=True, sort_keys=False), encoding='utf-8')
        try:
            run_native(binary, home, path, 'public Stash-target rule resources')
        except ValueError:
            raise ConversionError('Native resource-format validation rejected a public Stash-target rule payload') from None
    return len(unique)


def check_all(root: Path, directory: Path, archive: Path, binary: Path | None = None) -> int:
    settings = load_yaml(root / 'config/settings.yaml')
    inputs = [(profile, target, slug, directory / profile / folder / f'{slug}.ini')
              for profile in FILTER_PROFILES
              for target, folder in (('clash', 'subconverter'), ('stash', 'subconverter-stash'))
              for slug in INI_VARIANTS]
    if not all(path.is_file() for _, _, _, path in inputs):
        raise ConversionError('Conversion regression requires all profile/target candidate INI files')
    sources = [(profile, target, slug, path.read_text(encoding='utf-8')) for profile, target, slug, path in inputs]
    for _, _, _, source in sources:
        parse_template(source)
    stash_configs = []
    with local_converter(root, archive) as converter:
        for profile, target, slug, source in sources:
            try:
                config = converter.convert(source, target)
                validate_converted(config, source, target, profile_settings(settings, profile))
                if profile == 'custom-only' and any('AWAvenue-Ads-Rule' in str(p.get('url', '')) for p in config.get('rule-providers', {}).values()):
                    raise ConversionError('Custom-only profile unexpectedly includes AWAvenue')
            except ConversionError as error:
                raise ConversionError(f'{profile}/{target}/{slug}: {error}') from None
            print(f'Conversion check passed: {profile}/{target}/{slug}', flush=True)
            if target == 'stash':
                stash_configs.append(config)
    if binary is None:
        binary = locate_binary(root)
    count = validate_resources(root, stash_configs, binary)
    print(f'Validated {count} unique public Stash-target rule resources with the pinned MRS decoder and rule parser (not the Stash app).', flush=True)
    return len(inputs)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Cache the checksum-pinned official Linux converter')
    parser.add_argument('--config-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args(argv)
    try:
        archive = locate_archive(ROOT, args.download)
        supplied_core = os.environ.get('MIHOMO_BINARY') or os.environ.get('MIHOMO_TEST_BINARY')
        binary = locate_binary(ROOT, args.download, Path(supplied_core) if supplied_core else None)
        count = check_all(ROOT, args.config_dir.resolve(), archive, binary)
        print(f'Validated {count} actual clash/stash conversions with SubConverter-Extended {PIN}; synthetic nodes only. Stash device import/connectivity is not tested.')
    except ConversionError as error:
        print(f'Conversion validation failed: {error}. Publishing is blocked.', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, tarfile.TarError):
        print('Conversion validation failed: invalid public input, archive, or network resource. Publishing is blocked.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
