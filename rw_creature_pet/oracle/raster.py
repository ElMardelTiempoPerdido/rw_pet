"""显示像素密度与局部画布；不改变世界坐标或物理步进。"""
from math import ceil, floor, hypot

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage


def pixel_density(mode, scale):
    # 低于 1× 仍缩小原始像素；与桌面倍率上限一致，限制局部画布开销。
    return 1. if mode == 'classic' else round(max(1., min(4., scale)), 6)


def painter_density(painter, mode, scale=None):
    if scale is None:
        # deviceTransform 已包含 Qt 的 DPR，不再单独乘系统缩放。
        transform = painter.deviceTransform()
        scale = max(hypot(transform.m11(), transform.m12()),
                    hypot(transform.m21(), transform.m22()))
    return pixel_density(mode, scale)


def local_canvas(bounds, density):
    """在世界坐标的显示像素网格上取整，包围盒变化不会移动采样网格。"""
    left, top = floor(bounds.left()*density), floor(bounds.top()*density)
    right, bottom = ceil(bounds.right()*density), ceil(bounds.bottom()*density)
    image = QImage(max(1, right-left), max(1, bottom-top),
                   QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    target = QRectF(left/density, top/density, image.width()/density, image.height()/density)
    return image, target
