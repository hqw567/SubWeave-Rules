#!/usr/bin/env python3
"""Validate public YAML with pinned Mihomo -t, fixtures and real public rule data.

Never starts Mihomo normally. Subscription sources are replaced by local test
nodes. Real public rule-provider payloads and GeoData are parsed by the core;
this does not test subscriptions, connectivity, DNS interception or ad coverage.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

import yaml

from filter_profiles import FILTER_PROFILES
from rules import ROOT, VARIANTS, PLACEHOLDER, SELFHOST_PLACEHOLDER, load_yaml, validate_public_url


# SHA256 digests from the official GitHub release asset API for v1.19.32.
# Updating the version pin requires reviewing and updating these digests too.
# https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/v1.19.32
PIN = 'v1.19.32'
ASSETS = {
    ('linux', 'amd64'): ('mihomo-linux-amd64-v1-v1.19.32.gz', '306f81e723e60ce6b828899a6fe83e1d00e9ecefb2dc8d4d849312a5bc00efdc'),
    ('linux', 'arm64'): ('mihomo-linux-arm64-v1.19.32.gz', '9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0'),
    ('darwin', 'amd64'): ('mihomo-darwin-amd64-v1.19.32.gz', 'b7de9fc46af2ca985ecfb302a6362170e04ff2023dee1e82addc54133e669bc9'),
    ('darwin', 'arm64'): ('mihomo-darwin-arm64-v1.19.32.gz', '3312a6780652c622890fd4357c6a853bbf865464fd047ac7b7f52dab8de18652'),
}
DEFAULT_GEODATA = {
    'geoip': 'https://testingcf.jsdelivr.net/gh/Loyalsoldier/v2ray-rules-dat@release/geoip.dat',
    'geosite': 'https://testingcf.jsdelivr.net/gh/Loyalsoldier/v2ray-rules-dat@release/geosite.dat',
    'mmdb': 'https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb',
    'asn': 'https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/GeoLite2-ASN.mmdb',
}
RULE_WARNINGS = ('parse classical rule', 'skip invalid domain from rule provider', 'invalid ipcidr:')
LIMIT = 128 * 1024 * 1024


class NativeCheckError(ValueError):
    """A safe diagnostic containing no input values or native log excerpts."""


def clean_environment() -> dict[str, str]:
    # Environment overrides can replace -f input or supply lifecycle scripts.
    return {key: value for key, value in os.environ.items()
            if not key.startswith(('CLASH_', 'MIHOMO_'))}


def public_resource_urls(url: str) -> list[str]:
    """Known GitHub CDN aliases may fall back to the same repository/path."""
    parts = urlsplit(url)
    hosts = {'cdn.jsdelivr.net', 'testingcf.jsdelivr.net', 'fastly.jsdelivr.net', 'gcore.jsdelivr.net'}
    match = re.fullmatch(r'/gh/([^/]+)/([^/@]+)@([^/]+)/(.+)', parts.path)
    if parts.scheme == 'https' and parts.hostname in hosts and parts.port in (None, 443) and match:
        owner, repo, ref, path = match.groups()
        return [url, f'https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}']
    return [url]


def fetch_public(url: str) -> bytes:
    validate_public_url(url)
    candidates = public_resource_urls(url)
    for attempt in range(3):
        for candidate in candidates:
            try:
                with urlopen(Request(candidate, headers={'User-Agent': 'personal-clash-rules-native-check/2'}), timeout=60) as response:
                    data = response.read(LIMIT + 1)
            except (OSError, HTTPError):
                continue
            if len(data) > LIMIT:
                raise NativeCheckError('Public validation resource exceeds the size limit')
            if data:
                if candidate != url:
                    print('Public CDN resource fetched from its GitHub origin.', flush=True)
                return data
        if attempt < 2:
            time.sleep(attempt + 1)
    raise NativeCheckError('Public validation resource download failed; publication must stop')


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def locate_binary(root: Path, download: bool = False, binary: Path | None = None) -> Path:
    version = (root / 'config/mihomo-version.txt').read_text(encoding='utf-8').strip()
    if version != PIN:
        raise NativeCheckError('Mihomo version pin and reviewed release checksums disagree')
    if binary is None:
        machine = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine().lower(), platform.machine().lower())
        key = (platform.system().lower(), machine)
        if key not in ASSETS:
            raise NativeCheckError('Automatic Mihomo download supports Linux/macOS amd64/arm64; use --binary on other platforms')
        name, digest = ASSETS[key]
        archive = root / '.local/tools' / name
        binary = root / '.local/tools' / f'mihomo-{version}-{key[0]}-{key[1]}'
        if not archive.is_file():
            if not download:
                raise NativeCheckError('Pinned Mihomo is not cached; pass --download or --binary PATH')
            data = fetch_public(f'https://github.com/MetaCubeX/mihomo/releases/download/{version}/{name}')
        else:
            data = archive.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise NativeCheckError('Official Mihomo archive checksum mismatch; do not execute it')
        _atomic_write(archive, data)
        try:
            executable = gzip.decompress(data)
        except (OSError, EOFError):
            raise NativeCheckError('Invalid official Mihomo archive') from None
        # Re-extract a verified archive so a changed cached executable is not trusted.
        _atomic_write(binary, executable)
        binary.chmod(0o755)
    binary = binary.resolve()
    try:
        result = subprocess.run([str(binary), '-v'], capture_output=True, text=True, timeout=15, env=clean_environment())
    except (OSError, subprocess.TimeoutExpired):
        raise NativeCheckError('Cannot execute the selected Mihomo binary') from None
    if result.returncode or not re.search(r'\bMihomo Meta ' + re.escape(version) + r'(?:\s|$)', result.stdout):
        raise NativeCheckError('Selected Mihomo binary does not match the pinned stable version')
    return binary


def public_config(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    if '# PUBLIC TEMPLATE:' not in text[:1024] or '# PRIVATE' in text[:1024]:
        raise NativeCheckError('Native checker accepts generated public templates only, never private render output')
    config = load_yaml(path)
    for provider in config.get('proxy-providers', {}).values():
        if provider.get('type') != 'http' or provider.get('url') not in {PLACEHOLDER, SELFHOST_PLACEHOLDER} or provider.get('header'):
            raise NativeCheckError('Node sources must contain public placeholders, without subscription credentials')
    for node in config.get('proxies', []):
        if node.get('server') != 'selfhost.example.com' or node.get('uuid') != '00000000-0000-0000-0000-000000000000':
            raise NativeCheckError('Static nodes must contain the generated public example, never private credentials')
    return config


def fixture_config(config: dict, home: Path) -> dict:
    """Replace only subscription transport; preserve group filters and overrides."""
    result = copy.deepcopy(config)
    nodes = [{'name': name + ' native-check', 'type': 'socks5', 'server': '127.0.0.1', 'port': 9}
             for name in ('香港 HK', '美国 US', '日本 JP', '新加坡 SG', '台湾 TW', '韩国 KR')]
    for index, provider in enumerate(result.get('proxy-providers', {}).values()):
        file = home / f'fixture-provider-{index}.yaml'
        file.write_text(yaml.safe_dump({'proxies': nodes}, allow_unicode=True), encoding='utf-8')
        provider['type'] = 'file'
        provider['path'] = file.name
        provider.pop('url', None)
        provider.pop('header', None)
        # -t never initializes health checks; retaining their settings validates schema.
    # OpenClash's minimal template relies on its documented GeoIP DAT mode.
    # Standalone Mihomo already declares its runtime mode and keeps that value.
    result.setdefault('geodata-mode', True)
    result.setdefault('geodata-loader', 'memconservative')
    return result


def run_native(binary: Path, home: Path, config: Path, label: str = 'configuration', timeout: int = 120) -> None:
    try:
        result = subprocess.run([str(binary), '-t', '-d', str(home), '-f', str(config)],
                                capture_output=True, text=True, timeout=timeout, env=clean_environment(), cwd=home)
    except subprocess.TimeoutExpired:
        raise NativeCheckError(f'Native validation timed out for {label}') from None
    except OSError:
        raise NativeCheckError('Unable to execute native validation') from None
    logs = (result.stdout + result.stderr).lower()
    if result.returncode or any(marker in logs for marker in RULE_WARNINGS):
        # Do not echo core logs: they can include arbitrary values from input YAML.
        reason = 'invalid rule-provider payload' if any(marker in logs for marker in RULE_WARNINGS) else 'configuration rejected'
        raise NativeCheckError(f'Native validation failed for {label}: {reason}; inspect rule syntax, group references and GeoData categories')


class PublicResources:
    """Fresh public resources per invocation, shared across all templates."""
    def __init__(self, binary: Path, home: Path):
        self.binary, self.home = binary, home
        self.downloads: dict[str, Path] = {}
        self.payloads: dict[tuple[str, str, str], list[str]] = {}

    def download(self, url: str) -> Path:
        validate_public_url(url)
        if url not in self.downloads:
            path = self.home / ('resource-' + hashlib.sha256(url.encode()).hexdigest())
            _atomic_write(path, fetch_public(url))
            self.downloads[url] = path
        return self.downloads[url]

    def payload(self, provider: dict) -> list[str]:
        if provider.get('type') == 'inline':
            payload = provider.get('payload')
        elif provider.get('type') == 'http':
            url = provider.get('url')
            validate_public_url(url)
            if provider.get('header'):
                raise NativeCheckError('Public rule sources with request credentials are not supported')
            behavior, format = provider.get('behavior'), provider.get('format', 'yaml')
            key = (url, behavior, format)
            if key in self.payloads:
                return self.payloads[key]
            path = self.download(url)
            if format == 'mrs':
                if behavior not in {'domain', 'ipcidr'}:
                    raise NativeCheckError('MRS providers must use domain or ipcidr behavior')
                target = path.with_suffix('.txt')
                try:
                    converted = subprocess.run([str(self.binary), 'convert-ruleset', behavior, 'mrs', str(path), str(target)],
                                               capture_output=True, timeout=60, env=clean_environment(), cwd=self.home)
                except (OSError, subprocess.TimeoutExpired):
                    raise NativeCheckError('Native MRS conversion could not complete') from None
                # The pinned converter parses the MRS before testing Count().
                # A successfully decoded zero-entry provider raises this exact
                # error; empty reserved providers are valid Mihomo resources.
                empty_mrs = converted.stderr.startswith(b'panic: empty rule\n')
                if converted.returncode and not empty_mrs:
                    raise NativeCheckError('Native MRS validation rejected a public rule resource')
                payload = [] if empty_mrs else target.read_text(encoding='utf-8').splitlines()
            elif format == 'yaml':
                payload = load_yaml(path).get('payload')
            elif format == 'text':
                payload = [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
                           if line.strip() and not line.lstrip().startswith(('#', '//'))]
            else:
                raise NativeCheckError('Unsupported public rule resource format')
        else:
            raise NativeCheckError('Native validation supports public HTTP and inline rule providers; bundle local rule files explicitly first')
        if not isinstance(payload, list) or any(not isinstance(rule, str) for rule in payload):
            raise NativeCheckError('Public rule resource must contain a string payload list (which may be empty)')
        if provider.get('type') == 'http':
            self.payloads[key] = payload
        return payload

    def prepare(self, config: dict) -> None:
        for provider in config.get('rule-providers', {}).values():
            # -t does not call provider.Initial(). Supplying the *real* downloaded
            # payload as fallback makes the native parser inspect every entry
            # while preserving the original HTTP provider schema and behavior.
            try:
                downloaded = self.payload(provider)
            except (ValueError, OSError, yaml.YAMLError):
                raise NativeCheckError('A public rule-provider resource could not be downloaded or decoded') from None
            original_fallback = provider.get('payload', []) if provider.get('type') == 'http' else []
            if not isinstance(original_fallback, list) or any(not isinstance(rule, str) for rule in original_fallback):
                raise NativeCheckError('A public rule provider has an invalid fallback payload')
            provider['payload'] = downloaded + original_fallback
        urls = {**DEFAULT_GEODATA, **config.get('geox-url', {})}
        required = {'geosite': 'GeoSite.dat'}
        required['geoip' if config['geodata-mode'] else 'mmdb'] = 'GeoIP.dat' if config['geodata-mode'] else 'Country.mmdb'
        if any('IP-ASN,' in rule for rule in config.get('rules', [])):
            required['asn'] = 'ASN.mmdb'
        for key, filename in required.items():
            try:
                shutil.copyfile(self.download(urls[key]), self.home / filename)
            except (ValueError, OSError):
                raise NativeCheckError(f'Public GeoData resource {key} could not be downloaded') from None


def check_all(root: Path, directory: Path, binary: Path, timeout: int = 120) -> int:
    expected = [Path(f'{profile}/{platform_name}/{slug}.yaml') for profile in FILTER_PROFILES for platform_name in ('openclash', 'mihomo') for slug in VARIANTS]
    if not all((directory / path).is_file() for path in expected):
        raise NativeCheckError('Native validation requires all generated public YAML templates across filter profiles')
    # Validate the privacy boundary for every input before downloading or running.
    configs = [(path, public_config(directory / path)) for path in expected]
    local = root / '.local/native-check'
    local.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=local) as temporary:
        home = Path(temporary).resolve()
        resources = PublicResources(binary, home)
        for relative, original in configs:
            config = fixture_config(original, home)
            resources.prepare(config)
            path = home / 'config.yaml'
            path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
            run_native(binary, home, path, relative.as_posix(), timeout)
            print(f'Native check passed: {relative.as_posix()}', flush=True)
    return len(configs)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Download the checksum-pinned official core into .local/tools')
    parser.add_argument('--binary', type=Path, help='Use an existing binary matching config/mihomo-version.txt')
    parser.add_argument('--prepare-only', action='store_true', help='Verify/install the pinned core without fetching rules or validating configs')
    parser.add_argument('--github-output', type=Path, help='Append binary_path to a GitHub Actions output file (prepare-only)')
    parser.add_argument('--config-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--timeout', type=int, default=120, help='Maximum seconds per native parse')
    args = parser.parse_args(argv)
    try:
        if args.timeout <= 0:
            raise NativeCheckError('Native validation timeout must be positive')
        if args.github_output and not args.prepare_only:
            raise NativeCheckError('--github-output requires --prepare-only')
        binary = locate_binary(ROOT, args.download, args.binary)
        if args.prepare_only:
            if args.github_output:
                if any(character in str(binary) for character in '\r\n'):
                    raise NativeCheckError('Prepared binary path contains an invalid newline')
                with args.github_output.open('a', encoding='utf-8') as output:
                    output.write(f'binary_path={binary}\n')
            print(f'Prepared checksum-pinned Mihomo {PIN}.')
            return 0
        count = check_all(ROOT, args.config_dir.resolve(), binary, args.timeout)
        print(f'Validated {count} public YAML templates with Mihomo {PIN}, real public rules/GeoData and placeholder nodes; no tunnels or subscriptions started.')
    except NativeCheckError as exc:
        print(f'Native validation failed: {exc}. Publishing is blocked.', file=sys.stderr)
        return 1
    except (ValueError, OSError, TypeError, KeyError, yaml.YAMLError):
        # Deliberately redact arbitrary exception content (including YAML excerpts).
        print('Native validation failed. Check public inputs, pinned core, rule resources and network availability; publishing is blocked.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
