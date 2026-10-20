"""Prince 双层原色 PNG 的衣料网格投影，后层 _2、前层 _1"""
from functools import lru_cache

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from ..prince_assets import ROBE_BACK, ROBE_FRONT
from .clothing_decals import draw_texture_mesh


@lru_cache(maxsize=2)
def robe_image(path):
    image = QImage(str(path))
    if image.isNull():
        raise FileNotFoundError(path)
    return image


def draw_lower_robe(renderer, painter, scene, alpha):
    robe = scene.appearance.prince_robe
    if robe is None:
        return
    art = robe.art
    rect = QRectF(0., 0., art.width, art.height)
    for path, layer in zip((ROBE_BACK, ROBE_FRONT), robe.layers):
        vertices = tuple(p.sample(alpha) for p in layer.points)
        draw_texture_mesh(painter, robe_image(path), rect, robe.coords, vertices, robe.triangles)
