"""在独立像素网格中生成椭圆，平移只改变落点，不改变像素轮廓"""
from dataclasses import dataclass
from functools import lru_cache
from math import ceil, floor

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QTransform


def _fit_ink(image):
    # 极扁／极细的椭圆，Qt 可能连最外侧整列／行都不覆盖
    # 消除这种空边，避免增大直径时可见宽度反而缩小；只在缓存未命中时检查
    w, h = image.width(), image.height()
    pixels = image.constBits().cast('I')
    stride = image.bytesPerLine()//4
    top, bottom, left, right = 0, h, 0, w
    while top < bottom and not any(pixels[top*stride:top*stride+w]):
        top += 1
    if top == bottom:
        return image
    while not any(pixels[(bottom-1)*stride:(bottom-1)*stride+w]):
        bottom -= 1
    while not any(pixels[y*stride+left] for y in range(top, bottom)):
        left += 1
    while not any(pixels[y*stride+right-1] for y in range(top, bottom)):
        right -= 1
    if (left, top, right, bottom) == (0, 0, w, h):
        return image
    return image.copy(left, top, right-left, bottom-top).scaled(
        w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)


@lru_cache(maxsize=128)
def ellipse_image(width, height, linear, color, highlight):
    # 先投影矢量，再按当前绘制密度生成像素；不把固定的 1× 位图放大
    transform = QTransform(*linear, 0., 0.)
    rect = QRectF(-width/2, -height/2, width, height)
    path = QPainterPath()
    path.addEllipse(rect)
    projected = transform.map(path)
    bounds = projected.boundingRect()
    w = max(1, floor(round(bounds.width(), 6)+.5))
    h = max(1, floor(round(bounds.height(), 6)+.5))
    # 整个直径取整一次，再分配到两侧，保留奇数宽度
    fit = QTransform.fromScale(w/bounds.width(), h/bounds.height())
    fit.translate(-bounds.left(), -bounds.top())
    outline = fit.map(projected)
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillPath(outline, QColor(color))
        if highlight is not None:
            painter.setClipPath(outline)
            rect.setWidth(width/2)
            half = QPainterPath()
            half.addRect(rect)
            painter.fillPath(fit.map(transform.map(half)), QColor(highlight))
    finally:
        painter.end()
    return _fit_ink(image)


@dataclass(frozen=True)
class PixelEllipse:
    width: float
    height: float
    color: str
    highlight: str | None = None
    mirrored: bool = False

    def draw(self, painter):
        if isinstance(painter, QPainter):
            self.replay(painter)
        else:
            painter.draw_deferred(self)

    def replay(self, painter):
        transform = painter.deviceTransform()
        inverse, invertible = transform.inverted()
        if not invertible:
            return
        # 平移不参与缓存键；在头部角度、视线、尺寸不变时复用同一轮廓
        linear = tuple(round(v, 8) for v in
                       (transform.m11(), transform.m12(), transform.m21(), transform.m22()))
        image = ellipse_image(self.width, self.height, linear, self.color, self.highlight)
        center = transform.map(QPointF())
        x = round(center.x()-image.width()/2, 6)
        y = round(center.y()-image.height()/2, 6)
        # 正视时，奇数直径的半像素取舍也应左右镜像
        left = ceil(x-.5) if self.mirrored else floor(x+.5)
        top = floor(y+.5)
        painter.save()
        try:
            painter.setWorldTransform(inverse, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawImage(QPointF(left, top), image)
        finally:
            painter.restore()
