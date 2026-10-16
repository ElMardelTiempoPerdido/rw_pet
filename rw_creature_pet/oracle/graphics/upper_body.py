"""胸肩与袖子的公共尺寸接口，Bell 使用固定值，不启用自定义面部或服装逻辑"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpperBodyShape:
    chest_width: float = 12.
    chest_height: float = 8.
    shoulder_width: float = 10.
    sleeve_root_width: float = 8.
    sleeve_cuff_width: float = 10.
    sleeve_cuff_radius: float = 2.


BELL_UPPER_BODY = UpperBodyShape()


def upper_body_shape(custom=None):
    return BELL_UPPER_BODY if custom is None else custom
