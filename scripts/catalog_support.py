"""Versioned public template catalog, derived only from verified output metadata."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import quote

import yaml
from filter_profiles import DEFAULT_PROFILE, FILTER_PROFILES


NAMES = {
    'standard': '标准版', 'standard-fallback': '标准故障转移',
    'lite': '轻量版', 'lite-fallback': '轻量故障转移',
    'gfw': '极简 GFW', 'gfw-fallback': 'GFW 故障转移',
    'full': '完整分流', 'full-fallback': '完整故障转移',
    'selfhosted-provider-fallback': '自托管订阅故障转移',
    'selfhosted-manual-fallback': '自托管节点故障转移',
}
TARGETS = {'subconverter': 'clash', 'subconverter-stash': 'stash', 'mihomo': 'mihomo', 'openclash': 'openclash'}


def catalog_text(root: Path, manifest: dict, outputs: dict) -> str:
    publication = yaml.safe_load((root / 'config/catalog.yaml').read_text(encoding='utf-8'))
    if (not isinstance(publication, dict) or set(publication) != {'repository', 'ref'}
            or not isinstance(publication['repository'], str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', publication['repository'])
            or not isinstance(publication['ref'], str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', publication['ref'])):
        raise ValueError('Catalog publication must name a public GitHub repository and branch/ref')
    repository, ref = publication['repository'], publication['ref']
    base = f'https://raw.githubusercontent.com/{repository}/{quote(ref, safe="")}/dist/'
    entries = []
    for filename, digest in sorted(manifest['files'].items()):
        path = Path(filename)
        if len(path.parts) != 3 or path.parts[0] not in FILTER_PROFILES or path.parts[1] not in TARGETS or path.stem not in NAMES:
            raise ValueError('Unknown public artifact in template catalog')
        profile = path.parts[0]
        target = TARGETS[path.parts[1]]
        conversion = target in {'clash', 'stash'}
        if path.suffix != ('.ini' if conversion else '.yaml'):
            raise ValueError('Template artifact format does not match its target')
        content = outputs[filename]
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        if conversion:
            rule_lines = [line.strip() for line in content.splitlines() if line.strip().startswith('ruleset=')]
            has_mrs = any('.mrs' in line for line in rule_lines)
            has_geosite = any(re.match(r'ruleset=[^,]+,\[\]GEOSITE,', line) for line in rule_lines)
        else:
            config = yaml.safe_load(content)
            has_mrs = any(provider.get('format') == 'mrs' for provider in config.get('rule-providers', {}).values())
            has_geosite = any(rule.startswith('GEOSITE,') for rule in config.get('rules', []))
        capabilities = (['mrs'] if has_mrs else []) + (['geosite'] if has_geosite else [])
        entries.append({
            'id': f'{profile}/{target}/{path.stem}', 'profile': profile, 'name': NAMES[path.stem], 'variant': path.stem,
            'kind': 'conversion-template' if conversion else 'runtime-template',
            'target': target, 'path': filename, 'url': base + filename,
            'sha256': digest, 'upstreamCommit': manifest['file_upstream_commits'][filename],
            'requiredFlags': ({'expand': False, 'list': False, **({'new_name': True} if target == 'clash' else {})}
                              if conversion else {}),
            'capabilities': capabilities,
        })
    result = {
        'schemaVersion': 2, 'defaultProfile': DEFAULT_PROFILE,
        'profiles': [{'id': key, **value} for key, value in FILTER_PROFILES.items()], 'repository': repository, 'ref': ref,
        'license': 'CC-BY-SA-4.0',
        'source': 'https://github.com/Aethersailor/Custom_OpenClash_Rules',
        'testedWith': {
            'converter': (root / 'config/converter-version.txt').read_text().strip(),
            'mihomo': (root / 'config/mihomo-version.txt').read_text().strip(),
        },
        'templates': entries,
    }
    return json.dumps(result, ensure_ascii=False, indent=2) + '\n'
