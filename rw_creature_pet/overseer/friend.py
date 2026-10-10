"""朋友？外观的身体轮廓、带惯性的 S 形姿态和固定根部渐变"""
from dataclasses import dataclass
from math import atan2, cos, exp, hypot, radians, sin, tan, pi

from ..shared.geometry import Vec2

ROOT_COLOR = '#8859d6'
ROOT_RADIUS = 0.9
PEAK_RADIUS = 3.6
NECK_RADIUS = 1.3
PEAK_FRACTION = .80  # 按圆盘遮挡之前的可见身体弧长定位
NECK_FRACTION = 1  # 最宽处之后快速收细，余下部分保持细颈
GROWTH_POWER = 2.0  # 越大，根部起始的大半段越细长
NECK_LENGTH = 8.0  # 额外身体的逻辑长度，圆盘和镜片一起前移
NECK_SEGMENTS = 6
DISC_RADIUS = 3.25  # 配合 2x 花瓣贴图中央的开口
HEAD_OCCLUSION_RADIUS = 5.0  # 花冠遮挡身体末段的估计长度，独立于白色圆盘半径
HEAD_GAZE_DISTANCE_FRACTION = .9  # 鼠标横向/纵向跨工作区此比例时，头部达到最大倾角
HEAD_GAZE_NEAR_FRACTION = .2  # 近距离轻仰的过渡点，占工作区宽/高的比例；0 恢复单段曲线
HEAD_GAZE_NEAR_ANGLE = 40.0  # 近距离过渡点的内部倾角
HEAD_GAZE_POWER = 2.0  # 过渡点之后的角度增长曲线，越大中段越缓、远端增长越明显
BODY_GAZE_FOLLOW = .6  # 传给身体位移、颈部和弯身的注视影响，0～1；花冠转向保持完整幅度
BEND_ROOT_AMPLITUDE = 0.5  # 根侧细长段向侧视方向拱出的幅度，逻辑像素
BEND_BODY_AMPLITUDE = 2.0  # 主体反向回弯的幅度，逻辑像素
BEND_RESPONSE_SECONDS = .65  # 弯身接近新目标的时间，越大越迟缓
BEND_SIDE_SOFTNESS = .25  # 侧视响应的柔和程度，越小越容易显出弯曲
BEND_LENGTH_REFERENCE = 35.0  # 完整弯幅所需的出墙长度，短姿态自动减弱

BEND_ROOT_FRACTION = 0.5  # 根侧弯曲在身体生效的范围，剩余部分为主体的弯曲生效范围
ROOT_EXIT_ANGLE = 18.0  # 根段相对起终点连线的额外出墙倾角上限，度


def body_gaze_follow():
    return min(1., max(0., BODY_GAZE_FOLLOW))


def head_tilt_angle(span):
    full = max(1e-6, HEAD_GAZE_DISTANCE_FRACTION)
    near = min(full*.95, max(0., HEAD_GAZE_NEAR_FRACTION))
    angle = radians(min(90., max(0., HEAD_GAZE_NEAR_ANGLE))) if near > 0 else 0.
    if near > 0 and span < near:
        # 先较快出现轻仰，再以零斜率进入中段；距离归零时仍精确回到正面
        progress = max(0., span)/near
        return angle*progress*(2-progress)
    progress = min(1., max(0., (span-near)/(full-near)))
    return angle+(pi/2-angle)*progress**max(1., HEAD_GAZE_POWER)


def head_view_gaze(model, alpha=1.):
    """只改变头部及镜片的倾斜曲线，身体继续使用原有注视响应"""
    delta = model.previous_look.lerp(model.look_at, alpha)-model.eye_position(alpha)
    width = model.bounds.right-model.bounds.left
    height = model.bounds.bottom-model.bounds.top
    # 分别按工作区宽高归一化，斜向取较大跨度，不因两轴相加而提早转满
    span = max(abs(delta.x)/width, abs(delta.y)/height)
    angle = head_tilt_angle(span)
    extension = model.extension(alpha)
    length = delta.length()
    planar = delta*(sin(angle)*extension/length) if length > 1e-8 else Vec2()
    return planar, cos(angle)*extension


@dataclass(slots=True)
class FriendBend:
    side: float = 0.
    previous_side: float = 0.
    velocity: float = 0.

    def step(self, model):
        self.previous_side = self.side
        gaze = model.body_gaze()
        # 以附着边缘为参考，四边共用同一方向规则；伸缩只影响可见弯幅
        lateral = (gaze.x*model.tangent.x+gaze.y*model.tangent.y)/max(model.extended, 1e-8)
        goal = lateral/hypot(lateral, BEND_SIDE_SOFTNESS)
        omega = 6/BEND_RESPONSE_SECONDS
        delta = self.side-goal
        carry = self.velocity+omega*delta
        decay = exp(-omega/model.TICK_RATE)
        self.side = goal+(delta+carry/model.TICK_RATE)*decay
        self.velocity = (self.velocity-omega*carry/model.TICK_RATE)*decay
        if abs(self.side-goal) < 1e-5 and abs(self.velocity) < 1e-4:
            self.side, self.velocity = goal, 0.

    def sample(self, alpha):
        return self.previous_side+(self.side-self.previous_side)*alpha


def smoothstep(value):
    value = min(1., max(0., value))
    return value*value*(3-2*value)


def body_radius(fraction, size):
    if fraction <= PEAK_FRACTION:
        weight = smoothstep(fraction/PEAK_FRACTION)**GROWTH_POWER
        radius = ROOT_RADIUS+(PEAK_RADIUS-ROOT_RADIUS)*weight
    else:
        weight = smoothstep((fraction-PEAK_FRACTION)/(NECK_FRACTION-PEAK_FRACTION))
        radius = PEAK_RADIUS+(NECK_RADIUS-PEAK_RADIUS)*weight
    return radius*(.75+.25*size)


def neck_offset(model, alpha=1.):
    """沿身体和视线的混合方向延长，接近平视时也不会因归一化微小视线而翻面"""
    axis = model.stem(1., alpha)-model.root
    length = axis.length()
    axis = axis*(1/length) if length > 1e-6 else model.normal
    gaze = model.body_gaze(alpha)
    distance = NECK_LENGTH*(.75+.25*model.config.size)*model.extension(alpha)
    return (axis+gaze*.8)*(distance/(1+.8*gaze.length()))


@dataclass(frozen=True, slots=True)
class FriendBodyCurve:
    root: Vec2
    root_control: Vec2
    join: Vec2
    body_control: Vec2
    head_control: Vec2
    head: Vec2
    tangent: Vec2
    split: float
    body_bow: float

    def sample(self, fraction):
        if fraction <= 0:
            return self.root
        if fraction >= 1:
            return self.head
        if fraction <= self.split:
            t = fraction/self.split
            u = 1-t
            # 单段二次曲线没有额外拐点，根部直接顺着弧线离开边缘
            return self.root*(u*u)+self.root_control*(2*u*t)+self.join*(t*t)
        t = (fraction-self.split)/(1-self.split)
        u = 1-t
        point = (self.join*(u**3)+self.body_control*(3*u*u*t)+
                 self.head_control*(3*u*t*t)+self.head*(t**3))
        # 主体反弯的位移和斜率在两端归零，不破坏交界及头颈方向
        return point-self.tangent*(self.body_bow*16*t*t*u*u)


def body_curve(model, alpha):
    count = 24+NECK_SEGMENTS
    offset = neck_offset(model, alpha)
    # 原曲线只提供头颈位置、末端方向和范围分配的参考弧长
    centers = [model.stem(i/count, alpha, head_offset=offset) for i in range(count+1)]
    lengths = [0.]
    for a, b in zip(centers, centers[1:]):
        lengths.append(lengths[-1]+(b-a).length())
    head = centers[-1]
    relative = head-model.root
    inward = relative.x*model.normal.x+relative.y*model.normal.y
    amount = (model.friend_bend.sample(alpha)*model.extension(alpha)**2*
              smoothstep(inward/BEND_LENGTH_REFERENCE))
    split = min(.9, max(.1, BEND_ROOT_FRACTION))
    join_length = lengths[-1]*split
    index = next((i for i in range(1, count+1) if lengths[i] >= join_length), count)
    weight = (join_length-lengths[index-1])/max(lengths[index]-lengths[index-1], 1e-8)
    join = centers[index-1].lerp(centers[index], weight)
    chord = join-model.root
    root_inward = chord.x*model.normal.x+chord.y*model.normal.y
    lateral = chord.x*model.tangent.x+chord.y*model.tangent.y
    root_bow = amount*BEND_ROOT_AMPLITUDE
    if root_inward > 1e-6:
        base_angle = atan2(lateral, root_inward)
        desired_angle = atan2(lateral+4*root_bow, root_inward)
        limit = radians(max(0., min(60., ROOT_EXIT_ANGLE)))
        turn = min(limit, max(-limit, desired_angle-base_angle))
        root_bow = (root_inward*tan(base_angle+turn)-lateral)/4
    else:
        root_bow = 0.
    root_control = model.root.lerp(join, .5)+model.tangent*(2*root_bow)
    # 同时匹配两段关于全身参数的导数，范围改变后交界仍没有折角
    body_control = join+(join-root_control)*(2*(1-split)/(3*split))
    # 保留末端切线的长度一起衰减，视线穿过头部时不能将微小方向放大成甩颈
    end_delta = (head-model.stem(1.-1e-5, alpha, head_offset=offset))*((1-split)/(3e-5))
    limit = (head-join).length()*.4
    head_control = head-end_delta*min(1., limit/max(end_delta.length(), 1e-8))
    return FriendBodyCurve(model.root, root_control, join, body_control,
                           head_control, head, model.tangent, split,
                           amount*BEND_BODY_AMPLITUDE)


def body_centers(model, alpha):
    curve = body_curve(model, alpha)
    count = 24+NECK_SEGMENTS
    return [curve.sample(i/count) for i in range(count+1)]


def body_color(fraction, color):
    from PySide6.QtGui import QColor
    amount = min(1., max(0., fraction/.65))
    amount = amount*amount*(3-2*amount)
    a, b = QColor(ROOT_COLOR), QColor(color)
    return QColor.fromRgbF(*(a.getRgbF()[i]*(1-amount)+b.getRgbF()[i]*amount for i in range(3)))


def draw_body(painter, model, alpha):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPolygonF
    from .model import perpendicular, unit

    centers = body_centers(model, alpha)
    count = len(centers)-1
    lengths = [0.]
    for a, b in zip(centers, centers[1:]):
        lengths.append(lengths[-1]+(b-a).length())
    # 曲线参数不等于沿身体的距离，按弧长定位最宽处和紫色过渡
    fractions = [length/max(lengths[-1], 1e-6) for length in lengths]
    # 为圆盘覆盖的末段预留长度，避免收细的部分全部藏在白色圆盘下面
    visible_length = max(lengths[-1]*.5, lengths[-1]-HEAD_OCCLUSION_RADIUS*model.segment_extension(1., alpha), 1e-6)
    sections = []
    for i, center in enumerate(centers):
        normal = perpendicular(unit(centers[min(count, i+1)]-centers[max(0, i-1)], model.normal))
        fraction = i/count
        wall_radius = 1+sin(fraction*pi)
        full_radius = body_radius(min(1., lengths[i]/visible_length), model.config.size)
        radius = wall_radius+(full_radius-wall_radius)*model.segment_extension(fraction, alpha)
        if i == 0:
            normal, radius = model.tangent, max(1., radius)
        sections.append((center-normal*radius, center+normal*radius))
    painter.setPen(Qt.PenStyle.NoPen)
    for i, ((a, b), (c, d)) in enumerate(zip(sections, sections[1:])):
        painter.setBrush(body_color(fractions[i], model.config.color))
        painter.drawPolygon(QPolygonF([QPointF(p.x, p.y) for p in (a, b, d, c)]))
