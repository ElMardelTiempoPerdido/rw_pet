"""斗篷的姿态轮廓：共用袖子外缘，独立领口，抬手时张开并收短两侧"""
from dataclasses import dataclass
from math import exp

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QTransform

from ...shared.geometry import Vec2
from ..motion.cape import CapeOffsets, arm_lift, dot, side_tensions
from .neckline import reference_paths


def point(v):
    return QPointF(v.x, v.y)


@dataclass(frozen=True)
class CapeGeometry:
    outer: QPainterPath
    opening: QPainterPath
    fill: QPainterPath
    trim: QPainterPath
    hem: QPainterPath
    lowest: Vec2
    lift: tuple[float, float]


def _side_profile(edges, sign, to_local, rest_end_y, tension, shortening):
    # 袖子截面的第二点是上方/外侧边；忽略近端折返，保留肩部最高点
    vertices = [to_local(b) for _, b in edges]
    start = min(range(min(4, len(vertices))), key=lambda i: vertices[i].y)
    width = max(sign*p.x for p in vertices[start:])
    weights = [exp((sign*p.x-width)/.6) for p in vertices[start:]]
    # 宽度相近时平滑选取转折位置，避免最大宽度点换到下一截面时突然跳动
    peak = sum((i+start)*w for i, w in enumerate(weights))/sum(weights)
    widest = min(int(peak), len(vertices)-2)
    profile = vertices[start:widest+1]+[vertices[widest].lerp(vertices[widest+1], peak-widest)]
    if rest_end_y < profile[0].y+.5:
        rest_end_y = profile[0].y+.5
    # 自然下垂时只跟随到侧边终点，较短斗篷不能被袖长强行撑长
    rest = [profile[0]]
    for a, b in zip(profile, profile[1:]):
        if b.y > rest_end_y and b.y > a.y:
            rest.append(a.lerp(b, max(0., (rest_end_y-a.y)/(b.y-a.y))))
            break
        rest.append(b)
    else:
        peak = profile[-1]
        # 最宽处以下的斜率显著减小，留下垂坠的近直线侧边
        drop = max(0., rest_end_y-peak.y)
        rest.append(peak+Vec2(sign*drop*.035, drop))

    # 两侧横向收拢到袖缘，但未抬手一侧保留更多垂坠长度
    def sample(points, t):
        f = t*(len(points)-1)
        i = min(int(f), len(points)-2)
        return points[i].lerp(points[i+1], f-i) if len(points) > 1 else points[0]
    count = max(len(rest), len(profile), 2)
    result = []
    for i in range(count):
        a, b = sample(rest, i/(count-1)), sample(profile, i/(count-1))
        result.append(Vec2(a.x+(b.x-a.x)*tension, a.y+(b.y-a.y)*shortening))
    return tuple(result)


def cape_geometry(upper, direction, hands, sleeves, shape, offsets=CapeOffsets()):
    """只读物理步的插值偏移；肩部和领口固定，下半部叠加受限回摆"""
    cape = shape.cape
    side = Vec2(-direction.y, direction.x)
    down = direction*(-1)
    def local(p):
        v = p-upper
        return Vec2(dot(v, side), dot(v, down))
    lift = arm_lift(upper, direction, hands, shape.shoulder_width)
    tension, shortening = side_tensions(lift)
    top_y = min(local(b).y for edges in sleeves for _, b in edges[:4])
    rest_bottom = top_y+cape.length
    sag = min(3., cape.length*.14)
    left, right = [_side_profile(edges, sign, local, rest_bottom-sag, tension, shorten)
                   for edges, sign, shorten in zip(sleeves, (-1, 1), shortening)]
    l, r = left[-1], right[-1]
    # 长斗篷收短的绝对距离更大，最低处仍接近自然下垂长度
    bottom = rest_bottom-cape.length*(.07*max(lift)+.04*min(lift))
    bottom = max(bottom, l.y+.5, r.y+.5)
    fraction = .5+.27*(lift[0]-lift[1])
    low = Vec2(l.x+(r.x-l.x)*fraction, bottom)
    left_sag, right_sag = max(.5, (bottom-l.y)*.6), max(.5, (bottom-r.y)*.6)
    # 沿侧边长度渐增形变，肩部不动；手臂撑起时加紧侧边，仅留少量布料弹性
    def bend(profile, offset):
        distances = [0.]
        for a, b in zip(profile, profile[1:]):
            distances.append(distances[-1]+(b-a).length())
        length = max(distances[-1], 1e-9)
        # 垂手时下半片一起回摆，避免只有圆弧中心移动而压平底边
        # 撑起时侧边留在袖缘，自由底弧承担主要滞后
        delta = offsets.bottom*(.8*(1-tension))+offset*(.2*(1-.85*tension))
        return tuple(p+delta*(d/length)**2 for p, d in zip(profile, distances))
    left, right = bend(left, offsets.left), bend(right, offsets.right)
    l, r = left[-1], right[-1]
    low += offsets.bottom
    # 底弧保持单一最低点，强烈回摆也不折回或翻过侧边
    low = Vec2(max(l.x+(r.x-l.x)*.1, min(r.x-(r.x-l.x)*.1, low.x)),
               max(low.y, l.y+left_sag, r.y+right_sag))
    bottom = low.y
    hem = QPainterPath(point(r))
    hem.cubicTo(point(Vec2(r.x, r.y+(bottom-r.y)*.55)),
                point(Vec2(low.x+(r.x-low.x)*.55, bottom)), point(low))
    hem.cubicTo(point(Vec2(low.x+(l.x-low.x)*.55, bottom)),
                point(Vec2(l.x, l.y+(bottom-l.y)*.55)), point(l))
    outer = QPainterPath(point(left[0]))
    outer.quadTo(QPointF(0., min(left[0].y, right[0].y)-.8), point(right[0]))
    for p in right[1:]:
        outer.lineTo(point(p))
    outer.connectPath(hem)
    for p in reversed(left[:-1]):
        outer.lineTo(point(p))
    outer.closeSubpath()
    opening, _ = reference_paths(cape)
    fill = outer.subtracted(opening)
    trim = QPainterPath()
    if cape.hem_trim_enabled and cape.hem_trim_width > 0:
        stroke = QPainterPathStroker()
        # 内外描边都延续到弧形端帽，差集形成等宽圆弧并由斗篷侧边裁断
        # 平头会在底弧原端点处提前截断，内缩后留下与侧边之间的缺口
        stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroke.setWidth(2*(cape.hem_trim_gap+cape.hem_trim_width))
        trim = stroke.createStroke(hem)
        if cape.hem_trim_gap > 0:
            stroke.setWidth(2*cape.hem_trim_gap)
            trim = trim.subtracted(stroke.createStroke(hem))
        trim = trim.intersected(fill)
    transform = QTransform(side.x, side.y, down.x, down.y, upper.x, upper.y)
    return CapeGeometry(*(transform.map(p) for p in (outer, opening, fill, trim, hem)),
                        upper+side*low.x+down*low.y, tuple(lift))


def draw_cape(renderer, painter, scene, alpha, upper, direction):
    shape = scene.config.active_custom_appearance
    if shape is None or not shape.cape.enabled:
        return
    sleeves = tuple(renderer.body_sleeve_edges(scene, alpha, upper, direction, i) for i in range(2))
    geometry = cape_geometry(upper, direction, tuple(h.sample(alpha) for h in scene.appearance.hands),
                             sleeves, shape, scene.appearance.cape_motion.sample(alpha)
                             if scene.appearance.cape_motion is not None else CapeOffsets())
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(shape.cape.color))
    painter.drawPath(geometry.fill)
    painter.setBrush(QColor(shape.cape.hem_trim_color))
    painter.drawPath(geometry.trim)
    painter.restore()
