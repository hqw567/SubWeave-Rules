"""Project maintained INI policy for the pinned converter's Stash target.

Compatibility mappings follow Aethersailor's documented Stash generator; the
upstream generator is never imported or executed. Original templates remain
the policy source, and unsupported personal rules fail rather than disappear.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

from ini_support import build_ini


_META = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo"
_BENCHMARK = "https://www.gstatic.com/generate_204"
_BUILTINS = {"DIRECT", "REJECT", "REJECT-DROP"}
_BUSINESS_GEOIP = {"private", "telegram", "twitter", "facebook", "google", "netflix"}
_INLINE = {
    "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD", "DOMAIN-REGEX",
    "GEOSITE", "GEOIP", "IP-CIDR", "IP-CIDR6", "IP-ASN", "PROCESS-NAME",
    "PROCESS-PATH", "NETWORK", "DST-PORT",
}
_DIRECT_DATA = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX", "IP-CIDR", "IP-CIDR6"}
_IP_FILES = {
    "Custom_Direct_Classical_IP.yaml": "Custom_Direct_IP.mrs",
    "Custom_Proxy_Classical_IP.yaml": "Custom_Proxy_IP.mrs",
    "Steam_CDN_Classical_IP.yaml": "Steam_CDN_IP.mrs",
    "Game_Download_CDN_Classical_IP.yaml": "Game_Download_CDN_IP.mrs",
}


def _personal_supported(personal: dict) -> None:
    for key in ("before_ads", "after_ads"):
        for rule in personal.get(key, []):
            if not isinstance(rule, str):
                raise ValueError("Stash personal rules must be strings")
            parts = [part.strip() for part in rule.split(",")]
            target_index = -2 if parts[-1] == "no-resolve" else -1
            if parts[0].upper() not in _INLINE or parts[target_index] in {"PASS", "PASS-RULE", "COMPATIBLE"}:
                raise ValueError("Personal rule is unsupported by the Stash template; keep it in a compatible format section")


def _direct_ports(text: str) -> tuple[list[str], bool]:
    ports, omitted = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        kind = line.split(",", 1)[0]
        if kind in _DIRECT_DATA:
            continue
        if line == "SRC-PORT,41641":
            omitted = True
        elif kind == "DST-PORT" and re.fullmatch(r"DST-PORT,\d+(?:-\d+)?", line):
            ports.append(line)
        else:
            raise ValueError("Pinned Custom_Direct.list contains an unmapped Stash rule")
    return ports, omitted


def _renamed_url(url: str, filename: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or "/" not in parts.path:
        raise ValueError("Invalid upstream Stash rule-provider URL")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/", 1)[0] + "/" + filename, parts.query, parts.fragment))


def _remote(policy: str, behavior: str, url: str, interval="28800", no_resolve=False) -> str:
    return f"ruleset={policy},{behavior}:{url},{interval}" + ("|no-resolve" if no_resolve else "")


def _project_rule(line: str, direct_source: str, ads_url: str | None) -> list[str]:
    try:
        policy, specification = line.removeprefix("ruleset=").split(",", 1)
    except ValueError:
        raise ValueError("Invalid upstream Stash ruleset") from None
    if policy in {"PASS", "PASS-RULE", "COMPATIBLE"}:
        raise ValueError("Stash does not support this built-in policy")
    if specification.startswith("[]"):
        parts = specification[2:].split(",")
        kind = parts[0]
        if kind == "GEOSITE":
            if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_.@!-]+", parts[1]):
                raise ValueError("Invalid Stash GEOSITE category")
            return [_remote(policy, "clash-domain", f"{_META}/geosite/{quote(parts[1], safe='')}.mrs")]
        if kind == "GEOIP":
            if len(parts) not in {2, 3} or (len(parts) == 3 and parts[2] != "no-resolve"):
                raise ValueError("Unsupported Stash GEOIP options")
            category = parts[1].lower()
            if re.fullmatch(r"[a-z]{2}", category):
                return [line]
            if category not in _BUSINESS_GEOIP:
                raise ValueError("Unmapped non-country Stash GEOIP category")
            return [_remote(policy, "clash-ipcidr", f"{_META}/geoip/{category}.mrs", no_resolve=len(parts) == 3)]
        if parts == ["FINAL"] or kind in _INLINE:
            return [line]
        raise ValueError("Unsupported inline Stash rule")

    try:
        typed_url, options = specification.rsplit(",", 1)
        behavior, url = typed_url.split(":", 1)
    except ValueError:
        raise ValueError("Invalid upstream Stash provider") from None
    interval, *flags = options.split("|")
    if not interval.isdigit() or flags not in ([], ["no-resolve"]):
        raise ValueError("Unsupported Stash provider options")
    if behavior in {"clash-domain", "clash-ipcidr"}:
        return [line]
    if behavior != "clash-classic":
        raise ValueError("Unsupported Stash rule-provider format")
    filename = urlsplit(url).path.rsplit("/", 1)[-1]
    if url == ads_url or filename == "Custom_Port_Direct.yaml":
        return [line]
    if filename in _IP_FILES:
        result = [_remote(policy, "clash-ipcidr", _renamed_url(url, _IP_FILES[filename]), interval, True)]
        if filename == "Custom_Direct_Classical_IP.yaml":
            ports, omitted = _direct_ports(direct_source)
            result.extend(f"ruleset={policy},[]{port}" for port in ports)
            if omitted:
                result.append("; Stash: upstream SRC-PORT,41641 omitted for this converter profile; Stash documents SRC-PORT in beta iOS/tvOS 3.7+ and macOS 4.4+.")
        return result
    if filename == "Steam_CDN_Classical.yaml":
        return [
            _remote(policy, "clash-domain", _renamed_url(url, "Steam_CDN_Domain.mrs"), interval),
            _remote(policy, "clash-ipcidr", _renamed_url(url, "Steam_CDN_IP.mrs"), interval, True),
        ]
    raise ValueError("Unmapped classical provider in Stash template")


def _selector(name: str, selector: str, has_auto: bool) -> str | None:
    if selector.startswith("[]"):
        if selector[2:] in {"PASS", "PASS-RULE", "COMPATIBLE"}:
            raise ValueError("Unsupported built-in Stash group member")
        return selector
    if name == "🐢 低倍率节点":
        if "低倍率" not in selector or "(?<" not in selector:
            raise ValueError("Unexpected low-multiplier selector in Stash source")
        return "(低倍率|低倍)"
    if "(?!" in selector:
        return None if has_auto and name != "🌐 其他地区" else ".*"
    value = selector.replace("[A-Za-z]{2,}", "[A-Za-z][A-Za-z]+")
    for unsupported in ("|(?<!尼|-)日", "(?<!白)俄罗斯|", "(?<!白)俄|"):
        value = value.replace(unsupported, "")
    if "(?<" in value or "," in value or any(ord(c) < 32 for c in value):
        raise ValueError("Unmapped non-portable Stash node selector")
    return value


def _project_group(line: str) -> str:
    fields = line.split("`")
    if len(fields) < 3:
        raise ValueError("Incomplete Stash proxy group")
    name, kind = fields[0].removeprefix("custom_proxy_group="), fields[1]
    if kind == "select":
        candidates, suffix = fields[2:], []
        if any(x.startswith(("http://", "https://")) and x != _BENCHMARK for x in candidates):
            raise ValueError("Unexpected select-group URL in Stash source")
        candidates = [x for x in candidates if x != _BENCHMARK]
    elif kind in {"fallback", "url-test"}:
        if len(fields) < 5 or fields[-2] != _BENCHMARK:
            raise ValueError("Unsupported benchmark group in Stash source")
        interval = fields[-1].split(",", 1)[0]
        if not interval.isdigit():
            raise ValueError("Invalid Stash benchmark interval")
        candidates, suffix = fields[2:-2], fields[-2:]
    else:
        raise ValueError("Unsupported Stash proxy-group type")
    has_auto = "[]♻️ 自动选择" in candidates
    projected = [_selector(name, x, has_auto) for x in candidates]
    projected = [x for x in projected if x is not None]
    if not projected or sum(not x.startswith("[]") for x in projected) > 1:
        raise ValueError("Stash group needs candidates and at most one node selector")
    return "`".join(fields[:2] + projected + suffix)


def _validate_references(text: str) -> None:
    groups = [line.strip().split("`") for line in text.splitlines() if line.strip().startswith("custom_proxy_group=")]
    names = [group[0].removeprefix("custom_proxy_group=") for group in groups]
    if len(names) != len(set(names)) or set(names) & _BUILTINS:
        raise ValueError("Invalid Stash group names")
    available = set(names) | _BUILTINS
    for group in groups:
        for value in group[2:]:
            if value.startswith("[]") and value[2:] not in available:
                raise ValueError("Stash proxy group references an unknown policy")
    for line in text.splitlines():
        if line.strip().startswith("ruleset=") and line.strip()[8:].split(",", 1)[0] not in available:
            raise ValueError("Stash ruleset references an unknown policy")


def _proxy_entry(text: str, primary: str, ad_name: str | None) -> str:
    """Prevent subconverter from appending its implicit Proxy after the ad group."""
    groups, offset, in_custom = [], 0, False
    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_custom = line.lower() == "[custom]"
        if in_custom and line.startswith("custom_proxy_group="):
            name = line.split("`", 1)[0].removeprefix("custom_proxy_group=")
            groups.append((name, offset, offset + len(raw)))
        offset += len(raw)
    if any(name == "Proxy" for name, _, _ in groups):
        return text
    if not groups:
        raise ValueError("Stash needs an existing primary proxy group")
    insertion = next((start for name, start, _ in groups if name == ad_name), groups[-1][2])
    match = re.search(r"\r\n|\n|\r", text)
    newline = match[0] if match else "\n"
    separator = "" if insertion == 0 or text[insertion - 1] in "\r\n" else newline
    entry = f"custom_proxy_group=Proxy`select`[]{primary}"
    return text[:insertion] + separator + entry + newline + text[insertion:]


def build_stash_ini(source_text: str, personal: dict, settings: dict, proxy_group: str, direct_source_text: str) -> str:
    """Inject personal/ad policy, then render explicit Stash compatibility mappings."""
    _personal_supported(personal)
    composed = build_ini(source_text, personal, settings, proxy_group)
    ads_url = settings.get("ads", {}).get("url") if settings.get("ads", {}).get("enabled") else None
    ad_name = settings.get("ads", {}).get("group") if settings.get("ads", {}).get("enabled") else None
    composed = _proxy_entry(composed, proxy_group, ad_name)
    newline_match = re.search(r"\r\n|\n|\r", composed)
    newline = newline_match[0] if newline_match else "\n"
    rendered, in_custom = [], False
    for raw in composed.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        section = re.fullmatch(r"\[([^]]+)\]", stripped)
        if section:
            in_custom = section[1].lower() == "custom"
        if in_custom and stripped.startswith("ruleset="):
            replacements = _project_rule(stripped, direct_source_text, ads_url)
        elif in_custom and stripped.startswith("custom_proxy_group="):
            replacements = [_project_group(stripped)]
        else:
            rendered.append(raw)
            continue
        indent = line[:len(line) - len(line.lstrip())]
        ending = raw[len(line):]
        rendered.append(newline.join(indent + item for item in replacements) + ending)
    text = (
        "; Converter target=stash profile: GEOSITE and non-country GEOIP use MRS.\n"
        "; Benchmark URL/timeout/tolerance inputs are retained; the pinned v1.10.5 Stash exporter may omit them. Stash itself supports url-test tolerance.\n"
        "; For this converter's selector handling, complex exclusions use portable selectors or the existing automatic group; review node membership.\n"
    ).replace("\n", newline) + "".join(rendered)
    _validate_references(text)
    return text
