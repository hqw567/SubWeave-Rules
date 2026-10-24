"""Public filter schemes: custom rules alone or an official AWAvenue variant."""
from __future__ import annotations

DEFAULT_PROFILE = 'ads-only'
_BASE = 'https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/main/Filters/AWAvenue-Ads-Rule-Clash-Classical'
FILTER_PROFILES = {
    'custom-only': {'name': '仅自定义扩展', 'description': '基础分流加自定义规则，不附加秋风过滤。', 'categories': [], 'ruleUrl': None},
    'ads-only': {'name': '纯广告', 'description': '过滤广告，尽量减少对其他功能的影响。', 'categories': ['ads'], 'ruleUrl': _BASE + '-Only.Ads.yaml'},
    'full-protection': {'name': '完整防护', 'description': '同时过滤广告、追踪及更新、推送等不受欢迎的连接。', 'categories': ['ads', 'privacy', 'unwanted'], 'ruleUrl': _BASE + '.yaml'},
    'ads-unwanted': {'name': '广告＋不受欢迎', 'description': '保留统计与遥测，过滤广告及更新、推送等连接。', 'categories': ['ads', 'unwanted'], 'ruleUrl': _BASE + '-No.Privacy.yaml'},
    'ads-privacy': {'name': '广告＋隐私', 'description': '过滤广告与追踪，保留更新、推送等功能连接。', 'categories': ['ads', 'privacy'], 'ruleUrl': _BASE + '-No.Unwelcome.yaml'},
}


def select_profiles(profiles=None) -> list[str]:
    selected = set(profiles) if profiles is not None else set(FILTER_PROFILES)
    if not selected or selected - set(FILTER_PROFILES):
        raise ValueError('Unknown or empty filter-profile selection')
    return [profile for profile in FILTER_PROFILES if profile in selected]


def profile_settings(settings: dict, profile: str) -> dict:
    if profile not in FILTER_PROFILES:
        raise ValueError('Unknown filter profile')
    if not isinstance(settings, dict) or set(settings) != {'filter'}:
        raise ValueError('settings must contain only the filter section')
    options = settings['filter']
    if not isinstance(options, dict) or set(options) != {'name', 'group', 'interval'}:
        raise ValueError('filter must contain name, group and interval; subscription schemes select their own public URL')
    if not isinstance(options['interval'], int) or isinstance(options['interval'], bool) or options['interval'] <= 0:
        raise ValueError('filter.interval must be a positive integer')
    for key in ('name', 'group'):
        value = options[key]
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or c in ',`@' for c in value):
            raise ValueError('Invalid filter provider/group name')
    definition = FILTER_PROFILES[profile]
    # This is an internal composition model, not a legacy public configuration reader.
    return {'filter': {**options, 'name': options['name'] + '-' + profile, 'enabled': bool(definition['ruleUrl']), 'url': definition['ruleUrl']}}
