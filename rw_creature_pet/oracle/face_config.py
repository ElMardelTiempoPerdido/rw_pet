"""自定义面部贴图参数，不依赖 Qt 或贴图读取"""
from dataclasses import dataclass
from math import isfinite

from ..shared.messages import Message

FACE_IMAGE_MAX_SIZE = 32
FACE_OFFSET_LIMIT = 32.


@dataclass(frozen=True, slots=True)
class FaceDecal:
    enabled: bool = False
    image_path: str = ''
    image_name: str = ''
    offset_x: float = 0.
    offset_y: float = 0.

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('面部贴图开关必须为布尔值')
        if not isinstance(self.image_path, str) or not isinstance(self.image_name, str):
            raise ValueError('面部贴图路径和名称必须为字符串')
        for name in ('offset_x', 'offset_y'):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or abs(value) > FACE_OFFSET_LIMIT):
                raise ValueError(Message('面部贴图偏移必须在 -{limit}～{limit} 逻辑像素之间', limit=FACE_OFFSET_LIMIT))
