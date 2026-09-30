"""40 Hz 监视者模型：固定根部、单个头部质点和短触须；坐标向下为正。"""
from dataclasses import dataclass, replace
from enum import Enum
from math import cos, exp, isfinite, pi, sin, sqrt
from random import Random

from ..shared.geometry import Bounds, Vec2
from .config import OverseerConfig


def clamp(value, low, high):
    return max(low, min(high, value))


def dot(a, b):
    return a.x*b.x+a.y*b.y


def unit(vector, fallback=Vec2()):
    length = vector.length()
    return vector*(1/length) if length > 1e-8 else fallback


def limited(vector, length):
    return vector*min(1., length/max(vector.length(), 1e-8))


def perpendicular(vector):
    return Vec2(-vector.y, vector.x)


class Edge(str, Enum):
    TOP = 'top'
    RIGHT = 'right'
    BOTTOM = 'bottom'
    LEFT = 'left'


class State(str, Enum):
    HIDDEN = 'hidden'
    EMERGING = 'emerging'
    WATCHING = 'watching'
    WITHDRAWING = 'withdrawing'


@dataclass(frozen=True, slots=True)
class Anchor:
    edge: Edge = Edge.BOTTOM
    fraction: float = .35

    def __post_init__(self):
        object.__setattr__(self, 'edge', Edge(self.edge))
        if isinstance(self.fraction, bool) or not isfinite(self.fraction) or not 0 <= self.fraction <= 1:
            raise ValueError('附着位置必须在 0～1 之间')


@dataclass(slots=True)
class Point:
    position: Vec2
    previous: Vec2
    velocity: Vec2 = Vec2()

    @classmethod
    def at(cls, position):
        return cls(position, position)

    def sample(self, alpha):
        return self.previous.lerp(self.position, alpha)


class Overseer:
    TICK_RATE = 40
    FILAMENT_COUNT = 4
    FILAMENT_POINTS = 5
    HEAD_RADIUS = 5.

    def __init__(self, bounds=Bounds(0, 0, 960, 600), config=OverseerConfig(), seed=947):
        self.config, self.seed = config, seed
        self.active = False
        self.revision = 0
        self.place(bounds, Anchor())

    @property
    def reach(self):
        return 50*self.config.size

    @property
    def visible(self):
        # 收缩到零的最后一个插值帧仍需绘制；隐藏的事件仍可监测鼠标并再次探出。
        return self.active and max(self.extended, self.last_extended) > 0

    def extension(self, alpha=1.):
        return self.last_extended+(self.extended-self.last_extended)*clamp(alpha, 0., 1.)

    def segment_extension(self, fraction, alpha=1.):
        # 此处 fraction 为根 -> 头，原版 ExtensionOfSegment 的 f 为头 -> 根。
        return self.extension(alpha)**(4-3.9*fraction)

    @property
    def filament_length(self):
        # 原版 conRad = length / 节点数，再减半；可见链包含 节点数-1 个连接段。
        # 保留相同总静止长度，以固定五节点采样；size=0.6 时为 22.5。
        length = 55+(self.config.size-.5)*50
        original_points = int(length/15)
        return length*(original_points-1)/(2*original_points)

    def place(self, bounds, anchor):
        if not all(isfinite(v) for v in (bounds.left, bounds.top, bounds.right, bounds.bottom)) or min(bounds.right-bounds.left, bounds.bottom-bounds.top) < 140:
            raise ValueError('监视者预览区域每边至少需要 140 逻辑单位')
        self.bounds, self.anchor = bounds, anchor
        edge = anchor.edge
        self.normal = {Edge.TOP: Vec2(0, 1), Edge.RIGHT: Vec2(-1, 0),
                       Edge.BOTTOM: Vec2(0, -1), Edge.LEFT: Vec2(1, 0)}[edge]
        self.tangent = perpendicular(self.normal)
        margin = self.reach+self.filament_length+12
        width, height = bounds.right-bounds.left, bounds.bottom-bounds.top
        margin_x, margin_y = min(margin, width*.45), min(margin, height*.45)
        x = bounds.left+clamp(width*anchor.fraction, margin_x, width-margin_x)
        y = bounds.top+clamp(height*anchor.fraction, margin_y, height-margin_y)
        self.root = {Edge.TOP: Vec2(x, bounds.top), Edge.RIGHT: Vec2(bounds.right, y),
                     Edge.BOTTOM: Vec2(x, bounds.bottom), Edge.LEFT: Vec2(bounds.left, y)}[edge]
        self.hover = self.root+self.normal*(30*self.config.size)
        self.head = Point.at(self.hover)
        self.extended = self.last_extended = self.extension_velocity = 0.
        self.state = State.HIDDEN
        self.wants_out = True
        self.scared = False
        self.safe_time = 0.
        self.threat_distance = None
        self.random = Random(self.seed)
        self.time = self.wander_wait = 0.
        self.offset = self.offset_goal = Vec2()
        self.idle_target = Vec2(0, 180)
        self.look_at = self.previous_look = self.root+self.normal*180
        self.target = None
        base = self.filament_base(1.)
        tips = self._filament_tips()
        self.filaments = [[Point.at(base.lerp(tip, i/(self.FILAMENT_POINTS-1)))
                           for i in range(self.FILAMENT_POINTS)] for tip in tips]
        self.revision += 1

    def show(self, bounds=None, anchor=None):
        self.place(bounds or self.bounds, anchor or self.anchor)
        self.active = True

    def clear(self):
        self.active = False
        self.extended = self.last_extended = self.extension_velocity = 0.
        self.state = State.HIDDEN
        self.scared = False
        self.safe_time = 0.
        self.threat_distance = None
        self.target = None
        self.revision += 1

    def request_emerge(self):
        """保留根部、姿态和伸缩速度；手动探出也不能绕过近距离避让。"""
        self.wants_out = True

    def request_withdraw(self):
        self.wants_out = False

    def set_color(self, color):
        self.config = replace(self.config, color=color)
        self.revision += 1

    def _step_extension(self, threat, puppet):
        self.last_extended = self.extended
        self.threat_distance = None if threat is None else (threat-self.root).length()
        c, dt = self.config, 1/self.TICK_RATE
        puppet_distance = None if puppet is None else (puppet-self.root).length()
        near = ((self.threat_distance is not None and self.threat_distance <= c.withdraw_distance)
                or (puppet_distance is not None and puppet_distance <= c.puppet_withdraw_distance))
        safe = ((self.threat_distance is None or self.threat_distance >= c.reemerge_distance)
                and (puppet_distance is None or puppet_distance >= c.puppet_reemerge_distance))
        if near:
            self.scared = True
            self.safe_time = 0.
        elif self.scared:
            if safe:
                self.safe_time += dt
                if self.safe_time+1e-9 >= c.safe_delay:
                    self.scared = False
            else:
                self.safe_time = 0.
        goal = 1. if self.wants_out and not self.scared else 0.
        # 临界阻尼的解析步进：改变方向时保留进度和速度，不重置动画。
        omega = 6/max(dt, c.emerge_seconds if goal else c.withdraw_seconds)
        delta = self.extended-goal
        carry = self.extension_velocity+omega*delta
        decay = exp(-omega*dt)
        value = goal+(delta+carry*dt)*decay
        self.extension_velocity = (self.extension_velocity-omega*carry*dt)*decay
        self.extended = clamp(value, 0., 1.)
        if value != self.extended:
            # 中途反向仍可能因惯性碰到原方向的端点；在该端点停下，不能跳到新目标。
            self.extension_velocity = 0.
        if abs(self.extended-goal) < .0001 and abs(self.extension_velocity) < .002:
            self.extended = goal
            self.extension_velocity = 0.
        if goal:
            self.state = State.WATCHING if self.extended == 1 else State.EMERGING
        else:
            self.state = State.HIDDEN if self.extended == 0 else State.WITHDRAWING

    def local_vector(self, value):
        return self.tangent*value.x+self.normal*value.y

    def gaze(self, alpha=1.):
        delta = self.previous_look.lerp(self.look_at, alpha)-self.head.sample(alpha)
        distance = delta.length()
        angle = clamp(distance/600, 0., 1.)*pi/2
        # 原版朝向从屏幕平面转向镜头轴；距离为零时平面分量连续归零，避免翻面。
        extension = self.extension(alpha)
        return unit(delta)*(sin(angle)*extension), cos(angle)*extension

    def stem(self, fraction, alpha=1.):
        extension = self.extension(alpha)
        buried_head = self.root-self.normal*(12*self.config.size)
        # 原版探出时把物理头重置到墙内。这里用连续绘制位置替代重置，允许中途反向。
        head = buried_head.lerp(self.head.sample(alpha), extension)
        gaze, _ = self.gaze(alpha)
        a = self.root+self.normal*(max(40*self.config.size, (head-self.root).length()*.85)*extension)
        b = head-gaze*(15*self.config.size*extension)
        t, u = fraction, 1-fraction
        curve = self.root*(u**3)+a*(3*u*u*t)+b*(3*u*t*t)+head*(t**3)
        wall = self.root.lerp(buried_head, fraction)
        return wall.lerp(curve, self.segment_extension(fraction, alpha))

    def eye_position(self, alpha=1.):
        head = self.stem(1., alpha)
        return head+unit(self.stem(.999, alpha)-head)*(5*self.config.size*(1-self.extension(alpha)))

    def filament_base(self, alpha=1.):
        return self.stem(.5+(self.config.size-.5)*.6, alpha)

    def _filament_tips(self):
        gaze, depth = self.gaze()
        spread = (20+5*sin(self.time*.7))*self.config.size
        phase = .32*sin(self.time*.43)
        base = self.filament_base()
        return [base.lerp(self.head.position+self.tangent*(cos(i*pi/2+phase)*spread)
                +self.normal*(sin(i*pi/2+phase)*spread*depth+3*self.config.size)
                -gaze*(8*self.config.size), self.extended) for i in range(self.FILAMENT_COUNT)]

    def step(self, target=None, *, threat=None, puppet=None):
        if not self.active:
            return
        for value in (target, threat, puppet):
            if value is not None and not (isfinite(value.x) and isfinite(value.y)):
                raise ValueError('观察目标和避让位置必须是有限坐标')
        self.target = target
        previous = (self.state, self.extended, self.last_extended)
        self._step_extension(threat, puppet)
        if self.extended == self.last_extended == 0:
            if previous != (self.state, self.extended, self.last_extended):
                self.revision += 1
            return  # 藏在墙内时只检查距离与等待时间，不推进外观和随机数。
        self.time += 1/self.TICK_RATE
        self.wander_wait -= 1/self.TICK_RATE
        if self.wander_wait <= 0:
            self.wander_wait = self.random.uniform(1., 3.)
            self.offset_goal = Vec2(self.random.uniform(-3, 3), self.random.uniform(-2, 2))
            self.idle_target = Vec2(self.random.uniform(-140, 140), self.random.uniform(140, 250))
        self.offset = self.offset.lerp(self.offset_goal, .04)
        desired = target if target is not None else self.root+self.local_vector(self.idle_target)
        desired += self.local_vector(self.offset)
        self.previous_look = self.look_at
        self.look_at = (self.look_at+limited(desired-self.look_at, 60.)).lerp(desired, .02)

        head = self.head
        head.previous = head.position
        delta = self.look_at-head.position
        force = (-.8+1.6*clamp((delta.length()-30)/120, 0., 1.))*self.config.size
        head.velocity = limited(head.velocity*.8+(self.hover-head.position)*.07+unit(delta)*force, 3*self.config.size)
        proposed = head.position+head.velocity
        relative = proposed-self.root
        inward = clamp(dot(relative, self.normal), self.HEAD_RADIUS+1, self.reach)
        lateral_limit = sqrt(max(0., self.reach**2-inward**2))
        lateral = clamp(dot(relative, self.tangent), -lateral_limit, lateral_limit)
        head.position = self.root+self.normal*inward+self.tangent*lateral
        if head.position != proposed:
            head.velocity = head.position-head.previous
        self._step_filaments()
        self.revision += 1

    def _step_filaments(self):
        base = self.filament_base()
        segment_length = self.filament_length*self.extended/(self.FILAMENT_POINTS-1)
        # 收拢过程中允许节点退到墙内；绘制仍由边框裁剪。
        inset = 1-(1-self.extended)*self.reach
        safe = Bounds(self.bounds.left+inset, self.bounds.top+inset,
                      self.bounds.right-inset, self.bounds.bottom-inset)
        # 按本帧长度变化收拢，避免反复乘 extended 压短整条链、再由约束猛然撑开。
        shrink = min(1., self.extended/self.last_extended) if self.last_extended > 0 else 1.
        for index, (strand, tip) in enumerate(zip(self.filaments, self._filament_tips())):
            # 仅在重合点初次展开时使用局部方向，避免归一化零向量后无法撑开。
            radial = self.tangent*cos(index*pi/2)+self.normal*sin(index*pi/2)
            unfurl = unit(tip-base, radial)
            for i, point in enumerate(strand):
                point.previous = point.position
                if i == 0:
                    point.position = base
                    continue
                fraction = i/(len(strand)-1)
                # 原版用 sin(pi*t) 弱牵引中段；末端不追赶目标点，保留自由摆动。
                steering = (tip-point.position)*(.025*sin(fraction*pi)*self.extended)
                # 根部的方向偏好逐段减弱，不把整条触须强行排成一条目标曲线。
                steering += unfurl*(.12*(1-fraction)*self.extended)
                if i > 1:
                    # 轻微抵抗折叠，参考 Mycelium 对隔一个节点的排斥。
                    steering += unit(point.position-strand[i-2].previous, unfurl)*(.2*self.extended)
                point.velocity = limited(point.velocity*(.9*self.extended)+steering, 2.5)
                point.position = safe.clamp((point.position+point.velocity).lerp(base, 1-shrink))
            for iteration in range(4):
                strand[0].position = base
                order = range(len(strand)-1) if iteration % 2 == 0 else range(len(strand)-2, -1, -1)
                for i in order:
                    a, b = strand[i], strand[i+1]
                    delta = b.position-a.position
                    # 双向长度约束：拉长时收紧，压短时撑开；extended 决定当前静止长度。
                    correction = unit(delta, unfurl)*(delta.length()-segment_length)
                    if a is strand[0]:
                        b.position = b.position-correction
                    else:
                        a.position = safe.clamp(a.position+correction*.5)
                        b.position = safe.clamp(b.position-correction*.5)
            # 根部快速移动后，有限次松弛仍可能留下拉伸；从固定端向外收紧残余。
            for a, b in zip(strand, strand[1:]):
                delta = b.position-a.position
                if delta.length() > segment_length:
                    b.position = safe.clamp(a.position+unit(delta)*segment_length)
            for point in strand:
                point.velocity = point.position-point.previous

    def visual_bounds(self, alpha=1.):
        points = [self.stem(i/10, alpha) for i in range(11)]
        points += [point.sample(alpha) for strand in self.filaments for point in strand]
        pad = 12.
        return Bounds(min(p.x for p in points)-pad, min(p.y for p in points)-pad,
                      max(p.x for p in points)+pad, max(p.y for p in points)+pad)
