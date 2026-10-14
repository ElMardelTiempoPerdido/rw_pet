"""自定义袖根：隐藏截面保留搭接，可见上缘沿胸肩切线接入袖子"""
from functools import lru_cache
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform

from ...shared.geometry import Vec2
from .appearance import normalized, perpendicular

ROOT_OVERLAP = 1.  # 沿肩部横轴保留一逻辑像素的覆盖，避免旋转栅格化时露缝


def attach_sleeve_root(edges, upper, direction, sign, torso, shape):
    # 在胸部局部坐标内检查，避免桌面坐标和窗口平移影响接缝
    body = QTransform.fromTranslate(-upper.x, -upper.y).map(torso)
    outward = perpendicular(direction)*sign
    a, b = (p-upper for p in edges[0])
    probes = (a, a.lerp(b, .5), b)

    def covered(pull):
        offset = outward*(ROOT_OVERLAP-pull)
        return all(body.contains(QPointF(p.x+offset.x, p.y+offset.y)) for p in probes)

    if not covered(0.):
        center = a.lerp(b, .5)
        low, high = 0., max(0., center.x*outward.x+center.y*outward.y)
        if covered(high):
            for _ in range(12):
                middle = (low+high)*.5
                if covered(middle):
                    high = middle
                else:
                    low = middle
            offset = outward*high
            edges = [(edges[0][0]-offset, edges[0][1]-offset), *edges[1:]]
        else:
            # 扁胸肩配宽袖时，只收短躯干内的隐藏端，不把袖根顶出胸肩
            cap = []
            for p in (a, b):
                q = p+outward*ROOT_OVERLAP
                if body.contains(QPointF(q.x, q.y)):
                    cap.append(upper+p)
                    continue
                low, high = 0., 1.
                for _ in range(16):
                    t = (low+high)*.5
                    q = p*t+outward*ROOT_OVERLAP
                    if body.contains(QPointF(q.x, q.y)):
                        low = t
                    else:
                        high = t
                cap.append(upper+p*low)
            edges = [tuple(cap), *edges[1:]]
    return _smooth_shoulder(edges, upper, direction, outward, body, shape)


def _chest_arc(width, height, t):
    """与 torso_path 相同的四分之一椭圆三次曲线，返回位置与向外的切向"""
    k = .5522847498307936
    a, b, c, d = Vec2(0, height), Vec2(width*k, height), Vec2(width, height*k), Vec2(width, 0)
    u = 1-t
    return (a*(u*u*u)+b*(3*u*u*t)+c*(3*u*t*t)+d*(t*t*t),
            (b-a)*(3*u*u)+(c-b)*(6*u*t)+(d-c)*(3*t*t))


@lru_cache(maxsize=128)
def _attachment_point(width, height, sleeve_width):
    # 接入位置由胸肩与袖宽决定，避免手臂运动中多个轮廓交点互换导致跳变
    root_height = min(height*.85, sleeve_width*.5)
    low, high = 0., 1.
    for _ in range(16):
        t = (low+high)*.5
        if _chest_arc(width, height, t)[0].y > root_height:
            low = t
        else:
            high = t
    return _chest_arc(width, height, max(0., (low+high)*.5-.22))


def _bezier(a, b, c, d, t):
    u = 1-t
    return a*(u*u*u)+b*(3*u*u*t)+c*(3*u*t*t)+d*(t*t*t)


def _upper_shoulder(start, tangent, end, end_tangent, upper, direction, outward, shape):
    """先横向铺开上肩，再圆滑转向袖身；抬臂时连续退回原有轮廓"""
    start_local = start-upper
    start_x = start_local.x*outward.x+start_local.y*outward.y
    start_y = start_local.x*direction.x+start_local.y*direction.y
    down = (start-end).x*direction.x+(start-end).y*direction.y
    hanging = max(0., min(1., down/shape.chest_height))
    hanging = hanging*hanging*(3-2*hanging)
    reach = (end-start).x*outward.x+(end-start).y*outward.y
    # 袖子收进胸前时提前减弱方肩，避免临近轮廓边界时才集中收回
    spread = max(0., min(1., reach/4))
    hanging *= spread*spread*(3-2*spread)
    # 默认肩宽及以下保留圆滑肩线，加宽时才逐渐接近高位方肩
    broadness = max(0., min(1., (shape.shoulder_width-8.)/10.))
    hanging *= broadness*broadness*(3-2*broadness)
    # 肩宽作用于上肩转折，而非只扩大胸部高度的袖子鼓起部分
    corner_x = max(start_x+.5, shape.shoulder_width*.5+shape.sleeve_root_width*.12)
    corner = upper+outward*corner_x+direction*(start_y-.5)
    corner_tangent = outward
    slope = -(tangent.x*direction.x+tangent.y*direction.y)
    first_span = min((corner-start).length()/3, .5/max(.01, slope))
    last_span = min(1.5, (end-corner).length()/3)
    return ((start, start+tangent*first_span, corner-corner_tangent*first_span, corner),
            (corner, corner+corner_tangent*last_span, end-end_tangent*last_span, end), hanging)


def _smooth_shoulder(edges, upper, direction, outward, body, shape):
    outer = [p-upper for _, p in edges]
    end_index, steps = 8, 14
    samples = []
    for i in range(steps+1):
        index = 1+(end_index-1)*i/steps
        j = min(end_index-1, int(index))
        samples.append(tuple(edges[j][side].lerp(edges[j+1][side], index-j) for side in (0, 1)))
    original = [edges[0], *samples, *edges[end_index+1:]]

    def inside(p):
        return body.contains(QPointF(p.x, p.y))

    # 手臂收回胸前时，近端袖子会完全进入躯干；修形应连续退回原轮廓，
    # 不能在有无交点之间突然切换，也不能将交叉到另一侧的手接到错误肩部
    weight = 0.
    for p in outer[1:end_index+1]:
        if p.x*outward.x+p.y*outward.y <= 0 or inside(p):
            continue
        inward = normalized(p)*2
        if not inside(p-inward):
            weight = 1.
            break
        low, high = 0., 1.
        for _ in range(12):
            t = (low+high)*.5
            if inside(p-inward*t):
                high = t
            else:
                low = t
        weight = max(weight, high)
    if weight == 0:
        return original
    weight = weight*weight*(3-2*weight)

    # 沿胸肩向内退一小段再起弧，袖口四个截面完全保留
    start, tangent = _attachment_point(shape.chest_width*.5, shape.chest_height, shape.sleeve_root_width)
    start = upper+outward*start.x+direction*start.y
    tangent = normalized(outward*tangent.x+direction*tangent.y)
    # 固定接回同一截面，防止交点跨过网格顶点时突然改接另一段
    end = edges[end_index][1]
    end_tangent = normalized(edges[end_index+1][1]-end, outward)
    span = (end-start).length()/3
    control_a, control_b = start+tangent*span, end-end_tangent*span
    first, last, hanging = _upper_shoulder(start, tangent, end, end_tangent,
                                          upper, direction, outward, shape)
    result = [edges[0]]
    for i, (inner, old_outer) in enumerate(samples):
        t = i/steps
        p = _bezier(start, control_a, control_b, end, t)
        # 接入胸肩处多保留一些采样，避免较平的肩线在第一段折成直线
        shoulder = _bezier(*first, (t*2)**1.5) if t <= .5 else _bezier(*last, (t-.5)*2)
        p = p.lerp(shoulder, hanging)
        result.append((inner, old_outer.lerp(p, weight)))
    return result+edges[end_index+1:]
