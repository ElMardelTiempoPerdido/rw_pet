"""柔性部件的前后独立图层，不进入身体/线缆或鼠标命中缓存"""
from PySide6.QtGui import QPainter

from .face_assets import face_image
from .glow import GlowLayer
from .soft_mesh import rasterize_strip


class SoftPartsRenderer:
    def __init__(self):
        self.cache = [None, None]
        self.glows = [GlowLayer(), GlowLayer()]

    def discard(self, index):
        if self.cache[index] is not None:
            self.cache[index] = None
            self.glows[index] = GlowLayer()

    def prepare(self, index, part, alpha, density):
        if part is None:
            self.discard(index)
            return None
        texture = None
        if part.config.kind == 'png':
            texture = face_image(part.config.image_path, part.config.IMAGE_MAX_SIZE)
            if texture.isNull():
                self.discard(index)
                return None
        sample = 1. if part.sleeping else alpha
        key = (part, part.revision, sample, density, part.config,
               texture.cacheKey() if texture is not None else None)
        cached = self.cache[index]
        if cached is None or cached[0] != key:
            image, target = rasterize_strip(part, sample, density, texture)
            self.cache[index] = cached = key, image, target
        return cached

    def draw_glow(self, painter, parts, alpha, density, color, radius):
        # 两个槽位独立模糊；所有柔光都在实体之前合成，后方附件不会照亮前方衣袍表面
        # 不透明度由公共发光入口统一应用，不参与模糊缓存键
        for index, part in enumerate(parts.parts):
            cached = self.prepare(index, part, alpha, density)
            if cached is not None:
                glow = self.glows[index]
                glow.prepare(cached[1], cached[0], color, radius, density)
                glow.draw(painter, cached[2])

    def draw(self, painter, parts, alpha, density, *, layer='front'):
        for index, part in enumerate(parts.parts):
            if part is not None and part.config.layer != layer:
                continue
            cached = self.prepare(index, part, alpha, density)
            if cached is None:
                continue
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawImage(cached[2], cached[1])
            painter.restore()
