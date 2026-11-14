"""Select a workspace zone from the final, independently verified exit only."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .state import SPXError


def validate_zone(value):
    if not isinstance(value, str) or not value or len(value) > 80 or any(c in value for c in ('..', '\\', ',', '\n', '\r', '\0')) or value.startswith('/'):
        raise SPXError('未取得有效的落地出口 IANA 时区。请重试检查，或在偏好设置中选择手动固定时区。')
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise SPXError('落地出口的时区无法识别。请重试检查，或选择手动固定时区。') from error
    return value


def mode(settings):
    value = settings.get('timezone_mode', 'exit')
    if value not in ('exit', 'manual'):
        raise SPXError('时区模式无效，请在偏好设置中重新保存。')
    return value


def apply_verified_exit(engine, evidence):
    settings = engine.store.settings()
    if mode(settings) == 'manual':
        return settings['timezone']
    # exit_probe binds GeoIP to the final IP verified by two HTTPS sources.
    # No country-to-zone guessing and no use of the first-hop line geography.
    zone = validate_zone(evidence.get('timezone'))
    if zone != settings['timezone']:
        settings['timezone'] = zone
        engine.store.write('settings.json', settings)
        engine.log('工作区时区已根据最终落地出口调整为 ' + zone + '；Windows 主机时区保持原设置。')
    engine.store.write('environment.json', {'timezone': zone})
    return zone
