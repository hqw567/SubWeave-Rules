"""Keep mainland domain and IP routing ahead of upstream proxy policies."""

from __future__ import annotations

import re


DIRECT_GROUP = "🎯 全球直连"
CHINA_RULES = [f"GEOSITE,cn,{DIRECT_GROUP}", f"GEOIP,cn,{DIRECT_GROUP}"]


def _is_china(kind: str, payload: str) -> bool:
    return kind.upper() in {"GEOSITE", "GEOIP"} and payload.lower() == "cn"


def prioritize_china_rules(rules: list[str]) -> list[str]:
    """Preserve leading direct exceptions, then check CN before proxy rules.

    The IP check deliberately permits DNS resolution: an unlisted domain may
    still resolve to a mainland address. Never apply this to user overrides.
    """
    remaining = [rule for rule in rules if not _is_china(*rule.split(",")[:2])]
    position = len(remaining)
    for index, rule in enumerate(remaining):
        fields = rule.split(",")
        policy = fields[-2] if fields[-1] in {"no-resolve", "src"} else fields[-1]
        if policy != DIRECT_GROUP or fields[0].upper() in {"MATCH", "FINAL"}:
            position = index
            break
    return remaining[:position] + CHINA_RULES + remaining[position:]


def prioritize_china_ini(text: str) -> str:
    """Apply the same routing order inside [custom], preserving other text."""
    lines = text.splitlines(keepends=True)
    in_custom = has_group = False
    entries = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        section = re.fullmatch(r"\[([^]]+)\]", line)
        if section:
            in_custom = section[1].lower() == "custom"
        if not in_custom:
            continue
        if line.startswith(f"custom_proxy_group={DIRECT_GROUP}`"):
            has_group = True
        if not line.startswith("ruleset="):
            continue
        policy, separator, specification = line[8:].partition(",")
        if not separator:
            raise ValueError("Invalid upstream INI ruleset")
        parts = specification[2:].split(",") if specification.startswith("[]") else []
        china = len(parts) >= 2 and _is_china(parts[0], parts[1])
        final = bool(parts) and parts[0].upper() in {"MATCH", "FINAL"}
        entries.append((index, policy, china, final))
    if not has_group:
        return text
    remaining = [entry for entry in entries if not entry[2]]
    if not remaining:
        raise ValueError("China direct routing requires an upstream fallback")
    position = next((index for index, policy, _, final in remaining
                     if policy != DIRECT_GROUP or final), remaining[-1][0])
    removed = {index for index, _, china, _ in entries if china}
    newline_match = re.search(r"\r\n|\n|\r", text)
    newline = newline_match[0] if newline_match else "\n"
    additions = (f"ruleset={DIRECT_GROUP},[]GEOSITE,cn" + newline
                 + f"ruleset={DIRECT_GROUP},[]GEOIP,cn" + newline)
    return "".join((additions if index == position else "") + ("" if index in removed else raw)
                   for index, raw in enumerate(lines))
