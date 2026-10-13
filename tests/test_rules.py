"""Behavioral checks for generation, routing precedence, and secret boundaries."""

from __future__ import annotations

import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("personal_rules_generator", ROOT / "scripts/rules.py")
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def upstream_fixture() -> dict:
    return {
        "proxy-providers": {
            "provider1": {
                "type": "http",
                "url": "url",
                "path": "./proxy_provider/provider1.yaml",
                "interval": 3600,
                "proxy": "DIRECT",
                "header": None,
                "health-check": {"enable": True, "url": "https://www.gstatic.com/generate_204", "interval": 300},
            }
        },
        "proxy-groups": [
            {"name": "🚀 手动选择", "type": "select", "proxies": ["DIRECT"], "use": ["provider1"]}
        ],
        "rule-providers": {
            "upstream-cdn": {
                "type": "http",
                "behavior": "classical",
                "format": "yaml",
                "url": "https://example.org/public-rules.yaml",
                "path": "./ruleset/upstream.yaml",
                "interval": 86400,
            }
        },
        "rules": [
            "RULE-SET,upstream-cdn,DIRECT",
            "DOMAIN-SUFFIX,upstream.example,DIRECT",
            "MATCH,🚀 手动选择",
        ],
    }


def settings_fixture() -> dict:
    return {
        "ads": {
            "enabled": True,
            "name": "awavenue-ads-only",
            "url": "https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/main/Filters/AWAvenue-Ads-Rule-Clash-Classical-Only.Ads.yaml",
            "interval": 86400,
            "group": "🛡️ 广告过滤",
        }
    }


class CompositionTests(unittest.TestCase):
    def test_personal_rules_have_precedence_without_losing_upstream(self):
        upstream = upstream_fixture()
        snapshot = copy.deepcopy(upstream)
        before = "DOMAIN,allowed.example,DIRECT"
        after = "IP-CIDR,192.0.2.0/24,🚀 手动选择,no-resolve"
        result = generator.build_config(
            upstream,
            {"before_ads": [before], "after_ads": [after]},
            settings_fixture(),
        )
        generator.validate_config(result)

        advertisement = "RULE-SET,awavenue-ads-only,🛡️ 广告过滤"
        rules = result["rules"]
        self.assertLess(rules.index(before), rules.index(advertisement))
        self.assertLess(rules.index(advertisement), rules.index(after))
        self.assertLess(rules.index(after), rules.index(snapshot["rules"][0]))
        self.assertEqual(rules[-len(snapshot["rules"]):], snapshot["rules"])
        self.assertEqual(upstream, snapshot, "Generating one variant must not mutate its input")

        for group in snapshot["proxy-groups"]:
            self.assertIn(group, result["proxy-groups"])
        self.assertEqual(result["rule-providers"]["upstream-cdn"], snapshot["rule-providers"]["upstream-cdn"])
        expected_metadata = {key: value for key, value in snapshot["proxy-providers"]["provider1"].items() if key not in {"url", "header"}}
        actual_metadata = {key: value for key, value in result["proxy-providers"]["provider1"].items() if key not in {"url", "header"}}
        self.assertEqual(actual_metadata, expected_metadata)
        self.assertEqual(result["rule-providers"]["awavenue-ads-only"]["behavior"], "classical")
        self.assertEqual(result["rule-providers"]["awavenue-ads-only"]["format"], "yaml")

    def test_disabling_ads_keeps_personal_rules_and_upstream(self):
        upstream = upstream_fixture()
        settings = settings_fixture()
        settings["ads"]["enabled"] = False
        personal = {"before_ads": ["DOMAIN,allowed.example,DIRECT"], "after_ads": ["DOMAIN,other.example,DIRECT"]}
        result = generator.build_config(upstream, personal, settings)
        self.assertEqual(result["rules"], personal["before_ads"] + personal["after_ads"] + upstream["rules"])
        self.assertNotIn("awavenue-ads-only", result.get("rule-providers", {}))
        self.assertFalse(any(group["name"] == settings["ads"]["group"] for group in result["proxy-groups"]))

    def test_unknown_policy_and_rule_provider_are_rejected(self):
        for rule in ("DOMAIN,example.com,missing-policy", "RULE-SET,missing-provider,DIRECT"):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                config = generator.build_config(upstream_fixture(), {"before_ads": [rule], "after_ads": []}, settings_fixture())
                generator.validate_config(config)

    def test_proxy_alias_follows_the_variant_in_rules_and_runtime(self):
        for policy in ("🚀 手动选择", "🚀 故障转移"):
            with self.subTest(policy=policy):
                upstream = upstream_fixture()
                upstream["proxy-groups"][0]["name"] = policy
                upstream["rules"][-1] = f"MATCH,{policy}"
                runtime = {"dns": {"nameserver-policy": {"example.com": ["https://dns.example/dns-query#@proxy"]}}}
                result = generator.build_config(
                    upstream,
                    {"before_ads": ["DOMAIN,proxy.example,@proxy"], "after_ads": []},
                    settings_fixture(),
                    runtime,
                )
                self.assertIn(f"DOMAIN,proxy.example,{policy}", result["rules"])
                self.assertEqual(result["dns"]["nameserver-policy"]["example.com"], [f"https://dns.example/dns-query#{policy}"])


class InputSafetyTests(unittest.TestCase):
    def test_nested_duplicate_yaml_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.yaml"
            path.write_text("ads:\n  enabled: true\n  enabled: false\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                generator.load_yaml(path)

    def test_public_urls_reject_credentials_without_echoing_secrets(self):
        marker = "synthetic-private-value"
        forbidden = [
            f"https://user:{marker}@example.org/rules.yaml",
            f"https://example.org/rules.yaml?token={marker}",
            f"https://example.org/rules.yaml?arbitrary={marker}",
            f"https://example.org/rules.yaml#{marker}",
            f"file:///tmp/{marker}",
        ]
        for url in forbidden:
            with self.subTest(url=url):
                with self.assertRaises(ValueError) as raised:
                    generator.validate_public_url(url)
                self.assertNotIn(marker, str(raised.exception))
        generator.validate_public_url(settings_fixture()["ads"]["url"])


class ProjectOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        for directory in ("config", "rules", "templates", "vendor"):
            shutil.copytree(ROOT / directory, self.root / directory)
        (self.root / ".local").mkdir()
        self.secret_url = "https://subscription.example/subscribe?token=synthetic-render-secret"
        self.secrets = self.root / ".local" / "secrets.yaml"
        self.secrets.write_text(yaml.safe_dump({"subscription_url": self.secret_url}), encoding="utf-8")

    def test_all_yaml_outputs_preserve_their_vendored_variant(self):
        sources = {
            slug: generator.load_yaml(self.root / "vendor" / "aethersailor" / f"{stem}.yaml")
            for slug, stem in generator.VARIANTS.items()
        }
        counts = {slug: 0 for slug in sources}
        for filename, text in generator.prepare_outputs(self.root).items():
            if not filename.endswith(".yaml"):
                continue
            with self.subTest(filename=filename):
                config = yaml.safe_load(text)
                slug = Path(filename).stem
                original = sources[slug]
                counts[slug] += 1
                self.assertEqual(config["rules"][-len(original["rules"]):], original["rules"])
                for group in original["proxy-groups"]:
                    self.assertIn(group, config["proxy-groups"])
                for name, provider in original.get("rule-providers", {}).items():
                    self.assertEqual(config["rule-providers"][name], provider)
        self.assertEqual(set(counts.values()), {2})

    def test_private_render_does_not_modify_public_outputs(self):
        public = generator.prepare_outputs(self.root)
        self.assertEqual(sum(name.endswith(".yaml") for name in public), len(generator.VARIANTS) * 2)
        dist = self.root / "dist"
        dist.mkdir()
        for filename, content in public.items():
            path = dist / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.assertNotIn(self.secret_url, content)
            self.assertNotIn("synthetic-render-secret", content)
        previous = {path.relative_to(dist): path.read_bytes() for path in dist.rglob("*") if path.is_file()}

        output = self.root / ".local" / "rendered"
        private_paths = generator.render_private(self.root, self.secrets, output)
        regular_variants = {slug for slug in generator.VARIANTS if not slug.startswith("selfhosted-")}
        self.assertEqual(len(private_paths), len(regular_variants) * 2)
        for path in private_paths:
            self.assertTrue(path.resolve().is_relative_to(output.resolve()))
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(content["proxy-providers"]["provider1"]["url"], self.secret_url)
        current = {path.relative_to(dist): path.read_bytes() for path in dist.rglob("*") if path.is_file()}
        self.assertEqual(current, previous)
        self.assertEqual(generator.prepare_outputs(self.root), public)

    def test_public_build_rejects_tokenized_rule_url(self):
        path = self.root / "config" / "settings.yaml"
        settings = generator.load_yaml(path)
        settings["ads"]["url"] += "?token=synthetic-public-leak"
        path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            generator.prepare_outputs(self.root)
        self.assertNotIn("synthetic-public-leak", str(raised.exception))

    def test_undocumented_ini_url_cannot_bypass_public_url_validation(self):
        path = self.root / "config" / "settings.yaml"
        settings = generator.load_yaml(path)
        settings["ads"]["ini_url"] = "https://rules.example/private?token=synthetic-ini-secret"
        path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
        with self.assertRaises(ValueError) as raised:
            generator.prepare_outputs(self.root)
        self.assertNotIn("synthetic-ini-secret", str(raised.exception))

    def test_private_output_outside_local_is_rejected_before_writing(self):
        destinations = [self.root / "dist", self.root / "config", self.root.parent / "outside"]
        for output in destinations:
            with self.subTest(output=output), self.assertRaises(ValueError):
                generator.render_private(self.root, self.secrets, output)
        self.assertFalse((self.root / "dist").exists())
        self.assertFalse((self.root.parent / "outside").exists())
        self.assertFalse(any("synthetic-render-secret" in path.read_text(encoding="utf-8") for path in (self.root / "config").rglob("*.yaml")))

    def test_symlink_cannot_redirect_private_output_into_dist(self):
        dist = self.root / "dist"
        dist.mkdir()
        alias = self.root / ".local" / "rendered-link"
        try:
            alias.symlink_to(dist, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("This filesystem does not permit directory symlinks")
        with self.assertRaises(ValueError):
            generator.render_private(self.root, self.secrets, alias)
        self.assertEqual(list(dist.iterdir()), [])

    def test_failed_sync_preserves_sources_outputs_and_personal_rules(self):
        with redirect_stdout(io.StringIO()):
            generator.build(self.root)

        def snapshot():
            return {
                path.relative_to(self.root): path.read_bytes()
                for directory in ("vendor", "dist", "rules", "config", "templates")
                for path in (self.root / directory).rglob("*")
                if path.is_file()
            }

        previous = snapshot()

        def partial_download(url):
            if url.endswith("/" + generator.UPSTREAM_FILES["LICENSE"]):
                raise ValueError("Simulated interrupted upstream download")
            return b"Downloaded partial replacement; must never reach vendor or dist\n"

        with patch.object(generator, "_fetch", side_effect=partial_download) as fetch:
            with self.assertRaisesRegex(ValueError, "Simulated interrupted"):
                generator.sync(self.root, "a" * 40)
            self.assertGreater(fetch.call_count, 1)
        self.assertEqual(snapshot(), previous)
        self.assertEqual(list(self.root.glob(".sync-*")), [])

    def test_sync_resolves_main_through_git_when_api_is_unavailable(self):
        commit = "b" * 40
        vendor = self.root / "vendor" / "aethersailor"
        blobs = {name: (vendor / name).read_bytes() for name in generator.UPSTREAM_FILES}
        downloads = {
            f"https://raw.githubusercontent.com/{generator.REPOSITORY}/{commit}/{remote}": blobs[name]
            for name, remote in generator.UPSTREAM_FILES.items()
        }
        personal_path = self.root / "rules" / "custom.yaml"
        personal = generator.load_yaml(personal_path)
        personal["before_ads"] = ["DOMAIN,preserved.example,DIRECT"]
        personal_path.write_text(yaml.safe_dump(personal, allow_unicode=True), encoding="utf-8")
        previous_personal = personal_path.read_bytes()

        def fetch_resource(url):
            if url.startswith("https://api.github.com/"):
                raise ValueError("Simulated GitHub API rate limit")
            return downloads[url]

        result = SimpleNamespace(stdout=f"{commit}\trefs/heads/main\n")
        with patch.object(generator, "_fetch", side_effect=fetch_resource) as fetch:
            with patch.object(generator.subprocess, "run", return_value=result) as git:
                with redirect_stdout(io.StringIO()):
                    generator.sync(self.root, "main")
        git.assert_called_once()
        self.assertEqual(git.call_args.args[0][-1], "refs/heads/main")
        self.assertEqual({call.args[0] for call in fetch.call_args_list if "raw.githubusercontent.com" in call.args[0]}, set(downloads))
        self.assertEqual(personal_path.read_bytes(), previous_personal)
        metadata = json.loads((vendor / "upstream.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["commit"], commit)
        for name, original in blobs.items():
            self.assertEqual((vendor / name).read_bytes(), original)
        manifest = json.loads((self.root / "dist" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["upstream_commit"], commit)
        self.assertEqual(len(manifest["files"]), len(generator.VARIANTS) * 2 + len(generator.INI_VARIANTS))
        with redirect_stdout(io.StringIO()):
            generator.check(self.root)


if __name__ == "__main__":
    unittest.main()
