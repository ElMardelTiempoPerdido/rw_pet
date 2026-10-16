"""自定义迭代器的两个柔性附件槽位，尺寸均为逻辑像素"""
from dataclasses import dataclass
from math import isfinite
import re
from typing import ClassVar

from ..shared.messages import Message


SOFT_PART_FIELDS = ('soft_part_1', 'soft_part_2')
SOFT_ANCHORS = ('neck', 'head', 'waist')
SOFT_SHAPES = ('rectangle', 'ellipse', 'trapezoid', 'triangle', 'line', 'png')
SOFT_LAYERS = ('back', 'front')
SOFT_PART_RANGES = {
    'offset_x': (-32., 32.), 'offset_y': (-32., 32.), 'angle': (-180., 180.),
    'length': (2., 64.), 'width': (.5, 24.), 'softness': (0., 1.), 'damping': (0., 1.),
    'tip_width_ratio': (0., 1.),
}


@dataclass(frozen=True, slots=True)
class SoftPart:
    IMAGE_MAX_SIZE: ClassVar[int] = 128
    enabled: bool = False
    kind: str = 'rectangle'
    layer: str = 'front'
    image_path: str = ''
    image_name: str = ''
    tip_width_ratio: float = .5
    anchor: str = 'neck'
    offset_x: float = 0.
    offset_y: float = 0.
    angle: float = 0.  # 相对固定部位朝脚方向，正值顺时针
    length: float = 28.
    width: float = 4.
    color: str = '#ffb7c5'
    softness: float = .7
    damping: float = .5  # 越大越快停止回摆，不直接暴露积分阻尼系数

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('柔性部件开关必须为布尔值')
        if self.anchor not in SOFT_ANCHORS:
            raise ValueError('柔性部件固定点必须为 neck / head / waist')
        if self.kind not in SOFT_SHAPES:
            raise ValueError('不支持的柔性部件形状')
        if self.layer not in SOFT_LAYERS:
            raise ValueError('柔性部件图层必须为 back / front')
        if not isinstance(self.image_path, str) or not isinstance(self.image_name, str):
            raise ValueError('柔性部件贴图路径和名称必须为字符串')
        if not isinstance(self.color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.color):
            raise ValueError('柔性部件颜色必须为 #RRGGBB')
        for name, (low, high) in SOFT_PART_RANGES.items():
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (float, int))
                    or not isfinite(value) or not low <= value <= high):
                raise ValueError(Message('柔性部件 {name} 必须在 {low}～{high} 之间',
                                         name=name, low=low, high=high))
