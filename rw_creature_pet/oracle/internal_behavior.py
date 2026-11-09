"""收回为内部实现的行为字段，旧配置仍可读取，运行时统一使用配置定义默认值"""
from dataclasses import fields, replace


_GROUPS = {
    '': ('pearl_matrix_avoid_radius', 'pearl_follow_width', 'pearl_follow_height'),
    'daily_activity': ('move_lean_degrees',),
    'drift': ('entry_min_seconds', 'entry_max_seconds', 'resume_min_seconds', 'resume_max_seconds'),
    'drag_reactions': ('projection_move_min_seconds', 'projection_move_max_seconds', 'projection_frame_seconds'),
    'reading': ('notice_min_seconds', 'notice_max_seconds'),
}
INTERNAL_BEHAVIOR_PATHS = frozenset(
    '.'.join(part for part in ('oracle', group, name) if part)
    for group, names in _GROUPS.items() for name in names
)


def internal_behavior_defaults(oracle):
    """在应用配置边界处理所有来源，不改写下载原件或影响底层物理调试配置"""
    changes = {}
    for group, names in _GROUPS.items():
        target = getattr(oracle, group) if group else oracle
        defaults = {field.name: field.default for field in fields(target) if field.name in names}
        if all(getattr(target, name) == value for name, value in defaults.items()):
            continue
        if group:
            changes[group] = replace(target, **defaults)
        else:
            changes.update(defaults)
    return replace(oracle, **changes) if changes else oracle
