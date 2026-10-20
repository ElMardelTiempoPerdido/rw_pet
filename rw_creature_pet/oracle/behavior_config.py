"""角色行为参数，按行动维度归组；不包含设备设置或物理安全限制"""
from dataclasses import dataclass, fields
from math import isfinite

from ..shared.messages import Message


def validate_number(path, value, minimum, maximum):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or not minimum <= value <= maximum):
        raise ValueError(Message('{path} 必须为 {minimum}～{maximum} 之间的有限数值',
                                 path=path, minimum=minimum, maximum=maximum))


def validate_range(path, minimum, maximum):
    if minimum > maximum:
        raise ValueError(Message('{path} 的最小值不能大于最大值', path=path))


@dataclass(frozen=True, slots=True)
class DailyActivityConfig:
    idle_min_seconds: float = 3.
    idle_max_seconds: float = 6.
    long_idle_min_seconds: float = 7.5
    long_idle_max_seconds: float = 18.
    move_min_distance: float = 60.
    move_max_distance: float = 160.
    idle_weight: float = 28.
    move_weight: float = 35.
    meditate_weight: float = 12.
    meditate_min_seconds: float = 30.
    meditate_max_seconds: float = 60.
    cross_edge_cooldown_seconds: float = 60.
    cross_edge_check_seconds: float = 20.
    move_lean_degrees: float = 20.

    def __post_init__(self):
        for field in fields(self):
            name = field.name
            if name.endswith('_weight'):
                limits = (0, 100)
            elif name.endswith('_distance'):
                limits = (30, 1000)
            elif name == 'move_lean_degrees':
                limits = (0, 25)
            elif name == 'cross_edge_cooldown_seconds':
                limits = (0, 3600)
            elif name == 'cross_edge_check_seconds':
                limits = (1, 3600)
            else:
                limits = (.1, 3600)
            validate_number('oracle.daily_activity.'+name, getattr(self, name), *limits)
        for name, unit in (('idle', 'seconds'), ('long_idle', 'seconds'),
                           ('move', 'distance'), ('meditate', 'seconds')):
            if getattr(self, name+'_min_'+unit) > getattr(self, name+'_max_'+unit):
                raise ValueError(Message('{path} 的最小值不能大于最大值',
                                         path='oracle.daily_activity.'+name))
        if self.idle_weight+self.move_weight+self.meditate_weight <= 0:
            raise ValueError('停留、移动和冥想权重不能同时为 0')


@dataclass(frozen=True, slots=True)
class ReadingConfig:
    # 普通停留后的读珠选择，与停留 / 移动 / 冥想的相对权重独立
    start_probability: float = .25

    def __post_init__(self):
        validate_number('oracle.reading.start_probability', self.start_probability, 0, 1)
