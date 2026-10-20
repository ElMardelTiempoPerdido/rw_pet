"""自定义迭代器的单个斗篷槽位，尺寸使用逻辑像素"""
from dataclasses import dataclass
from math import isfinite
import re
from typing import ClassVar

from ..shared.messages import Message


CAPE_RANGES = {
    'length': (8., 48.),
    'neckline_width': (2., 24.), 'neckline_depth': (0., 16.), 'neckline_height': (-6., 8.),
    'neckline_roundness': (0., 1.), 'neckline_tip_radius': (0., 4.),
    'hem_trim_width': (0., 6.), 'hem_trim_gap': (0., 6.),
}


@dataclass(frozen=True, slots=True)
class Cape:
    enabled: bool = False
    length: float = 18.
    color: str = '#a00018'
    neckline_shape: str = 'arc'
    neckline_width: float = 10.
    neckline_depth: float = 3.
    neckline_height: float = 4.
    neckline_roundness: float = .65
    neckline_tip_radius: float = 0.
    hem_trim_enabled: bool = True
    hem_trim_color: str = '#f0c8a0'
    hem_trim_width: float = .8
    hem_trim_gap: float = 1.5
    # 复用领口轮廓算法，此槽位只提供底边彩边
    neckline_trim_enabled: ClassVar[bool] = False

    def __post_init__(self):
        for name in ('enabled', 'hem_trim_enabled'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(Message('斗篷参数 {name} 必须为布尔值', name=name))
        if self.neckline_shape not in ('arc', 'v'):
            raise ValueError('领口形状必须为 arc / v')
        for name in ('color', 'hem_trim_color'):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('斗篷颜色必须为 #RRGGBB')
        for name, (low, high) in CAPE_RANGES.items():
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (float, int))
                    or not isfinite(value) or not low <= value <= high):
                raise ValueError(Message('斗篷参数 {name} 必须在 {low}～{high} 之间',
                                         name=name, low=low, high=high))
