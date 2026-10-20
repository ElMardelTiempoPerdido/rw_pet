"""角色固有的服装 PNG 槽位，与可更换的附加外观独立"""
from dataclasses import dataclass
from typing import ClassVar

from .face_config import FaceDecal


CLOTHING_DECAL_FIELDS = ('clothing_decal_1', 'clothing_decal_2', 'clothing_decal_3')
CLOTHING_PARTS = ('robe', 'left_sleeve', 'right_sleeve')


@dataclass(frozen=True, slots=True)
class ClothingDecal(FaceDecal):
    IMAGE_MAX_SIZE: ClassVar[int] = 128
    OFFSET_LIMIT: ClassVar[float] = 128.
    part: str = 'robe'

    def __post_init__(self):
        FaceDecal.__post_init__(self)
        if self.part not in CLOTHING_PARTS:
            raise ValueError('服装贴图部位必须为 robe / left_sleeve / right_sleeve')
