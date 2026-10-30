"""所有生物共用的交互开关；默认保持原有全穿透行为。"""
from dataclasses import dataclass
from math import isfinite
from ..shared.messages import Message


@dataclass(frozen=True, slots=True)
class InteractionConfig:
    drag_enabled: bool = False
    hover_radius: float = 160.
    hover_dwell_seconds: float = 1.5
    hover_probability: float = .60
    hover_open_probability: float = .25
    hover_avoidance_enabled: bool = True
    petting_enabled: bool = True
    petting_seconds: float = 1.5
    petting_grace_seconds: float = .6

    def __post_init__(self):
        if type(self.drag_enabled) is not bool:
            raise ValueError('interaction.drag_enabled 必须为布尔值')
        if type(self.hover_avoidance_enabled) is not bool:
            raise ValueError('interaction.hover_avoidance_enabled 必须为布尔值')
        if type(self.petting_enabled) is not bool:
            raise ValueError('interaction.petting_enabled 必须为布尔值')
        for name, low, high in (('petting_seconds', .1, 60), ('petting_grace_seconds', 0, 10),
                                ('hover_radius', 1, 2000), ('hover_dwell_seconds', 0, 60),
                                ('hover_probability', 0, 1), ('hover_open_probability', 0, 1)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or not low <= value <= high):
                raise ValueError(Message('interaction.{name} 必须在 {low}～{high} 之间',
                                         name=name, low=low, high=high))


@dataclass(frozen=True, slots=True)
class AudioConfig:
    enabled: bool = True
    volume: float = .7

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('audio.enabled 必须为布尔值')
        if (isinstance(self.volume, bool) or not isinstance(self.volume, (int, float))
                or not isfinite(self.volume) or not 0 <= self.volume <= 1):
            raise ValueError('audio.volume 必须在 0～1 之间')
