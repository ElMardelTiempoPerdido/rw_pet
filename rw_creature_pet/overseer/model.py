"""40 Hz 监视者模型：固定根部、单个头部质点和短触须；坐标向下为正。"""
from dataclasses import dataclass, replace
from enum import Enum
from math import cos, exp, isfinite, pi, sin, sqrt
from random import Random

from ..shared.geometry import Bounds, Vec2
from .config import APPEARANCE_COLORS, OverseerConfig
from .graphics.lens import ObservationLens
from .graphics.friend.body import FriendBend, NECK_LENGTH, body_centers, body_gaze_follow, head_view_gaze, neck_offset
from .graphics.friend.light import OBSERVATION_DURATION as FRIEND_OBSERVATION_DURATION, light_extent
from .graphics.friend.pixels import FriendLightPixels
from .graphics.friend import filaments as friend_filaments


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
    FILAMENT_POINTS = 5
    FILAMENT_IDLE_FORWARD = .05
    FILAMENT_OBSERVE_FORWARD = .5  # 原版 useDir * t² * 0.5，沿触须向末端增强
    HEAD_RADIUS = 5.

    def __init__(self, bounds=Bounds(0, 0, 960, 600), config=OverseerConfig(), seed=947):
        self.config, self.seed = config, seed
        self.active = False
        self.revision = 0
        self.appearance = 'standard'
        self.friend_light_pixels = None
        self.lens = ObservationLens(config, seed)
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
        if self.appearance == 'friend':
            return max(friend_filaments.lengths(self.config.size))
        # 原版 conRad = length / 节点数，再减半；可见链包含 节点数-1 个连接段。
        # 保留相同总静止长度，以固定五节点采样；size=0.6 时为 22.5。
        length = 55+(self.config.size-.5)*50
        original_points = int(length/15)
        return length*(original_points-1)/(2*original_points)

    @property
    def filament_lengths(self):
        if self.appearance == 'friend':
            return friend_filaments.projected_lengths(self)
        return (self.filament_length,)*self.config.filament_count

    def place(self, bounds, anchor):
        if not all(isfinite(v) for v in (bounds.left, bounds.top, bounds.right, bounds.bottom)) or min(bounds.right-bounds.left, bounds.bottom-bounds.top) < 140:
            raise ValueError('监视者预览区域每边至少需要 140 逻辑单位')
        self.bounds, self.anchor = bounds, anchor
        self.lens.reset(self.config)
        if self.friend_light_pixels is not None:
            self.friend_light_pixels.reset()
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
        self.friend_bend = FriendBend()
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
        self._reset_filaments()
        self.revision += 1

    def _reset_filaments(self):
        base = self.filament_base(1.)
        tips = self._filament_tips()
        self.filaments = [[Point.at(base.lerp(tip, i/(self.FILAMENT_POINTS-1)))
                           for i in range(self.FILAMENT_POINTS)] for tip in tips]

    def show(self, bounds=None, anchor=None):
        self.place(bounds or self.bounds, anchor or self.anchor)
        self.active = True

    def clear(self):
        self.active = False
        self.lens.reset(self.config)
        if self.friend_light_pixels is not None:
            self.friend_light_pixels.reset()
        self.extended = self.last_extended = self.extension_velocity = 0.
        self.state = State.HIDDEN
        self.scared = False
        self.safe_time = 0.
        self.threat_distance = None
        self.target = None
        self.friend_bend = FriendBend()
        self.revision += 1

    def request_emerge(self):
        """保留根部、姿态和伸缩速度；手动探出也不能绕过近距离避让。"""
        self.wants_out = True

    def request_withdraw(self):
        self.wants_out = False

    def set_color(self, color):
        self.config = replace(self.config, color=color)
        self.revision += 1

    def configure(self, config):
        old = self.config
        self.config = config
        if old.size != config.size:
            # 重新计算附着边距和悬停高度；保留当前槽位和事件，活动个体原位重新探出
            self.place(self.bounds, self.anchor)
        elif old.filament_count != config.filament_count and self.appearance == 'standard':
            self._reset_filaments()
        self.revision += 1

    def set_appearance(self, appearance):
        if appearance not in APPEARANCE_COLORS:
            raise ValueError('监视者外观无效')
        if self.appearance != appearance:
            self.appearance = appearance
            self.friend_bend = FriendBend()
            self.friend_light_pixels = FriendLightPixels(self.seed) if appearance == 'friend' else None
            self._reset_filaments()
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

    def body_gaze(self, alpha=1.):
        # 花冠仍使用完整 gaze，身体只接收部分注视影响
        gaze, _ = self.gaze(alpha)
        return gaze*body_gaze_follow() if self.appearance == 'friend' else gaze

    def head_gaze(self, alpha=1.):
        return head_view_gaze(self, alpha) if self.appearance == 'friend' else self.gaze(alpha)

    def stem(self, fraction, alpha=1., *, head_offset=None):
        extension = self.extension(alpha)
        buried_head = self.root-self.normal*(12*self.config.size)
        # 原版探出时把物理头重置到墙内。这里用连续绘制位置替代重置，允许中途反向。
        head = buried_head.lerp(self.head.sample(alpha), extension)
        if head_offset is not None:
            head += head_offset
        gaze = self.body_gaze(alpha)
        handle = max(40*self.config.size, (head-self.root).length()*.85)
        if head_offset is not None:
            # 延长后的颈部会露出原先被头覆盖的曲线，短姿态下避免根侧控制点越过末端
            handle = min(handle, (head-self.root).length()*.9)
        a = self.root+self.normal*(handle*extension)
        b = head-gaze*(15*self.config.size*extension)
        t, u = fraction, 1-fraction
        curve = self.root*(u**3)+a*(3*u*u*t)+b*(3*u*t*t)+head*(t**3)
        wall = self.root.lerp(buried_head, fraction)
        return wall.lerp(curve, self.segment_extension(fraction, alpha))

    def eye_position(self, alpha=1.):
        head = self.stem(1., alpha)
        if self.appearance == 'friend':
            return self.stem(1., alpha, head_offset=neck_offset(self, alpha))
        return head+unit(self.stem(.999, alpha)-head)*(5*self.config.size*(1-self.extension(alpha)))

    @property
    def head_extra_extent(self):
        return NECK_LENGTH*(.75+.25*self.config.size) if self.appearance == 'friend' else 0.

    @property
    def observation_extent(self):
        return light_extent() if self.appearance == 'friend' else self.lens.MAX_EXTENT

    def filament_base(self, alpha=1.):
        if self.appearance == 'friend':
            return friend_filaments.attachment(self, alpha)
        return self.stem(.5+(self.config.size-.5)*.6, alpha)

    def _filament_tips(self):
        if self.appearance == 'friend':
            return friend_filaments.tip_targets(self)
        gaze, depth = self.gaze()
        spread = (20+5*sin(self.time*.7))*self.config.size
        phase = .32*sin(self.time*.43)
        base = self.filament_base()
        count = self.config.filament_count
        return [base.lerp(self.head.position+self.tangent*(cos(i*2*pi/count+phase)*spread)
                +self.normal*(sin(i*2*pi/count+phase)*spread*depth+3*self.config.size)
                -gaze*(8*self.config.size), self.extended) for i in range(count)]

    def step(self, target=None, *, threat=None, puppet=None):
        if not self.active:
            return
        for value in (target, threat, puppet):
            if value is not None and not (isfinite(value.x) and isfinite(value.y)):
                raise ValueError('观察目标和避让位置必须是有限坐标')
        self.target = target
        previous = (self.state, self.extended, self.last_extended)
        self._step_extension(threat, puppet)
        if self.lens.config is not self.config:
            self.lens.configure(self.config)
        self.lens.step(eligible=self.state == State.WATCHING and self.wants_out
                       and not self.scared and target is not None,
                       visible=self.visible, tick_rate=self.TICK_RATE,
                       animate_hologram=self.appearance != 'friend',
                       duration=FRIEND_OBSERVATION_DURATION if self.appearance == 'friend' else None)
        if self.friend_light_pixels is not None:
            self.friend_light_pixels.step(opening=max(self.lens.up, self.lens.previous_up),
                                          visible=self.visible, emitting=self.lens.remaining > 0,
                                          tick_rate=self.TICK_RATE)
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
        if self.appearance == 'friend':
            # 降低末端追随鼠标的位移，不减慢花冠本身的转向或探出、缩回
            force *= body_gaze_follow()
        head.velocity = limited(head.velocity*.8+(self.hover-head.position)*.07+unit(delta)*force, 3*self.config.size)
        proposed = head.position+head.velocity
        relative = proposed-self.root
        inward = clamp(dot(relative, self.normal), self.HEAD_RADIUS+1, self.reach)
        lateral_limit = sqrt(max(0., self.reach**2-inward**2))
        lateral = clamp(dot(relative, self.tangent), -lateral_limit, lateral_limit)
        head.position = self.root+self.normal*inward+self.tangent*lateral
        if head.position != proposed:
            head.velocity = head.position-head.previous
        if self.appearance == 'friend':
            self.friend_bend.step(self)
        self._step_filaments()
        self.revision += 1

    def _step_filaments(self):
        base = self.filament_base()
        lengths = self.filament_lengths
        opening = self.lens.up
        opening = opening*opening*(3-2*opening)
        idle_forward = 0. if self.appearance == 'friend' else self.FILAMENT_IDLE_FORWARD
        # 桌面适配：观察时逐渐增强原版的前向力，平时保留朋友？的 C/S 弧
        # 使用头部的屏幕投影，不归一化；接近正视时自然减弱，不突然倒向一侧
        gaze = self.head_gaze()[0]
        forward = gaze*(idle_forward+(self.FILAMENT_OBSERVE_FORWARD-idle_forward)*opening)
        # 收拢过程中允许节点退到墙内；绘制仍由边框裁剪。
        inset = 1-(1-self.extended)*self.reach
        safe = Bounds(self.bounds.left+inset, self.bounds.top+inset,
                      self.bounds.right-inset, self.bounds.bottom-inset)
        # 按本帧长度变化收拢，避免反复乘 extended 压短整条链、再由约束猛然撑开。
        shrink = min(1., self.extended/self.last_extended) if self.last_extended > 0 else 1.
        for index, (strand, tip) in enumerate(zip(self.filaments, self._filament_tips())):
            segment_length = lengths[index]*self.extended/(len(strand)-1)
            if self.appearance == 'friend':
                # 观察时松开后向姿态引导，避免长须被原有 S 弧一直留在身后
                tip = tip.lerp(base+gaze*(lengths[index]*.8), opening*.85)
            # 仅在重合点初次展开时使用局部方向，避免归一化零向量后无法撑开。
            angle = index*pi/2 if self.appearance == 'friend' else index*2*pi/len(self.filaments)
            radial = self.tangent*cos(angle)+self.normal*sin(angle)
            unfurl = unit(tip-base, radial)
            bends = (friend_filaments.bend_forces(self, index, strand, base, unfurl)
                     if self.appearance == 'friend' else None)
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
                steering += forward*(fraction*fraction)
                if bends is not None:
                    steering += bends[i]*(1-.75*opening)
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
        points = (body_centers(self, alpha) if self.appearance == 'friend'
                  else [self.stem(i/10, alpha) for i in range(11)])
        points += [point.sample(alpha) for strand in self.filaments for point in strand]
        if self.lens.opening(alpha) > 0:
            # 按外观包含观察光束或外围三角片，不能只缓存眼球与触须的矩形
            eye = self.eye_position(alpha)
            radius = self.observation_extent
            points += [eye-Vec2(radius, radius), eye+Vec2(radius, radius)]
        pad = 12.
        return Bounds(min(p.x for p in points)-pad, min(p.y for p in points)-pad,
                      max(p.x for p in points)+pad, max(p.y for p in points)+pad)
