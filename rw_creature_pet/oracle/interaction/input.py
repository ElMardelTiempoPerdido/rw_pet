"""Oracle 的可见人偶轮廓；机械臂、线缆、珍珠、光环不写入命中图。"""
from PySide6.QtGui import QPainter

from ...interaction.hitmap import PixelHitMap
from ...shared.geometry import Vec2
from ..graphics.damage import point_bounds
from ..graphics.raster import local_canvas, pixel_density
from ..ear_config import ear_radius


class PuppetHitMap:
    def __init__(self):
        self.key = self.value = None

    def get(self, renderer, scene, alpha=1., *, raster_scale=1.):
        app = scene.appearance
        if app.sleeping:
            alpha = 1.
        density = pixel_density(scene.config.pixel_mode, raster_scale, scene.config.coarse_pixels_4x)
        key = (app, app.revision, alpha, renderer.colors, renderer.atlas, density, scene.config.outfit,
               scene.config.active_custom_appearance)
        if key != self.key:
            parts = (app.head, *app.hands, *app.feet, *app.cloth)
            bounds = point_bounds((p.sample(alpha) for p in parts), 20)
            bounds = bounds.united(point_bounds((app.head.sample(alpha),), ear_radius(scene.config.active_custom_appearance)))
            image, rect = local_canvas(bounds, density)
            painter = QPainter(image)
            try:
                painter.scale(density, density)
                painter.translate(-rect.x(), -rect.y())
                renderer.draw_geometry(painter, scene, alpha, cords=False, pearl=False,
                                       halo=False, arm=False, cache_body=True, include_head=False,
                                       include_chest_ribbon=False)
                renderer.draw_scene_head(painter, scene, alpha, pixelated=True, raster_scale=density)
                renderer.draw_chest_ribbon(painter, scene, alpha, raster_scale=density)
            finally:
                painter.end()
            self.key = key
            self.value = PixelHitMap(image, Vec2(rect.x(), rect.y()), density)
        return self.value
