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
    interval_min_seconds: float = 0.
    interval_max_seconds: float = 0.
    drift_probability: float = 1.
    drift_delay_min_seconds: float = 12.
    drift_delay_max_seconds: float = 24.
    drift_interval_min_seconds: float = 20.
    drift_interval_max_seconds: float = 40.
    avoidance_probability: float = .35
    notice_min_seconds: float = .9
    notice_max_seconds: float = 1.5
    observe_min_seconds: float = 40.
    observe_max_seconds: float = 60.
    playback_min_seconds: float = 90.
    playback_max_seconds: float = 120.
    eye_open_probability: float = .1
    matrix_probability: float = .5
    approach_weight: float = 35.
    recall_weight: float = 35.
    orbit_weight: float = 30.
    observe_distance: float = 50.
    recall_distance: float = 38.

    def __post_init__(self):
        prefix = 'oracle.reading.'
        for field in fields(self):
            name = field.name
            if name.endswith('_probability'):
                limits = (0, 1)
            elif name.endswith('_weight'):
                limits = (0, 100)
            elif name == 'observe_distance':
                limits = (32, 150)
            elif name == 'recall_distance':
                limits = (30, 150)
            elif name.startswith('interval_'):
                limits = (0, 3600)
            else:
                limits = (.1, 3600)
            validate_number(prefix+name, getattr(self, name), *limits)
        for field in fields(self):
            name = field.name
            if '_min_' in name:
                validate_range(prefix+name, getattr(self, name), getattr(self, name.replace('_min_', '_max_')))
        if self.approach_weight+self.recall_weight+self.orbit_weight <= 0:
            raise ValueError('靠近、召近和绕珠权重不能同时为 0')
