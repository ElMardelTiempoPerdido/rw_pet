"""实体局部 alpha 的柔和外发光；不接收光环/投影，静止时复用模糊结果。"""
from math import ceil

from PIL import Image, ImageChops, ImageFilter
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter


class GlowLayer:
    def __init__(self):
        self.key = None
        self.image = None
        self.offset = QRectF()

    def prepare(self, source, key, color, radius, density):
        key = (key, color, radius, density)
        if key == self.key:
            return
        alpha = source.convertToFormat(QImage.Format.Format_Alpha8)
        mask = Image.frombytes('L', (alpha.width(), alpha.height()), bytes(alpha.constBits()),
                               'raw', 'L', alpha.bytesPerLine())
        bounds = mask.getbbox()
        self.image = None
        if bounds is not None:
            mask = mask.crop(bounds)
            padding = ceil(radius*density)+2
            padded = Image.new('L', (mask.width+2*padding, mask.height+2*padding))
            padded.paste(mask, (padding, padding))
            # 半径约为三倍 sigma；加一点强度，让单像素线缆也能显出柔光。
            blurred = padded.filter(ImageFilter.GaussianBlur(radius*density/3))
            blurred = blurred.point(tuple(min(200, round(i*1.6)) for i in range(256)))
            outside = ImageChops.multiply(blurred, ImageChops.invert(padded))
            rgb = QColor(color)
            tinted = Image.new('RGBA', padded.size, (rgb.red(), rgb.green(), rgb.blue(), 0))
            tinted.putalpha(outside)
            self.image = QImage(tinted.tobytes(), tinted.width, tinted.height,
                                QImage.Format.Format_RGBA8888).copy().convertToFormat(
                                    QImage.Format.Format_ARGB32_Premultiplied)
            self.offset = QRectF((bounds[0]-padding)/density, (bounds[1]-padding)/density,
                                 tinted.width/density, tinted.height/density)
        self.key = key

    def draw(self, painter, source_rect):
        if self.image is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(self.offset.translated(source_rect.topLeft()), self.image)
        painter.restore()
