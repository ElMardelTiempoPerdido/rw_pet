"""Prince 触手外观预览绘制；主体渐变、囊肿、独立亮芯分层"""
from math import atan2, ceil, degrees

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPolygonF

from ..prince_tentacles import make_path, stop_interval
from ...shared.geometry import Vec2


def color_at(tentacle, s):
    a, b, t = stop_interval(tentacle.colors, s)
    a, b = QColor(a), QColor(b)
    return QColor.fromRgbF(a.redF()+(b.redF()-a.redF())*t,
                          a.greenF()+(b.greenF()-a.greenF())*t,
                          a.blueF()+(b.blueF()-a.blueF())*t)


def point(p):
    return QPointF(p.x, p.y)


def draw_tube(painter, tentacle, path):
    count = max(2, ceil(path.length*2))
    stations = []
    for i in range(count+1):
        s = i/count
        center, tangent = path.sample(s)
        normal = Vec2(-tangent.y, tangent.x)*(tentacle.width_at(s)/2)
        stations.append((center, normal, color_at(tentacle, s)))
    for (a, na, ca), (b, nb, cb) in zip(stations, stations[1:]):
        gradient = QLinearGradient(point(a), point(b))
        gradient.setColorAt(0., ca)
        gradient.setColorAt(1., cb)
        painter.setBrush(gradient)
        painter.drawPolygon(QPolygonF([point(a-na), point(a+na), point(b+nb), point(b-nb)]))
    # 圆端封口，保持与囊肿连接时没有方形尖角
    for s in (0., 1.):
        center, _ = path.sample(s)
        radius = tentacle.width_at(s)/2
        painter.setBrush(color_at(tentacle, s))
        painter.drawEllipse(QRectF(center.x-radius, center.y-radius, radius*2, radius*2))


def draw_bump(painter, path, bump, fallback_color):
    if not bump.enabled:
        return
    center, tangent = path.attachment(bump)
    painter.save()
    try:
        painter.translate(center.x, center.y)
        # width 横跨触手，height 沿触手方向，angle 是在此基础上的顺时针旋转
        painter.rotate(degrees(atan2(tangent.y, tangent.x))+90.+bump.angle)
        painter.setBrush(QColor(bump.color) if bump.color else fallback_color)
        painter.drawEllipse(QRectF(-bump.width/2, -bump.height/2, bump.width, bump.height))
    finally:
        painter.restore()


def draw_tentacles(painter, tentacles, *, paths=None):
    """所有亮芯最后绘制，不要求与某颗深色囊肿配对或同心"""
    paths = [(t, make_path(t)) for t in tentacles if t.enabled] if paths is None else paths
    painter.save()
    try:
        # 也支持帧缓存 PaintCommands，不能从 painter 实例取 Qt 枚举
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        for tentacle, path in paths:
            draw_tube(painter, tentacle, path)
        for tentacle, path in paths:
            for bump in tentacle.bumps:
                draw_bump(painter, path, bump, color_at(tentacle, bump.s))
        for tentacle, path in paths:
            for core in tentacle.cores:
                draw_bump(painter, path, core, QColor(tentacle.core_color))
    finally:
        painter.restore()
