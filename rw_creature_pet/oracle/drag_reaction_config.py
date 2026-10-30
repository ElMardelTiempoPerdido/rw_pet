"""拖动反应的角色节奏；物理限位、力上限与到达约束不开放为性格参数"""
from dataclasses import dataclass, fields

from .behavior_config import validate_number, validate_range


@dataclass(frozen=True, slots=True)
class DragReactionConfig:
    enabled: bool = True
    gesture_probability: float = .90
    flutter_probability: float = .85
    alternating_probability: float = .47
    eye_open_probability: float = .65
    voice_probability: float = .55
    gesture_delay_min_seconds: float = .15
    gesture_delay_max_seconds: float = 1.5
    gesture_interval_min_seconds: float = .45
    gesture_interval_max_seconds: float = 1.35
    gesture_duration_min_seconds: float = 1.4
    gesture_duration_max_seconds: float = 2.6
    gesture_speed: float = 1.
    gesture_min_amplitude: float = .25
    gesture_max_amplitude: float = 1.
    flutter_sync_probability: float = .35
    eye_delay_min_seconds: float = 0.
    eye_delay_max_seconds: float = 0.
    eye_interval_min_seconds: float = .9
    eye_interval_max_seconds: float = 2.
    eye_duration_min_seconds: float = 1.5
    eye_duration_max_seconds: float = 3.
    voice_delay_min_seconds: float = 0.
    voice_delay_max_seconds: float = 3.
    voice_interval_min_seconds: float = 1.8
    voice_interval_max_seconds: float = 3.8
    projection_delay_min_seconds: float = .15
    projection_delay_max_seconds: float = 1.5
    projection_interval_min_seconds: float = .45
    projection_interval_max_seconds: float = 1.35
    projection_duration_min_seconds: float = 8.25
    projection_duration_max_seconds: float = 8.25
    projection_frame_seconds: float = .375
    projection_lift_delay_seconds: float = .35
    projection_move_min_seconds: float = .65
    projection_move_max_seconds: float = 1.6

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('oracle.drag_reactions.enabled 必须为布尔值')
        prefix = 'oracle.drag_reactions.'
        for field in fields(self):
            name = field.name
            if name == 'enabled':
                continue
            if name.endswith(('_probability', '_amplitude')):
                limits = (0, 1)
            elif name == 'gesture_speed':
                limits = (.25, 3.)
            elif name == 'projection_frame_seconds':
                limits = (.025, 10.)
            elif '_duration_' in name:
                limits = (.1, 300.)
            elif '_interval_' in name or name.startswith('projection_move_'):
                limits = (.025, 300.)
            else:
                limits = (0., 300.)
            validate_number(prefix+name, getattr(self, name), *limits)
        for field in fields(self):
            name = field.name
            if '_min_' in name:
                validate_range(prefix+name, getattr(self, name), getattr(self, name.replace('_min_', '_max_')))
