"""旧读珠三入口配置升级为单一尝试时钟；只转换输入，不改写来源文件"""
from .behavior_config import ReadingConfig, validate_number, validate_range


LEGACY_READING_FIELDS = frozenset((
    'interval_min_seconds', 'interval_max_seconds', 'drift_probability', 'avoidance_probability',
    'drift_delay_min_seconds', 'drift_delay_max_seconds',
    'drift_interval_min_seconds', 'drift_interval_max_seconds',
))
_PREFIX = 'oracle.reading.'


def migrate_reading(data):
    if not isinstance(data, dict):
        return data  # 交给原有配置入口报告结构错误
    result = {key: value for key, value in data.items() if key not in LEGACY_READING_FIELDS}
    interval_fields = ('interval_min_seconds', 'interval_max_seconds',
                       'drift_interval_min_seconds', 'drift_interval_max_seconds')
    if ('attempt_min_seconds' not in result or 'attempt_max_seconds' not in result) and any(
            key in data for key in interval_fields):
        defaults = ReadingConfig()
        low, high = data.get('interval_min_seconds', 0.), data.get('interval_max_seconds', 0.)
        for key, value in zip(interval_fields[:2], (low, high)):
            validate_number(_PREFIX+key, value, 0, 3600)
        validate_range(_PREFIX+'interval', low, high)
        if high == 0:
            low = data.get('drift_interval_min_seconds', defaults.attempt_min_seconds)
            high = data.get('drift_interval_max_seconds', defaults.attempt_max_seconds)
        result.setdefault('attempt_min_seconds', low)
        result.setdefault('attempt_max_seconds', high)
    return result


def migrate_reading_tree(data):
    """AppConfig / 角色的嵌套字典；必须在补齐新默认值之前调用"""
    if not isinstance(data, dict) or not isinstance(data.get('oracle'), dict):
        return data
    oracle = data['oracle']
    if 'reading' not in oracle:
        return data
    return {**data, 'oracle': {**oracle, 'reading': migrate_reading(oracle['reading'])}}


def migrate_reading_values(values):
    """个人覆盖和风格使用的完整路径字典"""
    if not isinstance(values, dict):
        return values
    reading = {key[len(_PREFIX):]: value for key, value in values.items() if key.startswith(_PREFIX)}
    if not reading:
        return values
    return {**{key: value for key, value in values.items() if not key.startswith(_PREFIX)},
            **{_PREFIX+key: value for key, value in migrate_reading(reading).items()}}
