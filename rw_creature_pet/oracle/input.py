"""Oracle 的可见人偶轮廓；机械臂、线缆、珍珠、光环不写入命中图。"""
from PySide6.QtGui import QPainter

from ..interaction.hitmap import PixelHitMap
from ..shared.geometry import Vec2
from .damage import point_bounds
from .raster import local_canvas, pixel_density


class PuppetHitMap:
    def __init__(self):
        self.key = self.value = None

    def get(self, renderer, scene, alpha=1., *, raster_scale=1.):
        app = scene.appearance
        if app.sleeping:
            alpha = 1.
        density = pixel_density(scene.config.pixel_mode, raster_scale)
        key = (app, app.revision, alpha, renderer.colors, renderer.atlas, density)
        if key != self.key:
            parts = (app.head, *app.hands, *app.feet, *app.cloth)
            image, rect = local_canvas(point_bounds((p.sample(alpha) for p in parts), 20), density)
            painter = QPainter(image)
            try:
                painter.scale(density, density)
                painter.translate(-rect.x(), -rect.y())
                renderer.draw_geometry(painter, scene, alpha, cords=False, pearl=False,
                                       halo=False, arm=False, cache_body=True, include_head=False)
                renderer.draw_scene_head(painter, scene, alpha, pixelated=True, raster_scale=density)
            finally:
                painter.end()
            self.key = key
            self.value = PixelHitMap(image, Vec2(rect.x(), rect.y()), density)
        return self.value
