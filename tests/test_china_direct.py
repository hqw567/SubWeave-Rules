"""Mainland routing must work without per-site direct exceptions."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from china_direct import CHINA_RULES, DIRECT_GROUP, china_fallback_ini, china_fallback_rules


class ChinaDirectTests(unittest.TestCase):
    def test_cn_precedes_match_without_overriding_private_or_service_rules(self):
        private = [f"GEOSITE,private,{DIRECT_GROUP}", f"GEOIP,private,{DIRECT_GROUP},no-resolve"]
        proxy = ["DOMAIN-SUFFIX,service.example,Proxy", "GEOSITE,gfw,Proxy", "MATCH,Proxy"]
        original = private + proxy[:-1] + [
            "GEOSITE,CN,Old", "GEOIP,cn,Old,no-resolve", f"GEOSITE,cn,{DIRECT_GROUP}",
        ] + proxy[-1:]
        snapshot = list(original)
        result = china_fallback_rules(original)
        self.assertEqual(result, private + proxy[:-1] + CHINA_RULES + proxy[-1:])
        self.assertEqual(original, snapshot)
        self.assertEqual(china_fallback_rules(result), result)

    def test_gfw_and_direct_fallback_templates_gain_real_country_checks(self):
        for original in (["GEOSITE,gfw,Proxy", f"MATCH,{DIRECT_GROUP}"], [f"MATCH,{DIRECT_GROUP}"]):
            with self.subTest(original=original):
                self.assertEqual(china_fallback_rules(original), original[:-1] + CHINA_RULES + original[-1:])

    def test_ini_only_changes_country_rules_inside_custom_and_preserves_crlf(self):
        original = "\r\n".join([
            "[other]", "ruleset=Other,[]GEOIP,cn,no-resolve", "[custom]",
            f"ruleset={DIRECT_GROUP},[]GEOSITE,private",
            f"ruleset={DIRECT_GROUP},[]GEOIP,private,no-resolve",
            "ruleset=Proxy,[]DOMAIN-SUFFIX,service.example",
            f"ruleset={DIRECT_GROUP},[]GEOSITE,cn",
            f"ruleset={DIRECT_GROUP},[]GEOIP,cn,no-resolve",
            "ruleset=Proxy,[]FINAL",
            f"custom_proxy_group={DIRECT_GROUP}`select`[]DIRECT",
            "custom_proxy_group=Proxy`select`[]DIRECT", "untouched=value",
        ])
        result = china_fallback_ini(original)
        self.assertTrue(result.startswith("[other]\r\nruleset=Other,[]GEOIP,cn,no-resolve\r\n[custom]"))
        self.assertIn(f"ruleset=Proxy,[]DOMAIN-SUFFIX,service.example\r\nruleset={DIRECT_GROUP},[]GEOSITE,cn\r\n"
                      f"ruleset={DIRECT_GROUP},[]GEOIP,cn\r\nruleset=Proxy,[]FINAL", result)
        self.assertNotIn(f"ruleset={DIRECT_GROUP},[]GEOIP,cn,no-resolve", result)
        self.assertNotIn("\n", result.replace("\r\n", ""))
        self.assertTrue(result.endswith("untouched=value"))
        self.assertEqual(china_fallback_ini(result), result)


if __name__ == "__main__":
    unittest.main()
