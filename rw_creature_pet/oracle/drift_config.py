"""反重力漫游的停走节奏，跨边与读珠参数由各自维度负责"""
from dataclasses import dataclass, fields

from .behavior_config import validate_number, validate_range


@dataclass(frozen=True, slots=True)
class DriftConfig:
    cooldown_seconds: float = 120.
    duration_variation: float = .1
    entry_min_seconds: float = 2.5
    entry_max_seconds: float = 5.
    resume_min_seconds: float = .5
    resume_max_seconds: float = 3.
    short_pause_min_seconds: float = .35
    short_pause_max_seconds: float = 1.2
    normal_pause_min_seconds: float = 1.8
    normal_pause_max_seconds: float = 5.5
    long_pause_min_seconds: float = 7.
    long_pause_max_seconds: float = 14.
    short_pause_weight: float = 50.
    normal_pause_weight: float = 35.
    long_pause_weight: float = 15.
    bout_min_seconds: float = 4.
    bout_max_seconds: float = 10.
    long_bout_min_seconds: float = 12.
    long_bout_max_seconds: float = 24.
    long_bout_probability: float = .35
    move_min_distance: float = 60.
    move_max_distance: float = 100.
    speed_min_factor: float = .8
    speed_max_factor: float = 1.2

    def __post_init__(self):
        for field in fields(self):
            name = field.name
            if name == 'duration_variation':
                limits = (0, .5)
            elif name == 'long_bout_probability':
                limits = (0, 1)
            elif name.endswith('_weight'):
                limits = (0, 100)
            elif name.endswith('_distance'):
                limits = (30, 1000)
            elif name.endswith('_factor'):
                limits = (.1, 2)
            elif name.startswith(('bout_', 'long_bout_')):
                limits = (.1, 3600)
            else:
                limits = (0, 3600)
            validate_number('oracle.drift.'+name, getattr(self, name), *limits)
        pairs = [(name, 'seconds') for name in (
            'entry', 'resume', 'short_pause', 'normal_pause', 'long_pause', 'bout', 'long_bout')]
        for name, unit in (*pairs, ('move', 'distance'), ('speed', 'factor')):
            validate_range('oracle.drift.'+name,
                           getattr(self, name+'_min_'+unit), getattr(self, name+'_max_'+unit))
        if self.short_pause_weight+self.normal_pause_weight+self.long_pause_weight <= 0:
            raise ValueError('短暂停顿、普通停顿和长歇权重不能同时为 0')
