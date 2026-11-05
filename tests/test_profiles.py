"""Profile boundaries: custom-only never adds AWAvenue, each scheme selects one source."""
from pathlib import Path
import sys
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import rules
from filter_profiles import FILTER_PROFILES, DEFAULT_PROFILE, profile_settings

class FilterProfileTests(unittest.TestCase):
    def test_all_schemes_generate_the_complete_matrix_without_cross_profile_rules(self):
        outputs = rules.prepare_outputs(ROOT)
        self.assertEqual(len(outputs), 180)
        settings = rules.load_yaml(ROOT / 'config/settings.yaml')['filter']
        self.assertEqual(DEFAULT_PROFILE, 'ads-only')
        for path, text in outputs.items():
            profile = path.split('/')[0]
            rule_url = FILTER_PROFILES[profile]['ruleUrl']
            with self.subTest(path=path):
                if profile == 'custom-only':
                    self.assertNotIn('AWAvenue-Ads-Rule', text)
                    self.assertNotIn(settings['name'], text)
                    self.assertNotIn(settings['group'], text)
                else:
                    self.assertIn(rule_url, text)
                    for other in FILTER_PROFILES.values():
                        if other['ruleUrl'] and other['ruleUrl'] != rule_url:
                            self.assertNotIn(other['ruleUrl'], text)
                if path.endswith('.yaml'):
                    config = yaml.safe_load(text)
                    self.assertEqual(config['rules'][0], 'DOMAIN-SUFFIX,neolive.kr,DIRECT')
                    if rule_url:
                        self.assertEqual(config['proxy-groups'][-1]['name'], settings['group'])
                        self.assertEqual(config['rule-providers'][settings['name'] + '-' + profile]['url'], rule_url)
                else:
                    routing = [line for line in text.splitlines() if line.startswith('ruleset=')]
                    self.assertEqual(routing[0], 'ruleset=DIRECT,[]DOMAIN-SUFFIX,neolive.kr')
                if path.endswith('.yaml'):
                    routing = config['rules']
                    domain_rule = 'GEOSITE,cn,🎯 全球直连'
                    ip_rule = 'GEOIP,cn,🎯 全球直连'
                else:
                    domain_rule = ('ruleset=🎯 全球直连,clash-domain:https://raw.githubusercontent.com/'
                                   'MetaCubeX/meta-rules-dat/meta/geo/geosite/cn.mrs,28800'
                                   if '/subconverter-stash/' in path else 'ruleset=🎯 全球直连,[]GEOSITE,cn')
                    ip_rule = 'ruleset=🎯 全球直连,[]GEOIP,cn'
                self.assertEqual(routing.count(domain_rule), 1)
                self.assertEqual(routing.count(ip_rule), 1)
                self.assertLess(routing.index(domain_rule), routing.index(ip_rule))
                for host in ('qlxft.ourduda.com', 'www.wellcee.com', 'bilalipay.com'):
                    self.assertFalse(any(host in rule for rule in routing), 'Domestic sites must not depend on individual whitelist rules')
                self.assertEqual(routing[-3:-1], [domain_rule, ip_rule], 'Other routing rules must retain priority over the CN fallback')

    def test_category_mapping_matches_the_official_four_subscriptions(self):
        self.assertEqual(FILTER_PROFILES['ads-only']['categories'], ['ads'])
        self.assertTrue(FILTER_PROFILES['ads-unwanted']['ruleUrl'].endswith('-No.Privacy.yaml'))
        self.assertTrue(FILTER_PROFILES['ads-privacy']['ruleUrl'].endswith('-No.Unwelcome.yaml'))
        self.assertEqual(set(FILTER_PROFILES['full-protection']['categories']), {'ads','privacy','unwanted'})
        settings = rules.load_yaml(ROOT / 'config/settings.yaml')
        self.assertFalse(profile_settings(settings, 'custom-only')['filter']['enabled'])
        self.assertTrue(profile_settings(settings, 'ads-only')['filter']['enabled'])
        with self.assertRaises(ValueError):
            profile_settings({'ads': {'enabled': True}}, 'ads-only')
        with self.assertRaises(ValueError):
            rules.prepare_outputs(ROOT, profiles=['removed-profile'])
