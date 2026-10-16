"""柔性带的分段 UV 网格与无抗锯齿采样，不推进物理"""
from functools import lru_cache

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPolygonF, QTransform

from ...shared.geometry import Vec2
from ..motion.soft_parts import unit
from .damage import soft_part_bounds
from .raster import local_canvas


def strip_mesh(part, alpha):
    """PNG 上边连接根部，下边连接末端；沿静止段长分配 UV，移动不滑动纹理"""
    points = [p.sample(alpha) for p in part.points]
    vertices, uv = [], []
    distance = 0.
    for i, point in enumerate(points):
        tangent = unit(points[min(i+1, len(points)-1)]-points[max(0, i-1)], part.direction)
        right = Vec2(tangent.y, -tangent.x)*(part.width/2)
        vertices.extend((point-right, point+right))
        if i:
            distance += part.rest[i-1]
        v = distance/part.length
        uv.extend(((0., v), (1., v)))
    return vertices, uv


def shape_contains(config, u, v):
    x = abs(2*u-1)
    if config.kind == 'ellipse':
        return x*x+(2*v-1)**2 <= 1.
    if config.kind == 'triangle':
        return x <= 1-v
    if config.kind == 'trapezoid':
        return x <= 1+(config.tip_width_ratio-1)*v
    if config.kind == 'line':
        # 圆端直线，宽度就是线宽；宽度大于长度时仍保持合法轮廓
        r = min(config.width, config.length)/2
        dx = np.maximum(abs((u-.5)*config.width)-(config.width/2-r), 0.)
        dy = np.maximum(abs((v-.5)*config.length)-(config.length/2-r), 0.)
        return dx*dx+dy*dy <= r*r
    return np.ones_like(u, dtype=bool)


@lru_cache(maxsize=64)
def geometry_texture(kind, width, length, tip_ratio, color, density):
    """几何外形按当前像素密度采样一次，变形时与 PNG 共用原生网格绘制"""
    from ..soft_part_config import SoftPart
    config = SoftPart(kind=kind, width=width, length=length, tip_width_ratio=tip_ratio, color=color)
    w, h = max(1, round(width*density)), max(1, round(length*density))
    v, u = np.mgrid[:h, :w]+.5
    inside = shape_contains(config, u/w, v/h)
    pixels = np.zeros((h, w, 4), dtype=np.uint8)
    pixels[inside] = QColor(color).getRgb()
    return QImage(pixels.data, w, h, pixels.strides[0], QImage.Format.Format_RGBA8888_Premultiplied).copy()


def rasterize_strip(part, alpha, density, texture=None):
    bounds = soft_part_bounds(part, alpha)
    canvas, target = local_canvas(bounds, density)
    vertices, uv = strip_mesh(part, alpha)
    vertices = [Vec2((p.x-target.x())*density, (p.y-target.y())*density) for p in vertices]
    config = part.config
    rect = QRectF(0, 0, 1, 1)
    if texture is None:
        texture = geometry_texture(config.kind, config.width, config.length,
                                   config.tip_width_ratio, config.color, density)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(config.color))
        for index in range(len(part.points)-1):
            start = index*2
            for ids in ((start, start+1, start+3), (start, start+3, start+2)):
                a, b, c = (vertices[i] for i in ids)
                first, second, third = (uv[i] for i in ids)
                du1, dv1 = second[0]-first[0], second[1]-first[1]
                du2, dv2 = third[0]-first[0], third[1]-first[1]
                determinant = du1*dv2-du2*dv1
                x1, y1 = b.x-a.x, b.y-a.y
                x2, y2 = c.x-a.x, c.y-a.y
                if abs(x1*y2-x2*y1) < 1e-9:
                    continue
                xx, yx = (x1*dv2-x2*dv1)/determinant, (y1*dv2-y2*dv1)/determinant
                xy, yy = (x2*du1-x1*du2)/determinant, (y2*du1-y1*du2)/determinant
                transform = QTransform(xx, yx, xy, yy,
                    a.x-xx*first[0]-xy*first[1], a.y-yx*first[0]-yy*first[1])
                clip = QPainterPath()
                clip.addPolygon(QPolygonF([QPointF(p.x, p.y) for p in (a, b, c)]))
                painter.save()
                painter.setClipPath(clip)
                painter.setWorldTransform(transform)
                painter.drawImage(rect, texture)
                painter.restore()
    finally:
        painter.end()
    return canvas, target
