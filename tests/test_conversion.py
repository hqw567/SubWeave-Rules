"""Regression checks for the final converter result, never private subscriptions."""
from __future__ import annotations

import copy
import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_conversion as checker


AD = '🛡️ 广告过滤'
PRIMARY = '🚀 手动选择'
AD_URL = 'https://example.org/ads.yaml'
SETTINGS = {'ads': {'enabled': True, 'group': AD, 'url': AD_URL}}
DIRECT_RULES = [f'DOMAIN,service-{number}.example,DIRECT' for number in range(6)]


def template(target='clash'):
    lines = ['[custom]']
    lines += [f'ruleset=DIRECT,[]DOMAIN,service-{number}.example' for number in range(6)]
    lines += [f'ruleset={AD},clash-classic:{AD_URL},86400', f'ruleset={PRIMARY},[]FINAL']
    lines += [f'custom_proxy_group={PRIMARY}`select`.*']
    if target == 'stash':
        lines += [f'custom_proxy_group=Proxy`select`[]{PRIMARY}']
    lines += [f'custom_proxy_group={AD}`select`[]REJECT`[]{PRIMARY}',
              'enable_rule_generator=true', 'overwrite_original_rules=true']
    return '\n'.join(lines) + '\n'


def converted(target='clash'):
    config = {
        'proxies': [{'name': 'HK-fixture', 'type': 'ss', 'server': '192.0.2.1', 'port': 443}],
        'proxy-providers': {'synthetic': {'url': checker.SYNTHETIC_PROVIDER, 'path': './nodes.yaml', 'interval': 3600}},
        'proxy-groups': [{'name': PRIMARY, 'type': 'select', 'proxies': ['HK-fixture'], 'use': ['synthetic']}],
        'rule-providers': {'backend-name': {'url': AD_URL, 'behavior': 'classical', 'format': 'yaml', 'path': './ads.yaml'}},
        'rules': DIRECT_RULES + [f'RULE-SET,backend-name,{AD}', f'MATCH,{PRIMARY}'],
    }
    if target == 'stash':
        config['proxy-groups'].append({'name': 'Proxy', 'type': 'select', 'proxies': [PRIMARY]})
        config['dns'] = {'nameserver': ['https://223.5.5.5/dns-query'], 'follow-rule': False}
    config['proxy-groups'].append({'name': AD, 'type': 'select', 'proxies': ['REJECT', PRIMARY]})
    return config


class ConversionContractTests(unittest.TestCase):
    def test_both_target_contracts_accept_correct_final_outputs(self):
        for target in ('clash', 'stash'):
            with self.subTest(target=target):
                checker.validate_converted(converted(target), template(target), target, SETTINGS)

    def test_all_six_direct_exceptions_must_precede_ads(self):
        for change in ('drop', 'reorder'):
            config = converted()
            if change == 'drop':
                config['rules'].pop(2)
            else:
                config['rules'][0], config['rules'][6] = config['rules'][6], config['rules'][0]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'rule sequence'):
                checker.validate_converted(config, template(), 'clash', SETTINGS)

    def test_provider_identity_is_by_source_not_backend_generated_name(self):
        config = converted()
        config['rule-providers']['new-generated-name'] = config['rule-providers'].pop('backend-name')
        config['rules'][6] = f'RULE-SET,new-generated-name,{AD}'
        checker.validate_converted(config, template(), 'clash', SETTINGS)
        config['rule-providers']['new-generated-name']['format'] = 'text'
        with self.assertRaisesRegex(ValueError, 'provider formats'):
            checker.validate_converted(config, template(), 'clash', SETTINGS)

    def test_post_conversion_group_order_and_no_pass_are_enforced(self):
        config = converted('stash')
        config['proxy-groups'][-1], config['proxy-groups'][-2] = config['proxy-groups'][-2], config['proxy-groups'][-1]
        with self.assertRaisesRegex(ValueError, 'group order'):
            checker.validate_converted(config, template('stash'), 'stash', SETTINGS)
        config = converted()
        config['proxy-groups'][-1]['proxies'] = ['REJECT', 'PASS']
        with self.assertRaisesRegex(ValueError, 'Advertising selector'):
            checker.validate_converted(config, template(), 'clash', SETTINGS)

    def test_shared_clash_fields_are_not_silently_projected_to_a_different_dialect(self):
        config = converted()
        config['proxy-providers']['synthetic']['health-check'] = {'enable': True}
        config['proxy-groups'][0]['url'] = 'https://example.com/probe'
        checker.validate_converted(config, template(), 'clash', SETTINGS)

    def test_shared_geosite_and_service_geoip_rules_are_preserved(self):
        for rule in ['GEOSITE,gfw,' + PRIMARY, 'GEOIP,telegram,' + PRIMARY]:
            source = template().replace(f'ruleset={PRIMARY},[]FINAL', f'ruleset={PRIMARY},[]{rule.rsplit(",", 1)[0]}\nruleset={PRIMARY},[]FINAL')
            config = converted()
            config['rules'].insert(-1, rule)
            with self.subTest(rule=rule):
                checker.validate_converted(config, source, 'clash', SETTINGS)

    def test_stash_target_must_use_its_expected_base_without_field_blacklisting(self):
        config = converted('stash')
        config['proxy-groups'][0]['tolerance'] = 50
        checker.validate_converted(config, template('stash'), 'stash', SETTINGS)
        config.pop('dns')
        with self.assertRaisesRegex(ValueError, 'native DNS base'):
            checker.validate_converted(config, template('stash'), 'stash', SETTINGS)

    def test_projected_resources_are_deduplicated_and_parsed_without_node_sources(self):
        captured = []
        def inspect_native(binary, home, path, label):
            captured.append(yaml.safe_load(path.read_text()))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(checker.PublicResources, 'payload', return_value=['DOMAIN,ads.example']) as load:
                with patch.object(checker, 'run_native', side_effect=inspect_native):
                    count = checker.validate_resources(root, [converted('stash'), converted('stash')], Path('/core'))
            self.assertEqual(count, 1)
            load.assert_called_once()
            self.assertNotIn('proxy-providers', captured[0])
            self.assertNotIn('proxies', captured[0])
            self.assertEqual(captured[0]['rules'], ['RULE-SET,resource-1,DIRECT', 'MATCH,DIRECT'])
            self.assertEqual(captured[0]['rule-providers']['resource-1']['payload'], ['DOMAIN,ads.example'])

    def test_missing_projected_resource_blocks_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(checker.PublicResources, 'payload', side_effect=ValueError('private-source-value')):
                with patch.object(checker, 'run_native') as native:
                    with self.assertRaisesRegex(ValueError, 'could not be downloaded') as error:
                        checker.validate_resources(Path(temporary), [converted('stash')], Path('/core'))
                    self.assertNotIn('private-source-value', str(error.exception))
                    native.assert_not_called()

    def test_candidate_cannot_load_private_subscriptions_or_executable_features(self):
        for extra in ['insert_url=https://private.example/sub?token=synthetic-secret',
                      'custom_proxy_group=Unsafe`select`script:/private/script.js',
                      'ruleset=DIRECT,clash-classic:https://example.org/rules.yaml?token=synthetic-secret']:
            with self.subTest(extra=extra), self.assertRaises(ValueError) as raised:
                checker.parse_template(template() + extra + '\n')
            self.assertNotIn('synthetic-secret', str(raised.exception))

    def test_unreviewed_archive_is_rejected_before_unpack_or_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'config').mkdir()
            (root / 'config/converter-version.txt').write_text(checker.PIN)
            with patch.object(checker.platform, 'system', return_value='Linux'), patch.object(checker.platform, 'machine', return_value='x86_64'):
                with patch.object(checker, 'fetch_public', return_value=b'wrong archive'):
                    with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                        checker.locate_archive(root, download=True)

    def test_archive_paths_cannot_escape_temporary_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'bad.tar.gz'
            with tarfile.open(archive, 'w:gz') as bundle:
                entry = tarfile.TarInfo('../escaped')
                entry.size = 1
                bundle.addfile(entry, io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError, 'Unsafe path'):
                checker.unpack_archive(archive, root / 'extract')
            self.assertFalse((root / 'escaped').exists())


if __name__ == '__main__':
    unittest.main()
