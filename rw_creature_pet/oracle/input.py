"""Oracle 的可见人偶轮廓；机械臂、线缆、珍珠、光环不写入命中图。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from ..interaction.hitmap import PixelHitMap
from ..shared.geometry import Vec2
from .damage import point_bounds


class PuppetHitMap:
    def __init__(self):
        self.key = self.value = None

    def get(self, renderer, scene, alpha=1.):
        app = scene.appearance
        if app.sleeping:
            alpha = 1.
        key = (app, app.revision, alpha, renderer.colors, renderer.atlas)
        if key != self.key:
            parts = (app.head, *app.hands, *app.feet, *app.cloth)
            rect = point_bounds((p.sample(alpha) for p in parts), 20).toAlignedRect()
            image = QImage(rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                painter.translate(-rect.x(), -rect.y())
                renderer.draw_geometry(painter, scene, alpha, cords=False, pearl=False,
                                       halo=False, arm=False, cache_body=True)
            finally:
                painter.end()
            self.key = key
            self.value = PixelHitMap(image, Vec2(rect.x(), rect.y()))
        return self.value
