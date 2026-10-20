"""Prince 固定衣料素材的共享元数据，物理层不依赖 Qt"""
from dataclasses import dataclass
from functools import lru_cache

from ..shared.paths import PACKAGE_ROOT


ROBE_FRONT = PACKAGE_ROOT/'skin/prince/prince_lower_robe_1.png'
ROBE_BACK = PACKAGE_ROOT/'skin/prince/prince_lower_robe_2.png'


@dataclass(frozen=True, slots=True)
class RobeLayout:
    width: int
    height: int
    left: float
    right: float
    join_y: float
    color: str


@lru_cache(maxsize=1)
def robe_layout():
    from PIL import Image
    with Image.open(ROBE_FRONT) as source:
        front = source.convert('RGBA')
    with Image.open(ROBE_BACK) as back:
        if back.size != front.size:
            raise ValueError('Prince 两层衣袍素材必须使用相同画布尺寸')
    bounds = front.getbbox()
    if bounds is None:
        raise ValueError('Prince 前层衣袍素材为空')
    y = min(bounds[1]+1, bounds[3]-1)
    xs = [x for x in range(front.width) if front.getpixel((x, y))[3] == 255]
    left, right = min(xs), max(xs)+1
    r, g, b, _ = front.getpixel(((left+right)//2, y))
    return RobeLayout(front.width, front.height, float(left), float(right), float(y),
                      f'#{r:02x}{g:02x}{b:02x}')
