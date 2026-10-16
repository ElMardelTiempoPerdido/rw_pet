"""角色自己的附加外观调整，默认值保持内置套装的原始效果"""
from dataclasses import dataclass, fields, replace
from math import isfinite

from ..shared.messages import Message


@dataclass(frozen=True, slots=True)
class OutfitPartSettings:
    enabled: bool = True
    offset_x: float = 0.
    offset_y: float = 0.
    mirror: bool = False
    hue: float = 0.
    saturation: float = 0.
    brightness: float = 0.

    def __post_init__(self):
        for name in ('enabled', 'mirror'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(Message('附加外观参数 {name} 必须为布尔值', name=name))
        for name, low, high in (('offset_x', -32, 32), ('offset_y', -32, 32),
                                ('hue', -180, 180), ('saturation', -100, 100), ('brightness', -100, 100)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
                    or not low <= value <= high):
                raise ValueError(Message('附加外观参数 {name} 必须在 {low}～{high} 之间',
                                         name=name, low=low, high=high))


@dataclass(frozen=True, slots=True)
class MaidSettings:
    head: OutfitPartSettings = OutfitPartSettings()
    lace: OutfitPartSettings = OutfitPartSettings(mirror=True)
    apron: OutfitPartSettings = OutfitPartSettings()
    ribbon_up: OutfitPartSettings = OutfitPartSettings()
    ribbon_down: OutfitPartSettings = OutfitPartSettings()

    def __post_init__(self):
        if any(not isinstance(getattr(self, f.name), OutfitPartSettings) for f in fields(self)):
            raise ValueError('附加外观部件配置无效')

    @classmethod
    def from_mapping(cls, data):
        defaults = cls()
        if not isinstance(data, dict) or set(data)-{f.name for f in fields(cls)}:
            raise ValueError('附加外观部件配置无效')
        return cls(**{name: replace(getattr(defaults, name), **value) for name, value in data.items()})


@dataclass(frozen=True, slots=True)
class OutfitSettings:
    maid: MaidSettings = MaidSettings()

    def __post_init__(self):
        if not isinstance(self.maid, MaidSettings):
            raise ValueError('附加外观配置无效')

    @classmethod
    def from_mapping(cls, data):
        values = dict(data)
        values['maid'] = MaidSettings.from_mapping(values.get('maid', {}))
        return cls(**values)
