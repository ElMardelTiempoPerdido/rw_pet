"""Prince 触手外观预览绘制；主体渐变、囊肿、独立亮芯分层"""
from bisect import bisect_left, bisect_right
from functools import lru_cache
from math import atan2, ceil, degrees

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPolygonF

from ..prince_tentacles import make_path, stop_interval


TUBE_SPACING = 4.  # 平缓处最多每 4 逻辑像素一片，配置转折点始终保留
TUBE_ERROR = .12  # 弯曲中心线相对粗网格弦线的允许误差，逻辑像素
TUBE_SUBDIVISIONS = 8  # 急弯最多细分至约 0.5 逻辑像素，与原绘制精度相当


@lru_cache(maxsize=256)
def paint_color(value):
    return QColor(value)


@lru_cache(maxsize=4096)
def sampled_color(colors, s):
    a, b, t = stop_interval(colors, s)
    a, b = paint_color(a), paint_color(b)
    return QColor.fromRgbF(a.redF()+(b.redF()-a.redF())*t,
                          a.greenF()+(b.greenF()-a.greenF())*t,
                          a.blueF()+(b.blueF()-a.blueF())*t)


def color_at(tentacle, s):
    return sampled_color(tentacle.colors, s)


def point(p):
    return QPointF(p.x, p.y)


@lru_cache(maxsize=32)
def tube_profile(widths, colors, count):
    """只缓存归一化位置、半宽和颜色；配置值改变即使用新键，缓存不持有运动路径"""
    boundaries = sorted({i/count for i in range(count+1)}
                        | {s for s, _ in widths} | {s for s, _ in colors})
    fractions = [a+(b-a)*i/TUBE_SUBDIVISIONS
                 for a, b in zip(boundaries, boundaries[1:]) for i in range(TUBE_SUBDIVISIONS)]
    fractions.append(1.)
    result = []
    for s in fractions:
        a, b, t = stop_interval(widths, s)
        result.append((s, (a+(b-a)*t)/2, sampled_color(colors, s)))
    return tuple(result)


def tube_stations(tentacle, path):
    """平缓段合并，急弯自适应细分；检查区间内所有折点，避免漏掉 S 形弯折"""
    # 分段数按 8 档量化，轻微长度变化仍复用同一份静态配置采样
    count = max(8, ceil(path.length/(TUBE_SPACING*8))*8)
    profile = tube_profile(tentacle.widths, tentacle.colors, count)

    def sample(index):
        s, radius, color = profile[index]
        center, tangent = path.sample(s)
        return index, center, -tangent.y*radius, tangent.x*radius, color

    def needs_split(a, b):
        start, end = profile[a[0]][0]*path.length, profile[b[0]][0]*path.length
        if end-start < 1e-9:
            return False
        ax, ay = a[1].x, a[1].y
        dx, dy = b[1].x-ax, b[1].y-ay
        for i in range(bisect_right(path.distances, start), bisect_left(path.distances, end)):
            t = (path.distances[i]-start)/(end-start)
            p = path.points[i]
            ex, ey = p.x-ax-dx*t, p.y-ay-dy*t
            if ex*ex+ey*ey > TUBE_ERROR*TUBE_ERROR:
                return True
        return False

    stations = [sample(0)]

    # 显式小栈避免递归闭包自引用，让本帧的路径和几何及时释放
    pending = []
    for i in range(TUBE_SUBDIVISIONS, len(profile), TUBE_SUBDIVISIONS):
        pending.append((stations[-1], sample(i)))
        while pending:
            a, b = pending.pop()
            if b[0]-a[0] > 1 and needs_split(a, b):
                middle = sample((a[0]+b[0])//2)
                pending.append((middle, b))
                pending.append((a, middle))
            else:
                stations.append(b)
    return stations, profile


def draw_tube(painter, tentacle, path):
    stations, profile = tube_stations(tentacle, path)
    for (_, a, ax, ay, ca), (_, b, bx, by, cb) in zip(stations, stations[1:]):
        if ca == cb:
            painter.setBrush(ca)
        else:
            gradient = QLinearGradient(point(a), point(b))
            gradient.setColorAt(0., ca)
            gradient.setColorAt(1., cb)
            painter.setBrush(gradient)
        painter.drawPolygon(QPolygonF([QPointF(a.x-ax, a.y-ay), QPointF(a.x+ax, a.y+ay),
                                       QPointF(b.x+bx, b.y+by), QPointF(b.x-bx, b.y-by)]))
    # 圆端封口，保持与囊肿连接时没有方形尖角
    for index in (0, -1):
        _, center, _, _, color = stations[index]
        radius = profile[stations[index][0]][1]
        painter.setBrush(color)
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
        painter.setBrush(paint_color(bump.color) if bump.color else fallback_color)
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
                draw_bump(painter, path, core, paint_color(tentacle.core_color))
    finally:
        painter.restore()
