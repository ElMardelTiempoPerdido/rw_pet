"""四条固定细线缆的编号、配色及旧十四条配置的迁移"""
import re


# 保留原生成参数和覆盖顺序；显示编号按自然长度从短到长排列
FINE_CORD_SOURCE_INDICES = (0, 2, 8, 13)
LEGACY_FINE_COUNT = 14
# 第二项是旧绘制中的金属 / 红 / 蓝混色编号
FINE_CORD_COLORS = (
    ('cord_long_2', 1), ('cord_long_1', 0), ('cord_short_2', 1), ('cord_short_1', 2),
)
_OLD_TO_NEW = {'cord_short_9': 'cord_short_1', 'cord_long_4': 'cord_short_2',
               'cord_long_2': 'cord_long_1', 'cord_long_1': 'cord_long_2'}
_REMOVED = {'cord_long_3', 'cord_long_4', 'cord_long_5',
            *(f'cord_short_{i}' for i in range(3, 10))}
_OLD_FIELDS = _REMOVED | {name for name, _ in FINE_CORD_COLORS}


def migrate_cord_colors(colors):
    """旧表通过已删除字段识别；同时换名，避免长1/长2与短1/短2互相覆盖"""
    if not _REMOVED.intersection(colors):
        return dict(colors)
    result = {key: value for key, value in colors.items() if key not in _OLD_FIELDS}
    result.update({new: colors[old] for old, new in _OLD_TO_NEW.items() if old in colors})
    return result


def migrate_cord_tree(data):
    oracle = data.get('oracle')
    if not isinstance(oracle, dict):
        return data
    return {**data, 'oracle': {key: migrate_cord_colors(value)
            if key in ('colors', 'custom_colors', 'prince_colors') and isinstance(value, dict) else value
            for key, value in oracle.items()}}


def migrate_cord_values(values):
    """只迁移实际存在的字段，可用于部分修改，不添加其他颜色默认值"""
    result = dict(values)
    for palette in ('colors', 'custom_colors', 'prince_colors'):
        prefix = 'oracle.'+palette+'.'
        colors = {key[len(prefix):]: value for key, value in values.items() if key.startswith(prefix)}
        migrated = migrate_cord_colors(colors)
        for name in colors:
            result.pop(prefix+name)
        result.update({prefix+name: value for name, value in migrated.items()})
    return result


def legacy_cord_colors(joints):
    """按旧调色公式生成 #RRGGBB，不依赖 Qt；中间保留 QColor 的 16 位精度"""
    if not isinstance(joints, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', joints):
        return {}  # 原配色校验负责报告无效的关节色
    metal = [int(int(joints[i:i+2], 16)*257*.55+.5)/65535 for i in (1, 3, 5)]
    palette = []
    for source in (None, (1., 0., 0.), (0., 0., 1.)):
        channels = metal if source is None else [int((a*.45+b*.55)*65535+.5)/65535
                                                for a, b in zip(source, metal)]
        palette.append('#'+''.join(f'{int(c*255+.5):02x}' for c in channels))
    return {name: palette[index] for name, index in FINE_CORD_COLORS}


def complete_cord_colors(colors, default_joints='#424c5d'):
    """仅补齐旧配色缺失的线缆字段，之后各条颜色独立于关节色"""
    colors = migrate_cord_colors(colors)
    return {**legacy_cord_colors(colors.get('joints', default_joints)), **colors}


def complete_cord_values(values):
    """旧个人快照使用扁平路径，默认值与当前修改需各自按原关节色补齐"""
    values = migrate_cord_values(values)
    for palette in ('colors', 'custom_colors', 'prince_colors'):
        prefix = 'oracle.'+palette+'.'
        if any(key.startswith(prefix) for key in values):
            for name, color in legacy_cord_colors(values.get(prefix+'joints', '#424c5d')).items():
                values.setdefault(prefix+name, color)
    return values
