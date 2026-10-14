"""自定义内搭与高领的局部轮廓，绘制和附加套装裁剪共用"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QPolygonF, QTransform

from ..scene import unit
from .appearance import perpendicular

COLLAR_BASE_RISE = 3.  # 胸部质点沿身体轴向上的平领口位置


def polygon_path(points):
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(p.x, p.y) for p in points]))
    path.closeSubpath()
    return path


def inner_robe_clip(upper, direction):
    """跟随胸肩的平领口截面，绘制时直接裁切原始躯干曲线"""
    side = perpendicular(direction)
    base = upper+direction*COLLAR_BASE_RISE
    return polygon_path((base-side*40, base+side*40,
                         base+side*40-direction*80, base-side*40-direction*80))


def inner_collar_path(upper, direction, head, shape):
    if not shape.inner_robe_enabled or not shape.inner_collar_enabled or shape.inner_collar_height <= 0:
        return QPainterPath()
    side = perpendicular(direction)
    base = upper+direction*COLLAR_BASE_RISE
    neck = unit(head-upper, direction)
    top = base+neck*shape.inner_collar_height
    top_side = perpendicular(neck)*(.5*shape.inner_collar_top_width)
    bottom_side = side*(.5*shape.inner_collar_bottom_width)
    # 下口跟随胸肩，上口跟随颈轴；绕向与躯干一致，蒙版重叠处不会相消
    return polygon_path((base-bottom_side, top-top_side, top+top_side, base+bottom_side))


def inner_robe_path(torso, upper, direction, head, shape):
    """围裙用的衣料覆盖范围；相接的内搭与高领不做布尔并集"""
    if not shape.inner_robe_enabled:
        return QPainterPath()
    # 在胸肩局部坐标内求截面，减少屏幕位置对边界计算精度的影响
    local = QTransform.fromTranslate(-upper.x, -upper.y)
    origin = upper-upper
    cloth = local.map(torso).intersected(inner_robe_clip(origin, direction))
    # united 在两条领口边恰好重合时可能丢失整个躯干子路径
    # 保留两个独立子路径，用同向非零绕组填充其覆盖范围
    cloth.addPath(inner_collar_path(origin, direction, head-upper, shape))
    cloth.setFillRule(Qt.FillRule.WindingFill)
    return QTransform.fromTranslate(upper.x, upper.y).map(cloth)
