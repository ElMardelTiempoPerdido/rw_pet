"""自定义领口与单色领边：以未摆动衣料的逻辑像素定义，再绑定到布料三角形"""
from functools import lru_cache
from math import ceil, hypot

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QPolygonF, QTransform


def reference_paths(shape):
    """胸部质点为原点，Y 向下；领边宽度和间隔均沿开口法线测量"""
    half, start, depth = shape.neckline_width*.5, -shape.neckline_height, shape.neckline_depth
    bottom = start+depth
    opening = QPainterPath(QPointF(-half, -16.))
    opening.lineTo(-half, start)
    if shape.neckline_shape == 'arc':
        r = shape.neckline_roundness
        opening.cubicTo(-half, start+depth*r, -half*r, bottom, 0., bottom)
        opening.cubicTo(half*r, bottom, half, start+depth*r, half, start)
    elif shape.neckline_tip_radius > 0 and depth > 0:
        # V 底圆弧与两侧相切；大圆角限制在端点以内，不改变开口宽度与起始高度
        length = hypot(half, depth)
        radius = min(shape.neckline_tip_radius, .95*length*half/depth)
        t = radius*depth/(half*length)
        x, y = half*t, bottom-depth*t
        opening.lineTo(-x, y)
        # 对称圆弧的三次贝塞尔近似，深窄 V 也保持平滑切线
        k = 4/3 * radius * depth/(length+half)
        opening.cubicTo(-x+k*half/length, y+k*depth/length,
                        x-k*half/length, y+k*depth/length, x, y)
        opening.lineTo(half, start)
    else:
        opening.lineTo(0., bottom)
        opening.lineTo(half, start)
    opening.lineTo(half, -16.)
    opening.closeSubpath()
    if not shape.neckline_trim_enabled or shape.neckline_trim_width == 0:
        return opening, QPainterPath()

    def expanded(distance):
        if distance == 0:
            return opening
        stroke = QPainterPathStroker()
        stroke.setWidth(distance*2)
        stroke.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        stroke.setMiterLimit(4.)
        return opening.united(stroke.createStroke(opening))

    inner = expanded(shape.neckline_trim_gap)
    outer = expanded(shape.neckline_trim_gap+shape.neckline_trim_width)
    return opening, outer.subtracted(inner)


def _triangles(rest, n):
    result = []
    for y in range(n-1):
        for x in range(n-1):
            i, j = y*n+x, (y+1)*n+x
            for indices in ((i, i+1, j+1), (i, j+1, j)):
                a, b, c = ((rest[k][0], -rest[k][1]) for k in indices)
                det = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
                result.append((indices, a, b, c, det))
    return result


def _edge_distance(x, y, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
    return (x-a[0]-dx*t)**2+(y-a[1]-dy*t)**2


def _binding(x, y, triangles):
    nearest, best = None, float('inf')
    for indices, a, b, c, det in triangles:
        wa = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/det
        wb = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/det
        weights = wa, wb, 1-wa-wb
        if min(weights) >= -1e-8:
            return indices, weights
        distance = min(_edge_distance(x, y, a, b), _edge_distance(x, y, b, c),
                       _edge_distance(x, y, c, a))
        if distance < best:
            nearest, best = (indices, weights), distance
    # 袖根上的领端按最近布片外推，最终由衣袍与袖根轮廓裁切
    return nearest


def _shoulder_cap(rest, n, shape):
    """领口宽度内，衣袍上缘以上也属于露肩区，不保留突出的袖根衣料"""
    half = shape.neckline_width*.5
    edge = [(x, -y) for x, y in rest[:n]]

    def height(x):
        i = next((i for i in range(n-1) if x <= edge[i+1][0]), n-2)
        a, b = edge[i:i+2]
        return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])

    cap = QPainterPath(QPointF(-half, -16.))
    cap.lineTo(-half, height(-half))
    for x, y in edge:
        if -half < x < half:
            cap.lineTo(x, y)
    cap.lineTo(half, height(half))
    cap.lineTo(half, -16.)
    cap.closeSubpath()
    return cap


@lru_cache(maxsize=32)
def _bound_paths(rest, n, shape):
    triangles = _triangles(rest, n)
    result = []
    for path in (*reference_paths(shape), _shoulder_cap(rest, n, shape)):
        polygons = []
        # 细分曲线和直线，跨越网格时仍跟随局部褶皱；只在配置变化时计算绑定
        for polygon in path.toSubpathPolygons(QTransform.fromScale(4., 4.)):
            vertices = [(p.x()/4, p.y()/4) for p in polygon]
            bindings = []
            for a, b in zip(vertices, vertices[1:]+vertices[:1]):
                steps = max(1, ceil(hypot(b[0]-a[0], b[1]-a[1])/.5))
                for step in range(steps):
                    t = step/steps
                    bindings.append(_binding(a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t, triangles))
            polygons.append(tuple(bindings))
        result.append(tuple(polygons))
    return tuple(result)


def _deform_path(cloth, polygons):
    path = QPainterPath()
    for bindings in polygons:
        vertices = []
        for indices, weights in bindings:
            a, b, c = cloth[indices[0]], cloth[indices[1]], cloth[indices[2]]
            wa, wb, wc = weights
            vertices.append(QPointF(a.x*wa+b.x*wb+c.x*wc, a.y*wa+b.y*wb+c.y*wc))
        path.addPolygon(QPolygonF(vertices))
        path.closeSubpath()
    return path


def neckline_paths(cloth, rest, n, shape):
    return tuple(_deform_path(cloth, polygons) for polygons in _bound_paths(tuple(rest), n, shape)[:2])


def sleeve_neckline_path(cloth, rest, n, shape, opening):
    """保留原有领口参数，只补齐袖根在衣袍上缘以上的裁剪范围"""
    result = QPainterPath(opening)
    result.addPath(_deform_path(cloth, _bound_paths(tuple(rest), n, shape)[2]))
    # 同向子路径重叠仍填充，避免领口与上缘相切时布尔并集丢失轮廓
    result.setFillRule(Qt.FillRule.WindingFill)
    return result
