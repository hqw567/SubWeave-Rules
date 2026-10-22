"""Native validation boundary tests; optional real-core regression tests.

Set MIHOMO_TEST_BINARY to the pinned core to run the real -t cases. The regular
test suite does not download binaries/data or start listeners.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import check_mihomo as checker


def minimal_config() -> dict:
    return {
        'proxy-providers': {'provider1': {'type': 'http', 'url': checker.PLACEHOLDER, 'path': './providers/nodes.yaml',
                                         'filter': 'HK|US', 'override': {'udp': True}}},
        'proxy-groups': [{'name': 'Proxy', 'type': 'select', 'use': ['provider1']}],
        'rules': ['DOMAIN,example.com,Proxy', 'MATCH,DIRECT'],
    }


class NativeBoundaryTests(unittest.TestCase):
    def test_fixtures_preserve_original_and_group_routing(self):
        source = minimal_config()
        snapshot = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            prepared = checker.fixture_config(source, home)
            self.assertEqual(source, snapshot)
            self.assertEqual(prepared['rules'], source['rules'])
            self.assertEqual(prepared['proxy-groups'], source['proxy-groups'])
            provider = prepared['proxy-providers']['provider1']
            self.assertEqual(provider['type'], 'file')
            self.assertNotIn('url', provider)
            self.assertEqual(provider['filter'], 'HK|US')
            self.assertEqual(provider['override'], {'udp': True})
            self.assertEqual(prepared['geodata-mode'], True)
            nodes = yaml.safe_load((home / provider['path']).read_text())['proxies']
            self.assertTrue(nodes)
            self.assertTrue(all(node['server'] == '127.0.0.1' for node in nodes))

    def test_private_subscription_is_refused_without_echo(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'public.yaml'
            config = minimal_config()
            config['proxy-providers']['provider1']['url'] = 'https://private.example/?token=synthetic-secret'
            path.write_text('# PUBLIC TEMPLATE: test\n' + yaml.safe_dump(config), encoding='utf-8')
            with self.assertRaises(ValueError) as raised:
                checker.public_config(path)
            self.assertNotIn('synthetic-secret', str(raised.exception))
            path.write_text('# PRIVATE: do not publish\n' + yaml.safe_dump(config), encoding='utf-8')
            with self.assertRaises(ValueError):
                checker.public_config(path)

    def test_only_test_mode_runs_and_environment_overrides_are_removed(self):
        completed = subprocess.CompletedProcess([], 0, 'configuration test is successful', '')
        with patch.dict(os.environ, {'CLASH_CONFIG_STRING': 'synthetic-secret', 'CLASH_POST_UP': 'false'}):
            with patch.object(checker.subprocess, 'run', return_value=completed) as run:
                checker.run_native(Path('/pinned/mihomo'), Path('/temporary'), Path('/temporary/config.yaml'))
        args, kwargs = run.call_args
        self.assertIn('-t', args[0])
        self.assertEqual(kwargs['timeout'], 120)
        self.assertNotIn('CLASH_CONFIG_STRING', kwargs['env'])
        self.assertNotIn('CLASH_POST_UP', kwargs['env'])

    def test_native_timeout_and_provider_warnings_block_publication(self):
        with patch.object(checker.subprocess, 'run', side_effect=subprocess.TimeoutExpired('mihomo', 1)):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                checker.run_native(Path('/core'), Path('/tmp'), Path('/tmp/config.yaml'))
        warning = subprocess.CompletedProcess([], 0, 'level=warning msg="parse classical rule [private-value] error"', '')
        with patch.object(checker.subprocess, 'run', return_value=warning):
            with self.assertRaisesRegex(ValueError, 'invalid rule-provider payload') as raised:
                checker.run_native(Path('/core'), Path('/tmp'), Path('/tmp/config.yaml'))
            self.assertNotIn('private-value', str(raised.exception))

    def test_unverified_archive_never_executes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'config').mkdir()
            (root / 'config/mihomo-version.txt').write_text(checker.PIN)
            with patch.object(checker.platform, 'system', return_value='Linux'), patch.object(checker.platform, 'machine', return_value='x86_64'):
                with patch.object(checker, 'fetch_public', return_value=b'not-the-reviewed-release'), patch.object(checker.subprocess, 'run') as run:
                    with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                        checker.locate_binary(root, download=True)
                    run.assert_not_called()

    def test_http_rule_payload_is_really_loaded_and_shared(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = checker.PublicResources(Path('/core'), Path(temporary))
            source = {'type': 'http', 'behavior': 'classical', 'format': 'yaml', 'url': 'https://example.org/rules.yaml'}
            with patch.object(checker, 'fetch_public', return_value=b'payload:\n  - DOMAIN,ads.example\n') as fetch:
                self.assertEqual(resources.payload(source), ['DOMAIN,ads.example'])
                self.assertEqual(resources.payload(source), ['DOMAIN,ads.example'])
                fetch.assert_called_once()

    def test_empty_public_provider_is_downloaded_and_injected(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            resources = checker.PublicResources(Path('/core'), home)
            provider = {'type': 'http', 'behavior': 'classical', 'format': 'yaml', 'url': 'https://example.org/empty.yaml'}
            config = {'geodata-mode': True, 'rule-providers': {'reserved': provider}, 'rules': ['MATCH,DIRECT']}
            with patch.object(checker, 'fetch_public', return_value=b'payload: []\n'):
                resources.prepare(config)
            self.assertEqual(provider['payload'], [])
            self.assertEqual(provider['type'], 'http')

    def test_native_decoded_empty_mrs_is_accepted_but_corrupt_mrs_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            resources = checker.PublicResources(Path('/core'), Path(temporary))
            provider = {'type': 'http', 'behavior': 'domain', 'format': 'mrs', 'url': 'https://example.org/empty.mrs'}
            empty = subprocess.CompletedProcess([], 2, b'', b'panic: empty rule\n\n')
            with patch.object(checker, 'fetch_public', return_value=b'public-mrs'), patch.object(checker.subprocess, 'run', return_value=empty):
                self.assertEqual(resources.payload(provider), [])
            resources.payloads.clear()
            corrupt = subprocess.CompletedProcess([], 2, b'', b'panic: invalid format\n')
            with patch.object(checker.subprocess, 'run', return_value=corrupt):
                with self.assertRaisesRegex(ValueError, 'MRS validation rejected'):
                    resources.payload(provider)


@unittest.skipUnless(os.environ.get('MIHOMO_TEST_BINARY'), 'Set MIHOMO_TEST_BINARY to run the pinned real-core checks')
class RealMihomoTests(unittest.TestCase):
    def run_config(self, config):
        binary = Path(os.environ['MIHOMO_TEST_BINARY']).resolve()
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            prepared = checker.fixture_config(config, home)
            path = home / 'config.yaml'
            path.write_text(yaml.safe_dump(prepared, allow_unicode=True), encoding='utf-8')
            checker.run_native(binary, home, path, 'native regression', timeout=30)

    def test_valid_fixture_passes_actual_core(self):
        self.run_config(minimal_config())

    def test_empty_rule_provider_passes_actual_core(self):
        config = minimal_config()
        config['rule-providers'] = {'reserved': {'type': 'inline', 'behavior': 'classical', 'payload': []}}
        config['rules'].insert(0, 'RULE-SET,reserved,DIRECT')
        self.run_config(config)

    def test_invalid_cidr_and_regex_fail_actual_core(self):
        for invalid in ['IP-CIDR,999.0.0.1/99,DIRECT', 'DOMAIN-REGEX,[,DIRECT']:
            with self.subTest(rule=invalid):
                config = minimal_config()
                config['rules'].insert(0, invalid)
                with self.assertRaises(ValueError):
                    self.run_config(config)

    def test_invalid_provider_payload_fails_even_when_core_only_warns(self):
        config = minimal_config()
        config['rule-providers'] = {'broken': {'type': 'inline', 'behavior': 'classical', 'payload': ['IP-CIDR,999.0.0.1/99']}}
        config['rules'].insert(0, 'RULE-SET,broken,DIRECT')
        with self.assertRaisesRegex(ValueError, 'invalid rule-provider payload'):
            self.run_config(config)


if __name__ == '__main__':
    unittest.main()
