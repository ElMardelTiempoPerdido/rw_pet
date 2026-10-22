"""Prince 双层原色 PNG 的衣料网格投影，后层 _2、前层 _1"""
from functools import lru_cache

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from ..prince_assets import ROBE_BACK, ROBE_FRONT
from .clothing_decals import draw_texture_mesh
from .damage import point_bounds
from .raster import local_canvas


@lru_cache(maxsize=2)
def robe_image(path):
    image = QImage(str(path))
    if image.isNull():
        raise FileNotFoundError(path)
    return image


class LowerRobeRenderer:
    """共享变形后的透明图，显示、外发光和鼠标轮廓只栅格化一次双层网格"""
    def __init__(self):
        self.key = None
        self.image = self.target = None

    def draw(self, painter, robe, alpha, density):
        layers = tuple(tuple(p.sample(alpha) for p in layer.points) for layer in robe.layers)
        textures = tuple(robe_image(path) for path in (ROBE_BACK, ROBE_FRONT))
        # 使用实际插值姿态；尾端单独回摆、休眠及不同场景之间不会误用旧图
        key = (robe, layers, density, tuple(image.cacheKey() for image in textures))
        if key != self.key:
            bounds = point_bounds((p for vertices in layers for p in vertices), 1/density)
            image, target = local_canvas(bounds, density)
            local = QPainter(image)
            try:
                local.scale(density, density)
                local.translate(-target.x(), -target.y())
                rect = QRectF(0., 0., robe.art.width, robe.art.height)
                for texture, vertices in zip(textures, layers):
                    draw_texture_mesh(local, texture, rect, robe.coords, vertices, robe.triangles)
            finally:
                local.end()
            self.key, self.image, self.target = key, image, target
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawImage(self.target, self.image)
        painter.restore()


def draw_lower_robe(renderer, painter, scene, alpha, *, density=1.):
    robe = scene.appearance.prince_robe
    if robe is None:
        return
    renderer._prince_robe_renderer.draw(painter, robe, alpha, density)
