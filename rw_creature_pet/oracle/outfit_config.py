"""角色自己的附加外观调整，默认值保持内置套装的原始效果"""
from dataclasses import dataclass, fields, replace
from math import isfinite

from ..shared.messages import Message
from .outfit_layout import Anchor, MAID_PLACEMENTS, Slot, resolved_slot


@dataclass(frozen=True, slots=True)
class OutfitPartSettings:
    enabled: bool = True
    anchor: str = Anchor.HEAD_CROWN
    layer: str = Slot.BEHIND_HEAD
    offset_x: float = 0.
    offset_y: float = 0.
    mirror: bool = False
    hue: float = 0.
    saturation: float = 0.
    brightness: float = 0.

    def __post_init__(self):
        try:
            anchor = Anchor(self.anchor)
            layer = resolved_slot(anchor, self.layer)
        except (ValueError, TypeError):
            raise ValueError('附加外观的锚点或层级无效') from None
        object.__setattr__(self, 'anchor', anchor)
        object.__setattr__(self, 'layer', layer)
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


def maid_part_settings(part_id, **values):
    anchor, layer = MAID_PLACEMENTS[part_id]
    return OutfitPartSettings(anchor=anchor, layer=layer, **values)


@dataclass(frozen=True, slots=True)
class MaidSettings:
    head: OutfitPartSettings = maid_part_settings('head')
    lace: OutfitPartSettings = maid_part_settings('lace', mirror=True)
    apron: OutfitPartSettings = maid_part_settings('apron')
    ribbon_up: OutfitPartSettings = maid_part_settings('ribbon_up')
    ribbon_down: OutfitPartSettings = maid_part_settings('ribbon_down')

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
