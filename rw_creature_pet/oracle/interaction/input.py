"""Oracle 的可见人偶轮廓；柔性附件、发光、机械臂、线缆、珍珠和光环保持鼠标穿透"""
from PySide6.QtGui import QPainter

from ...interaction.hitmap import PixelHitMap
from ...shared.geometry import Vec2
from ..graphics.damage import cape_bounds, point_bounds
from ..graphics.raster import local_canvas, pixel_density
from ..graphics.outfit_definition import outfit_definition
from ..graphics.outfits import outfit_padding
from ..ear_config import ear_radius


class PuppetHitMap:
    def __init__(self):
        self.key = self.value = None

    def get(self, renderer, scene, alpha=1., *, raster_scale=1.):
        app = scene.appearance
        if app.sleeping:
            alpha = 1.
        density = pixel_density(scene.config.pixel_mode, raster_scale, scene.config.coarse_pixels_4x)
        key = (app, app.revision, alpha, renderer.colors, renderer.atlas, density,
               outfit_definition(scene.config.active_outfit, scene.config.outfit_settings),
               scene.config.body_appearance, scene.config.active_custom_appearance)
        if key != self.key:
            parts = (app.head, *app.hands, *app.feet, *app.cloth)
            if app.prince_robe is not None:
                parts += tuple(app.prince_robe.points)
            extra = outfit_padding(scene.config)
            bounds = point_bounds((p.sample(alpha) for p in parts), 20+extra)
            bounds = bounds.united(cape_bounds(scene))
            bounds = bounds.united(point_bounds((app.head.sample(alpha),),
                                                ear_radius(scene.config.active_custom_appearance)+extra))
            image, rect = local_canvas(bounds, density)
            painter = QPainter(image)
            try:
                # 柔性附件只在最终实体/发光合成时绘制，不进入此人偶轮廓缓存
                painter.scale(density, density)
                painter.translate(-rect.x(), -rect.y())
                renderer.draw_geometry(painter, scene, alpha, cords=False, pearl=False,
                                       halo=False, arm=False, cache_body=True, include_head=False,
                                       include_front_outfit=False)
                renderer.draw_scene_head(painter, scene, alpha, pixelated=True, raster_scale=density)
                renderer.draw_front_outfit(painter, scene, alpha, raster_scale=density)
            finally:
                painter.end()
            self.key = key
            self.value = PixelHitMap(image, Vec2(rect.x(), rect.y()), density)
        return self.value
