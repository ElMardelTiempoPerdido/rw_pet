"""角色保存的风格来源标记，不根据参数反推，也不驱动运行时行为"""
from dataclasses import dataclass, fields
import re


DIMENSIONS = ('daily_activity', 'drift', 'mouse_attention', 'mouse_avoidance',
              'drag_reactions', 'reading_habits', 'pearl_interaction')


@dataclass(frozen=True, slots=True)
class StyleSelection:
    id: str = ''
    version: str = ''

    def __post_init__(self):
        if (not isinstance(self.id, str) or not isinstance(self.version, str)
                or len(self.id) > 120 or not re.fullmatch(r'[a-z0-9_.-]*', self.id)
                or (self.version and not re.fullmatch(r'v1:[0-9a-f]{64}', self.version))
                or bool(self.id) != bool(self.version)):
            raise ValueError('Invalid behavior style selection')


@dataclass(frozen=True, slots=True)
class BehaviorStyleSelections:
    daily_activity: StyleSelection = StyleSelection()
    drift: StyleSelection = StyleSelection()
    mouse_attention: StyleSelection = StyleSelection()
    mouse_avoidance: StyleSelection = StyleSelection()
    drag_reactions: StyleSelection = StyleSelection()
    reading_habits: StyleSelection = StyleSelection()
    pearl_interaction: StyleSelection = StyleSelection()

    def __post_init__(self):
        if any(not isinstance(getattr(self, f.name), StyleSelection) for f in fields(self)):
            raise ValueError('Invalid behavior style selections')

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict) or set(data)-set(DIMENSIONS):
            raise ValueError('Invalid behavior style dimensions')
        return cls(**{key: StyleSelection(**value) for key, value in data.items()})
