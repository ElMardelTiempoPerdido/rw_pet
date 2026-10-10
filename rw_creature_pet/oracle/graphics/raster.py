"""显示像素密度与局部画布；不改变世界坐标或物理步进。"""
from math import ceil, floor, hypot

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from ...shared.raster import pixel_density


def painter_scale(painter):
    # deviceTransform 已包含 Qt 的 DPR，不再单独乘系统缩放
    transform = painter.deviceTransform()
    return max(hypot(transform.m11(), transform.m12()), hypot(transform.m21(), transform.m22()))


def painter_density(painter, mode, scale=None, coarse_pixels_4x=False):
    if scale is None:
        scale = painter_scale(painter)
    return pixel_density(mode, scale, coarse_pixels_4x)


def stable_pixel_angle(angle):
    """抑制轴向附近的亚像素旋转；0.2° 内归轴，0.8° 外保留原角度。

    平滑过渡避免越过阈值时跳角；只用于绘制，不改变物理朝向或积累帧状态。
    """
    axis = round(angle/90)*90
    delta = angle-axis
    t = max(0., min(1., (abs(delta)-.2)/.6))
    return round(axis+delta*t*t*(3-2*t), 5)


def aligned_sprite(texture, rect, density, angle):
    """先对齐贴图边缘，再绕固定原点旋转，避免半像素采样随角度正负跳变。"""
    left, top = floor(rect.left()*density+.5), floor(rect.top()*density+.5)
    width, height = round(rect.width()*density), round(rect.height()*density)
    radius = ceil(hypot(max(abs(left), abs(left+width)), max(abs(top), abs(top+height))))+2
    image = QImage(radius*2, radius*2, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.translate(radius, radius)
        painter.rotate(angle)
        painter.drawImage(QRectF(left, top, width, height), texture)
    finally:
        painter.end()
    return image


def attached_sprite_rect(image, origin, density):
    width, height = image.width()/density, image.height()/density
    return QRectF(floor(origin.x*density+.5)/density-width/2,
                  floor(origin.y*density+.5)/density-height/2, width, height)


def local_canvas(bounds, density):
    """在世界坐标的显示像素网格上取整，包围盒变化不会移动采样网格。"""
    left, top = floor(bounds.left()*density), floor(bounds.top()*density)
    right, bottom = ceil(bounds.right()*density), ceil(bounds.bottom()*density)
    image = QImage(max(1, right-left), max(1, bottom-top),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    target = QRectF(left/density, top/density, image.width()/density, image.height()/density)
    return image, target
