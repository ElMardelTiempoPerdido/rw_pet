"""人偶的鼠标躲避风格；通用鼠标关注参数仍保留在 interaction"""
from dataclasses import dataclass, fields

from .behavior_config import validate_number, validate_range


@dataclass(frozen=True, slots=True)
class MouseAvoidanceConfig:
    delay_min_seconds: float = 1.
    delay_max_seconds: float = 6.
    probability: float = .95
    enter_distance: float = 55.
    exit_distance: float = 85.
    leave_grace_seconds: float = 1.5
    pointer_lag_seconds: float = .35
    retry_min_seconds: float = .1
    retry_max_seconds: float = .3
    impatience_min_seconds: float = 1.
    impatience_max_seconds: float = 1.5
    move_probability: float = .85
    move_min_distance: float = 18.
    move_max_distance: float = 32.
    speed_min: float = 1.8
    speed_max: float = 3.6
    lean_move_probability: float = .95
    lean_move_min_distance: float = 16.
    lean_move_max_distance: float = 80.
    lean_min_degrees: float = 30.
    lean_max_degrees: float = 60.
    lean_sample_power: float = 2.
    lean_speed: float = 90.
    move_angle_jitter: float = 22.

    def __post_init__(self):
        for field in fields(self):
            name = field.name
            if name.endswith('probability'):
                limits = (0, 1)
            elif name in ('enter_distance', 'exit_distance'):
                limits = (1, 1000)
            elif name.startswith('lean_move_'):
                limits = (3, 1000)
            elif name.endswith('_distance'):
                limits = (6, 1000)
            elif name.endswith('_degrees'):
                limits = (0, 85)
            elif name == 'lean_sample_power':
                limits = (.1, 10)
            elif name == 'lean_speed':
                limits = (1, 360)
            elif name == 'move_angle_jitter':
                limits = (0, 80)
            elif name.startswith('speed_'):
                limits = (.1, 5)
            elif name == 'pointer_lag_seconds':
                limits = (.01, 5)
            elif name.startswith('retry_'):
                limits = (.05, 60)
            elif name.startswith('impatience_'):
                limits = (.1, 60)
            else:
                limits = (0, 60)
            validate_number('oracle.mouse_avoidance.'+name, getattr(self, name), *limits)
        for name, unit in (('delay', 'seconds'), ('retry', 'seconds'), ('impatience', 'seconds'),
                           ('move', 'distance'), ('lean_move', 'distance'), ('lean', 'degrees')):
            validate_range('oracle.mouse_avoidance.'+name,
                           getattr(self, name+'_min_'+unit), getattr(self, name+'_max_'+unit))
        validate_range('oracle.mouse_avoidance.speed', self.speed_min, self.speed_max)
        if self.exit_distance < self.enter_distance+20:
            raise ValueError('躲避退出距离至少比进入距离大 20 逻辑像素')
