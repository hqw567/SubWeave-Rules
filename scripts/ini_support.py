"""Compose portable subconverter rules without rewriting an upstream INI."""

from __future__ import annotations

import re


_SECTION = re.compile(r"^[ \t]*\[([^\]\r\n]+)\][ \t]*$")
_GROUP = re.compile(r"^[ \t]*custom_proxy_group[ \t]*=[ \t]*([^`\r\n]+)`")
_STATIC_TYPES = frozenset(
    {
        "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-WILDCARD",
        "DOMAIN-REGEX", "GEOSITE", "GEOIP", "IP-CIDR", "IP-CIDR6",
        "IP-SUFFIX", "IP-ASN", "SRC-IP-CIDR", "SRC-IP-CIDR6",
        "SRC-IP-SUFFIX", "SRC-IP-ASN", "SRC-GEOIP", "SRC-PORT", "DST-PORT",
        "IN-PORT", "IN-TYPE", "IN-USER", "IN-NAME", "NETWORK", "DSCP",
        "PROCESS-NAME", "PROCESS-PATH", "UID",
    }
)
_IP_TYPES = frozenset({"IP-CIDR", "IP-CIDR6", "IP-SUFFIX", "IP-ASN", "GEOIP"})


def _plain_value(value: object, field: str) -> str:
    """Forbid INI/control delimiters without including input in diagnostics."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string.")
    value = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} must not contain control characters.")
    if "`" in value:
        raise ValueError(f"{field} must not contain an INI group delimiter.")
    return value


def _convert_rule(rule: object, policies: set[str], proxy_group: str) -> str:
    text = _plain_value(rule, "Personal rule")
    parts = [part.strip() for part in text.split(",")]
    rule_type = parts[0].upper()
    if rule_type in {"MATCH", "FINAL"}:
        raise ValueError("Personal INI rules cannot use MATCH/FINAL; retain the upstream fallback.")
    if rule_type == "RULE-SET":
        raise ValueError("Personal RULE-SET rules are not portable to INI; use individual rules instead.")
    if rule_type not in _STATIC_TYPES:
        raise ValueError("This personal rule type is not portable to INI; use a simple static rule without logical or sub-rule expressions.")
    if len(parts) not in (3, 4) or any(not part for part in parts):
        raise ValueError("Personal INI rules must use TYPE,payload,policy[,no-resolve].")
    if len(parts) == 4 and (parts[3] != "no-resolve" or rule_type not in _IP_TYPES):
        raise ValueError("The optional no-resolve flag is supported only for destination IP rules.")
    payload = parts[1]
    policy = {"@proxy": proxy_group, "@direct": "DIRECT", "@reject": "REJECT"}.get(parts[2], parts[2])
    if policy not in policies:
        raise ValueError("Personal INI rule references an unknown policy; use an upstream group or @proxy/@direct/@reject.")
    suffix = ",no-resolve" if len(parts) == 4 else ""
    return f"ruleset={policy},[]{rule_type},{payload}{suffix}"


def build_ini(source_text: str, personal: dict, settings: dict, proxy_group: str) -> str:
    """Prepend personal/advertising rules and an ad selector to an upstream INI.

    Every original character, line ending, comment, option and group stays in
    place. Only additions to the existing [custom] section are made. This
    function does not fetch sources, process credentials, or write files.
    """
    if not isinstance(source_text, str):
        raise ValueError("The upstream INI must be text.")
    if not isinstance(personal, dict) or not isinstance(settings, dict):
        raise ValueError("Personal rules and settings must be mappings.")
    lines = source_text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    custom_sections: list[int] = []
    for index, line in enumerate(lines):
        offsets.append(position)
        position += len(line)
        section = _SECTION.fullmatch(line.rstrip("\r\n"))
        if section and section[1].lower() == "custom":
            custom_sections.append(index)
    if len(custom_sections) != 1:
        raise ValueError("The upstream INI must contain exactly one [custom] section.")
    custom_index = custom_sections[0]
    section_end = len(lines)
    for index in range(custom_index + 1, len(lines)):
        if _SECTION.fullmatch(lines[index].rstrip("\r\n")):
            section_end = index
            break
    group_indices: list[int] = []
    policies = {"DIRECT", "REJECT", "PASS"}
    for index in range(custom_index + 1, section_end):
        group = _GROUP.match(lines[index])
        if group:
            group_indices.append(index)
            policies.add(group[1].strip())

    ads = settings.get("ads", {})
    if not isinstance(ads, dict) or not isinstance(ads.get("enabled", False), bool):
        raise ValueError("Advertising settings must contain a boolean enabled flag.")
    ad_rule: list[str] = []
    ad_group: str | None = None
    if ads.get("enabled", False):
        name = _plain_value(ads.get("group"), "Advertising group")
        url = _plain_value(ads.get("url"), "Advertising rule URL")
        interval = ads.get("interval", 86400)
        if "," in name or "=" in name or "," in url:
            raise ValueError("Advertising fields contain an unsupported INI delimiter.")
        if name in policies:
            raise ValueError("The advertising group must have a name not used by the upstream INI.")
        if not group_indices:
            raise ValueError("The upstream INI needs an existing proxy group before adding advertising controls.")
        if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
            raise ValueError("The advertising interval must be a positive integer.")
        policies.add(name)
        ad_rule = [f"ruleset={name},clash-classic:{url},{interval}"]
        if proxy_group not in policies:
            raise ValueError("The advertising alternative must reference an existing upstream policy.")
        ad_group = f"custom_proxy_group={name}`select`[]REJECT`[]{proxy_group}"

    rule_parts: dict[str, list[str]] = {}
    for key in ("before_ads", "after_ads"):
        rules = personal.get(key, [])
        if not isinstance(rules, list):
            raise ValueError("Personal before_ads and after_ads values must be lists.")
        rule_parts[key] = [_convert_rule(rule, policies, proxy_group) for rule in rules]
    added_rules = rule_parts["before_ads"] + ad_rule + rule_parts["after_ads"]
    if not added_rules and ad_group is None:
        return source_text

    newline_match = re.search(r"\r\n|\n|\r", source_text)
    newline = newline_match[0] if newline_match else "\n"
    additions: list[tuple[int, str]] = []
    if ad_group is not None:
        last_group = group_indices[-1]
        line = lines[last_group]
        separator = "" if line.endswith(("\r", "\n")) else newline
        additions.append((offsets[last_group] + len(line), separator + ad_group + newline))
    if added_rules:
        header = lines[custom_index]
        header_end = offsets[custom_index] + len(header)
        separator = "" if header.endswith(("\r", "\n")) else newline
        additions.append((header_end, separator + newline.join(added_rules) + newline))
    result = source_text
    # Insert from the end so source offsets remain valid. Display order of groups
    # is independent from the matching order of the prepended rules.
    for offset, addition in sorted(additions, key=lambda item: item[0], reverse=True):
        result = result[:offset] + addition + result[offset:]
    return result
