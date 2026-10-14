"""自定义耳机的对称主体和三个刚性配件，不依赖 Qt"""
from dataclasses import dataclass
from functools import lru_cache
from math import hypot, isfinite

from .face_config import FaceDecal
from ..shared.messages import Message

EAR_PART_FIELDS = ('ear_body', 'ear_part_1', 'ear_part_2', 'ear_part_3')
EAR_SHAPES = ('ellipse', 'rectangle', 'trapezoid', 'triangle', 'line', 'png')
EAR_TONES = ('shell', 'highlight', 'split')


@dataclass(frozen=True, slots=True)
class EarPart(FaceDecal):
    kind: str = 'rectangle'
    width: float = 2.
    height: float = 5.5
    rotation: float = 0.
    tone: str = 'shell'

    def __post_init__(self):
        FaceDecal.__post_init__(self)
        if self.kind not in EAR_SHAPES:
            raise ValueError('不支持的耳机形状')
        if self.tone not in EAR_TONES:
            raise ValueError('不支持的耳机配色方式')
        for name, low, high in (('width', .5, 32.), ('height', .5, 32.), ('rotation', -180., 180.)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
                    or not low <= value <= high):
                raise ValueError(Message('耳机参数 {name} 必须在 {low}～{high} 之间', name=name, low=low, high=high))


@lru_cache(maxsize=128)
def ear_radius(shape):
    """覆盖所有视线和旋转的保守半径，供头图、脏区和鼠标命中共用"""
    if shape is None:
        return 0.
    result = 0.
    for name in EAR_PART_FIELDS:
        part = getattr(shape, name)
        if not part.enabled or (part.kind == 'png' and not part.image_path):
            continue
        half = hypot(part.width, part.height)/2
        result = max(result, hypot(6+1.75*(abs(part.offset_x)+half), abs(part.offset_y)+half)+2)
    return result
