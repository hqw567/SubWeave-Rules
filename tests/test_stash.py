"""Stash projections preserve routing intent and reject unsupported user rules."""

from pathlib import Path
import sys
import unittest
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from stash_support import build_stash_ini
from rules import STASH_INI_VARIANTS


PRIMARY = "🚀 手动选择"
AD_GROUP = "🛡️ 广告过滤"
AD_URL = "https://rules.example/pure-ads.yaml"
SETTINGS = {"filter": {"enabled": True, "name": "ads-only", "group": AD_GROUP, "url": AD_URL, "interval": 86400}}
DIRECT = "DOMAIN-SUFFIX,direct.example\nIP-CIDR,192.0.2.0/24,no-resolve\nDST-PORT,7844\nSRC-PORT,41641\n"
SOURCE_BASE = "https://raw.githubusercontent.com/Aethersailor/Custom_OpenClash_Rules/main/rule/"
META_BASE = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/"


def source(*rules):
    return "\n".join([
        "[custom]", *rules, f"ruleset={PRIMARY},[]FINAL",
        f"custom_proxy_group={PRIMARY}`select`[]DIRECT", "enable_rule_generator=true", "",
    ])


class StashProjectionTests(unittest.TestCase):
    def test_geosite_and_business_geoip_become_typed_mrs_with_options(self):
        template = source(
            "ruleset=DIRECT,[]GEOSITE,category-games@cn",
            f"ruleset={PRIMARY},[]GEOSITE,category-ai-!cn",
            "ruleset=DIRECT,[]GEOIP,private,no-resolve",
            f"ruleset={PRIMARY},[]GEOIP,telegram,no-resolve",
            "ruleset=DIRECT,[]GEOIP,cn,no-resolve",
        )
        result = build_stash_ini(template, {}, SETTINGS, PRIMARY, DIRECT)
        self.assertIn(f"ruleset=DIRECT,clash-domain:{META_BASE}geosite/category-games%40cn.mrs,28800", result)
        self.assertIn(f"ruleset={PRIMARY},clash-domain:{META_BASE}geosite/category-ai-%21cn.mrs,28800", result)
        self.assertIn(f"ruleset=DIRECT,clash-ipcidr:{META_BASE}geoip/private.mrs,28800|no-resolve", result)
        self.assertIn(f"ruleset={PRIMARY},clash-ipcidr:{META_BASE}geoip/telegram.mrs,28800|no-resolve", result)
        self.assertIn("ruleset=DIRECT,[]GEOIP,cn,no-resolve", result)
        self.assertNotIn(",[]GEOSITE,", result)

    def test_direct_ip_projection_keeps_destination_port_and_documents_one_exclusion(self):
        template = source(
            f"ruleset=DIRECT,clash-classic:{SOURCE_BASE}Custom_Direct_Classical_IP.yaml,1800",
            f"ruleset=DIRECT,clash-classic:{SOURCE_BASE}Steam_CDN_Classical.yaml,28800",
            f"ruleset=DIRECT,clash-classic:{SOURCE_BASE}Custom_Port_Direct.yaml,28800",
        )
        result = build_stash_ini(template, {}, SETTINGS, PRIMARY, DIRECT)
        self.assertIn(f"clash-ipcidr:{SOURCE_BASE}Custom_Direct_IP.mrs,1800|no-resolve", result)
        self.assertIn("ruleset=DIRECT,[]DST-PORT,7844", result)
        self.assertTrue(any(line.startswith("; Stash:") and "SRC-PORT,41641 omitted" in line for line in result.splitlines()))
        self.assertFalse(any("SRC-PORT" in line for line in result.splitlines() if line.startswith("ruleset=")))
        self.assertIn(f"clash-domain:{SOURCE_BASE}Steam_CDN_Domain.mrs,28800", result)
        self.assertIn(f"clash-ipcidr:{SOURCE_BASE}Steam_CDN_IP.mrs,28800|no-resolve", result)
        self.assertIn(f"clash-classic:{SOURCE_BASE}Custom_Port_Direct.yaml,28800", result)
        self.assertIn(f"ruleset={AD_GROUP},clash-classic:{AD_URL},86400", result)

    def test_user_unsupported_rules_are_rejected_instead_of_omitted(self):
        for rule in (
            "SRC-PORT,41641,@direct", "SRC-IP-CIDR,192.0.2.0/24,@direct",
            "DOMAIN,personal.example,PASS", "AND,((NETWORK,udp),(DST-PORT,443)),@reject",
        ):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                build_stash_ini(source(), {"before_filter": [rule]}, SETTINGS, PRIMARY, DIRECT)

    def test_unknown_upstream_classical_provider_or_direct_rule_requires_mapping(self):
        for template, direct in (
            (source(f"ruleset=DIRECT,clash-classic:{SOURCE_BASE}New_Unknown.yaml,28800"), DIRECT),
            (source(f"ruleset=DIRECT,clash-classic:{SOURCE_BASE}Custom_Direct_Classical_IP.yaml,28800"), DIRECT + "SRC-PORT,5555\n"),
        ):
            with self.subTest(template=template), self.assertRaises(ValueError):
                build_stash_ini(template, {}, SETTINGS, PRIMARY, direct)

    def test_explicit_proxy_entry_precedes_ad_group_and_is_not_duplicated(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                template = source()
                if existing:
                    template += f"custom_proxy_group=Proxy`select`[]{PRIMARY}\n"
                result = build_stash_ini(template, {}, SETTINGS, PRIMARY, DIRECT)
                groups = [line for line in result.splitlines() if line.startswith("custom_proxy_group=")]
                self.assertEqual(sum(line.startswith("custom_proxy_group=Proxy`") for line in groups), 1)
                self.assertEqual(groups[-1], f"custom_proxy_group={AD_GROUP}`select`[]REJECT`[]{PRIMARY}")
                self.assertIn(f"custom_proxy_group=Proxy`select`[]{PRIMARY}", groups[:-1])
                self.assertNotIn("[]PASS", result)

    def test_benchmark_parameters_are_preserved_for_the_converter(self):
        for kind in ("url-test", "fallback"):
            with self.subTest(kind=kind):
                benchmark = f"custom_proxy_group=Bench`{kind}`.*`https://www.gstatic.com/generate_204`300,6,50"
                result = build_stash_ini(source() + benchmark + "\n", {}, SETTINGS, PRIMARY, DIRECT)
                self.assertIn(benchmark, result.splitlines())

    def test_all_vendored_stash_variants_keep_personal_priority_and_portable_groups(self):
        vendor = ROOT / "vendor" / "aethersailor"
        direct = (vendor / "Custom_Direct.list").read_text(encoding="utf-8")
        for slug, stem in STASH_INI_VARIANTS.items():
            with self.subTest(variant=slug):
                with (vendor / f"{stem}.ini").open(encoding="utf-8", newline="") as handle:
                    template = handle.read()
                primary = "🚀 故障转移" if slug.endswith("fallback") else PRIMARY
                personal = {"before_filter": ["DOMAIN,personal.example,@direct"], "after_filter": []}
                result = build_stash_ini(template, personal, SETTINGS, primary, direct)
                rules = [line for line in result.splitlines() if line.startswith("ruleset=")]
                self.assertEqual(rules[0], "ruleset=DIRECT,[]DOMAIN,personal.example")
                self.assertEqual(rules[1], f"ruleset={AD_GROUP},clash-classic:{AD_URL},86400")
                self.assertNotIn(",[]GEOSITE,", result)
                for line in template.splitlines():
                    if ",[]GEOSITE," in line:
                        category = line.rsplit(",", 1)[1]
                        self.assertIn(f"{META_BASE}geosite/{quote(category, safe='')}.mrs", result)
                original_names = [line.split("`", 1)[0] for line in template.splitlines() if line.startswith("custom_proxy_group=")]
                original_groups = {line.split("`", 1)[0]: line.split("`") for line in template.splitlines() if line.startswith("custom_proxy_group=")}
                groups = [line for line in result.splitlines() if line.startswith("custom_proxy_group=")]
                expected_names = original_names + (["custom_proxy_group=Proxy"] if "custom_proxy_group=Proxy" not in original_names else []) + [f"custom_proxy_group={AD_GROUP}"]
                self.assertEqual([line.split("`", 1)[0] for line in groups], expected_names)
                self.assertEqual(groups[-1], f"custom_proxy_group={AD_GROUP}`select`[]REJECT`[]{primary}")
                for line in groups:
                    fields = line.split("`")
                    if fields[1] in {"url-test", "fallback"}:
                        self.assertEqual(fields[-2:], original_groups[fields[0]][-2:])
                    else:
                        self.assertNotIn("https://www.gstatic.com/generate_204", line)
                    self.assertNotIn("(?<", line)
                    self.assertNotIn("(?!", line)


if __name__ == "__main__":
    unittest.main()
