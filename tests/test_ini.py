"""Keep INI selectors portable without moving upstream rules or groups."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ini_support import build_ini


AD_GROUP = "🛡️ 广告过滤"
AD_URL = "https://rules.example/only-ads.yaml"
SETTINGS = {"ads": {
    "enabled": True, "name": "awavenue-ads-only", "group": AD_GROUP,
    "url": AD_URL, "interval": 86400,
}}


class IniCompositionTests(unittest.TestCase):
    def test_ad_selector_is_last_inside_custom_and_rule_priority_is_preserved(self):
        for primary in ("🚀 手动选择", "🚀 故障转移"):
            with self.subTest(primary=primary):
                source = (
                    "; original heading\n"
                    "[custom]\n"
                    "; original rule comment\n"
                    "ruleset=DIRECT,[]DOMAIN,upstream.example\n"
                    f"ruleset={primary},[]FINAL\n"
                    f"custom_proxy_group={primary}`select`[]DIRECT\n"
                    "; comment between groups\n"
                    "custom_proxy_group=Tail`select`[]DIRECT\n"
                    "enable_rule_generator=true\n"
                    "[unrelated]\n"
                    "custom_proxy_group=Outside`select`[]DIRECT\n"
                    "untouched=value"
                )
                personal = {
                    "before_ads": ["DOMAIN,allowed.example,@direct"],
                    "after_ads": ["DOMAIN,proxied.example,@proxy"],
                }
                result = build_ini(source, personal, SETTINGS, primary)
                group_line = f"custom_proxy_group={AD_GROUP}`select`[]REJECT`[]{primary}"
                prefix_rules = [
                    "ruleset=DIRECT,[]DOMAIN,allowed.example",
                    f"ruleset={AD_GROUP},clash-classic:{AD_URL},86400",
                    f"ruleset={primary},[]DOMAIN,proxied.example",
                ]
                custom = result.split("[custom]\n", 1)[1].split("[unrelated]\n", 1)[0]
                groups = [line for line in custom.splitlines() if line.startswith("custom_proxy_group=")]
                self.assertEqual(groups, [
                    f"custom_proxy_group={primary}`select`[]DIRECT",
                    "custom_proxy_group=Tail`select`[]DIRECT",
                    group_line,
                ])
                rules = [line for line in custom.splitlines() if line.startswith("ruleset=")]
                self.assertEqual(rules, prefix_rules + [
                    "ruleset=DIRECT,[]DOMAIN,upstream.example", f"ruleset={primary},[]FINAL",
                ])
                self.assertLess(result.index(group_line), result.index("[unrelated]\n"))
                restored = result.replace("\n".join(prefix_rules) + "\n", "", 1).replace(group_line + "\n", "", 1)
                self.assertEqual(restored, source, "Upstream text may only gain the requested insertions")

    def test_crlf_and_unterminated_last_group_remain_separate_lines(self):
        primary = "🚀 手动选择"
        original_group = f"custom_proxy_group={primary}`select`[]DIRECT"
        source = f"; keep CRLF\r\n[custom]\r\nruleset={primary},[]FINAL\r\n{original_group}"
        result = build_ini(source, {"before_ads": [], "after_ads": []}, SETTINGS, primary)
        ad_group = f"custom_proxy_group={AD_GROUP}`select`[]REJECT`[]{primary}"
        ad_rule = f"ruleset={AD_GROUP},clash-classic:{AD_URL},86400\r\n"
        self.assertIn(original_group + "\r\n" + ad_group, result)
        self.assertNotIn("\n", result.replace("\r\n", ""), "Inserted lines must use the source's CRLF convention")
        restored = result.replace(ad_rule, "", 1)
        suffix = "\r\n" + ad_group
        if restored.endswith(suffix + "\r\n"):
            restored = restored[:-len(suffix + "\r\n")]
        else:
            self.assertTrue(restored.endswith(suffix))
            restored = restored[:-len(suffix)]
        self.assertEqual(restored, source)


if __name__ == "__main__":
    unittest.main()
