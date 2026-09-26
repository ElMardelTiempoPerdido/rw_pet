"""所有生物共用的交互开关；默认保持原有全穿透行为。"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class InteractionConfig:
    drag_enabled: bool = False

    def __post_init__(self):
        if type(self.drag_enabled) is not bool:
            raise ValueError('interaction.drag_enabled 必须为布尔值')


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
