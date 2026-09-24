"""Oracle 场景：滑动底座、边缘曲线漂浮、两质点身体及独立观察。

坐标 y 向下，固定 40 Hz；速度为单位 / tick。没有 Qt 或墙钟依赖。
原版参考 Oracle.cs / OracleGraphics.cs；关节求解和边缘范围为桌面适配。
"""
from dataclasses import dataclass
from enum import Enum
from math import atan2, cos, isfinite, pi, radians, sin
from random import Random

from ..shared.geometry import Bounds, Vec2
from .config import OracleConfig
from .navigation import EdgeRegion, FloatNavigator, RoundedRail
from .appearance import OracleAppearance
from .behavior import OracleBehavior
from .eyes import OracleEyes
from .pearl import PearlState
from .pose import OraclePose


def unit(v: Vec2, fallback=Vec2(0, -1)) -> Vec2:
    length = v.length()
    return v * (1 / length) if length > 1e-9 else fallback


def limited(v: Vec2, length: float) -> Vec2:
    return v * min(1, length / max(v.length(), 1e-9))


def dot(a: Vec2, b: Vec2) -> float:
    return a.x * b.x + a.y * b.y


def finite_point(point: Vec2):
    if not isfinite(point.x) or not isfinite(point.y):
        raise ValueError('坐标必须为有限数值')


class RailSide(str, Enum):
    TOP = 'top'
    RIGHT = 'right'
    BOTTOM = 'bottom'
    LEFT = 'left'


@dataclass(frozen=True, slots=True)
class RailAnchor:
    side: RailSide
    fraction: float


@dataclass(slots=True)
class OracleWorld:
    width: float
    height: float
    edge_fraction: float
    rail_inset: float = 18.0
    body_margin: float = 36.0

    @property
    def inner(self) -> Bounds:
        return Bounds(self.width * self.edge_fraction, self.height * self.edge_fraction,
                      self.width * (1 - self.edge_fraction), self.height * (1 - self.edge_fraction))

    def anchor_position(self, anchor: RailAnchor) -> Vec2:
        pad, f = self.rail_inset, anchor.fraction
        x, y = pad + (self.width - 2 * pad) * f, pad + (self.height - 2 * pad) * f
        return {RailSide.TOP: Vec2(x, pad), RailSide.BOTTOM: Vec2(x, self.height - pad),
                RailSide.LEFT: Vec2(pad, y), RailSide.RIGHT: Vec2(self.width - pad, y)}[anchor.side]

    def normal(self, side: RailSide) -> Vec2:
        return {RailSide.TOP: Vec2(0, 1), RailSide.BOTTOM: Vec2(0, -1),
                RailSide.LEFT: Vec2(1, 0), RailSide.RIGHT: Vec2(-1, 0)}[side]

    def corridor(self, side: RailSide, body=True) -> Bounds:
        pad = self.body_margin if body else self.rail_inset
        inner_pad = self.body_margin if body else 7.0
        box = Bounds(pad, pad, self.width - pad, self.height - pad)
        inner = self.inner
        return {RailSide.TOP: Bounds(box.left, box.top, box.right, inner.top - inner_pad),
                RailSide.BOTTOM: Bounds(box.left, inner.bottom + inner_pad, box.right, box.bottom),
                RailSide.LEFT: Bounds(box.left, box.top, inner.left - inner_pad, box.bottom),
                RailSide.RIGHT: Bounds(inner.right + inner_pad, box.top, box.right, box.bottom)}[side]


@dataclass(slots=True)
class MotionPoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()
    radius: float = 6.0
    mass: float = .5

    @classmethod
    def at(cls, position, radius=6.0):
        return cls(position, position, radius=radius)


@dataclass(slots=True)
class OracleHead(MotionPoint):
    """健康 Oracle 的定长头部连接；积分速度与可见位移分开保存。"""
    drive_velocity: Vec2 = Vec2()
    NECK_BASE_OFFSET = 6.
    CONNECTION_LENGTH = 8.

    def step(self, upper, direction, look):
        self.previous_position = self.position
        predicted = self.position+self.drive_velocity
        anchor = upper.position+direction*self.NECK_BASE_OFFSET
        self.position = anchor+unit(predicted-anchor, direction)*self.CONNECTION_LENGTH
        correction = self.position-predicted
        # GenericBodyPart.Update -> ConnectToPoint(push=True, adapt=.5,
        # exaggerate=.01) -> OracleGraphics 的健康状态受力（breathFac=1）。
        velocity = self.drive_velocity*.995+upper.velocity*.01+correction
        self.drive_velocity = ((velocity-upper.velocity)*.5+upper.velocity
                               + direction+look*.5)
        # 静止时仍有被定长约束抵消的径向驱动力，不能把它当成可见运动。
        self.velocity = self.position-self.previous_position


@dataclass(slots=True)
class OracleBody:
    chunks: list[MotionPoint]
    connection_length: float = 9.0

    @property
    def direction(self):
        return unit(self.chunks[0].position - self.chunks[1].position)


@dataclass(slots=True)
class ArmJoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()


class FixedOracleArm:
    """4 个主关节；前三段允许折叠，末端到上身的连接为固定长度。

    原版 totalLength 是可折叠段的最大跨度，不是四根始终笔直的定长杆。
    这里用阻尼预测 + 距离区间约束，保留上次关节位置和弯折侧。
    """
    def __init__(self, base, tip, normal, corridor, scale):
        self.lengths = tuple(value * scale for value in (300., 150., 90., 30.))
        # 窄活动带中，长机械臂过角时需要更深地折叠，不能强制维持首批的
        # 固定最小跨度（原版也会随邻段夹角改变最小距离）。
        fold_limit = float('inf')
        if isinstance(corridor, EdgeRegion):
            top, right = corridor.boxes[:2]
            fold_limit = .8 * min(top.bottom - top.top, right.right - right.left)
        self.minimum_spans = tuple(min(length / 3, fold_limit) for length in self.lengths[:3])
        self.base = base
        self.normal = normal
        self.corridor = corridor
        tangent = Vec2(normal.y, -normal.x)
        # 只在重置时选择有足够空间的一侧，运行期间不随机翻折。
        candidates = [corridor.clamp(base + tangent * sign * self.lengths[0] * .7
                                     + normal * 25) for sign in (1, -1)]
        self.bend_sign = 1 if (candidates[0] - base).length() >= (candidates[1] - base).length() else -1
        self.tangent = tangent * self.bend_sign
        a = candidates[0 if self.bend_sign == 1 else 1]
        b = corridor.clamp(a.lerp(tip, .65))
        self.joints = [ArmJoint(p, p) for p in (base, a, b, tip)]
        self._solve(tip, iterations=120)
        for joint in self.joints:
            joint.previous_position = joint.position

    @property
    def maximum_reach(self):
        # 给末端姿态与弯曲保留余量。
        return sum(self.lengths[:3]) * .88 - self.lengths[3]

    def _solve(self, tip, iterations=90):
        for iteration in range(iterations):
            self.joints[0].position = self.base
            self.joints[-1].position = tip
            for i, length in enumerate(self.lengths[:3]):
                a, b = self.joints[i], self.joints[i + 1]
                delta = b.position - a.position
                distance = delta.length()
                target = max(self.minimum_spans[i], min(length * .98, distance))
                correction = unit(delta, self.tangent) * (distance - target)
                wa, wb = (0 if i == 0 else 1), (0 if i == 2 else 1)
                a.position = a.position + correction * (wa / (wa + wb))
                b.position = b.position - correction * (wb / (wa + wb))
            for joint in self.joints[1:3]:
                joint.position = self.corridor.clamp(joint.position)
            if isinstance(self.corridor, EdgeRegion):
                for i in range(3):
                    a, b = self.joints[i:i + 2]
                    a.position, b.position = self.corridor.separate_segment(
                        a.position, b.position, fixed_a=i == 0, fixed_b=i == 2)
            safe = (not isinstance(self.corridor, EdgeRegion) or all(
                self.corridor.segment_safe(a.position, b.position) for a, b in zip(self.joints, self.joints[1:])))
            if iteration % 4 == 3 and self.constraint_error < 1e-5 and safe:
                break
        self.joints[0].position = self.base
        self.joints[-1].position = tip

    def step(self, tip, base=None, normal=None):
        for joint in self.joints:
            joint.previous_position = joint.position
        if base is not None:
            self.base = base
            self.normal = normal
            self.tangent = Vec2(normal.y, -normal.x) * self.bend_sign
        # 小幅恢复力防止多解关节持续游走；目标随末端连续变化。
        guide = self.corridor.clamp(self.base + self.tangent * self.lengths[0] * .62
                                   + self.normal * 22)
        for i in (1, 2):
            joint = self.joints[i]
            target = guide if i == 1 else guide.lerp(tip, .7)
            joint.position = joint.position + joint.velocity * .7 + limited(target - joint.position, 20) * .012
        self._solve(tip)
        for joint in self.joints:
            joint.velocity = joint.position - joint.previous_position

    @property
    def constraint_error(self):
        errors = []
        for i, length in enumerate(self.lengths[:3]):
            span = (self.joints[i + 1].position - self.joints[i].position).length()
            errors.append(max(self.minimum_spans[i] - span, span - length * .98, 0))
        return max(errors)


class OracleScene:
    TICK_RATE = 40

    def __init__(self, config=OracleConfig()):
        self.config = config
        self.world = OracleWorld(config.world_width, config.world_height, config.edge_fraction,
                                 body_margin=max(36., 18 + 30 * config.arm_scale))
        self.anchor = RailAnchor(RailSide(config.base_side), config.base_fraction)
        self.sliding_base = config.sliding_base
        self.body_region = EdgeRegion(self.world)
        self.arm_region = EdgeRegion(self.world, body=False)
        self.navigator = None
        self.tilt_degrees = 0.0
        self.reset()

    @property
    def desired_direction(self):
        angle = radians(max(-25., min(25., self.tilt_degrees+self.pose.angle)))
        return Vec2(sin(angle), -cos(angle))

    @property
    def base(self):
        return self.navigator.base.position if self.navigator else self.world.anchor_position(self.anchor)

    def base_normal(self, alpha=1.):
        if self.navigator:
            base = self.navigator.base
            return self.navigator.rail.normal(base.previous_s + (base.s - base.previous_s) * alpha)
        return self.world.normal(self.anchor.side)

    def reset(self):
        self.pose = OraclePose()
        self.navigator = None
        base = self.world.anchor_position(self.anchor)
        normal = self.world.normal(self.anchor.side)
        if self.sliding_base:
            rail = RoundedRail(self.world)
            s = rail.project(base)
            base, normal = rail.sample(s)[0], rail.normal(s)
        start = self.world.corridor(self.anchor.side).clamp(base + normal * 64)
        self.body = OracleBody([MotionPoint.at(start), MotionPoint.at(start - self.desired_direction * 9)])
        self.head = OracleHead.at(start+self.desired_direction
                                  *(OracleHead.NECK_BASE_OFFSET+OracleHead.CONNECTION_LENGTH), radius=5)
        tip = start - self.desired_direction * 30 * self.config.arm_scale
        corridor = self.arm_region if self.sliding_base else self.world.corridor(self.anchor.side, False)
        self.arm = FixedOracleArm(base, tip, normal, corridor, self.config.arm_scale)
        if self.sliding_base:
            self.navigator = FloatNavigator(self.world, start, base, self.arm.maximum_reach,
                                            self.config.float_speed, self.config.base_speed)
        self.requested_target = self.target = start
        self.look_target = None
        self.look_direction = Vec2()
        self.previous_look_direction = Vec2()
        region = self.navigator.region if self.navigator else self.body_region
        tangent = Vec2(normal.y, -normal.x)
        candidates = [self.project_target(start+tangent*(sign*90)+Vec2(0, -12)) for sign in (1, -1)]
        home = max(candidates, key=lambda p: (p-start).length())
        home = PearlState.nearby_home(home, start, region, self.config.pearl_follow_width, self.config.pearl_follow_height)
        self.pearl = PearlState(home, self.world, region)
        self.pearl.follow_home(start, self.config.pearl_follow_width, self.config.pearl_follow_height)
        self.behavior = OracleBehavior()
        self.eyes = OracleEyes()
        # 字形只在创建时选择；独立随机流不影响日常行为的节奏。
        self.pearl.glyph_id = Random(12842).randrange(14)
        self.ticks = 0
        self.appearance = OracleAppearance(self)

    def set_anchor(self, side, fraction):
        if not isfinite(fraction) or not 0 <= fraction <= 1:
            raise ValueError('底座位置必须在 0～1 之间')
        self.anchor = RailAnchor(RailSide(side), fraction)
        self.reset()

    def project_target(self, point):
        finite_point(point)
        if self.navigator:
            options = [safe.clamp(point) for physical, safe in zip(self.body_region.boxes, self.navigator.region.boxes)
                       if physical.contains(point)]
            return min(options, key=lambda p: (p - point).length()) if options else self.navigator.region.clamp(point)
        box = self.world.corridor(self.anchor.side)
        point = box.clamp(point)
        for _ in range(8):
            point = self.base + limited(point - self.base, self.arm.maximum_reach)
            point = box.clamp(point)
        return point

    def set_target(self, point):
        finite_point(point)
        self.behavior.cancel(self, stop_body=False)
        self._move_to(point)

    def _move_to(self, point, *, route=None):
        """导航入口；行为控制器调用它，不触发手动接管。"""
        finite_point(point)
        self.requested_target = point
        self.target = self.project_target(point)
        if self.navigator:
            upper = self.body.chunks[0]
            self.navigator.set_route(route if route is not None else
                                     self.navigator.planner.plan(upper.position, self.target, upper.velocity))

    def set_sliding_base(self, enabled):
        self.sliding_base = bool(enabled)
        self.reset()

    def start_lap(self, clockwise=True):
        self.behavior.cancel(self, stop_body=False)
        if not self.navigator:
            return
        upper = self.body.chunks[0]
        self.requested_target = self.target = upper.position
        self.navigator.set_route(self.navigator.planner.lap(upper.position, clockwise))

    def stop(self):
        self.set_target(self.body.chunks[0].position)

    def set_look_target(self, point):
        if point is not None:
            finite_point(point)
        self.behavior.cancel(self)
        self.look_target = point
        if point is None:
            self.eyes.end_observation()
        else:
            self.eyes.begin_observation()

    def set_autonomous(self, enabled):
        self.behavior.set_enabled(self, enabled)

    def observe_pearl(self, mode='approach'):
        if mode not in ('approach', 'recall'):
            raise ValueError('观察方式必须为 approach 或 recall')
        self.behavior.enabled = False  # 调试按钮明确运行一次；循环由自主开关启动。
        self.behavior.notice(self, mode)

    def roam(self, *, adjacent=False):
        """调试入口：手动触发一次短途或邻边移动，不开启自主循环。"""
        self.behavior.cancel(self, stop_body=False)
        return self.behavior.start_roam(self, adjacent=adjacent)

    def set_pearl_home(self, point):
        finite_point(point)
        self.behavior.cancel(self)
        self.pearl.home = self.pearl.nearby_home(self.project_target(point), self.body.chunks[0].position,
                                                self.pearl.region, self.config.pearl_follow_width, self.config.pearl_follow_height)
        self.pearl.return_home()

    def set_tilt(self, degrees):
        if not isfinite(degrees) or not -25 <= degrees <= 25:
            raise ValueError('躯干倾角必须在 -25～25 度之间')
        self.tilt_degrees = degrees

    @property
    def arrived(self):
        return ((self.body.chunks[0].position - self.target).length() < .3
                and max(c.velocity.length() for c in self.body.chunks) < .03
                and (self.navigator is None or (self.navigator.done and abs(self.navigator.base.velocity) < .01)))

    def step(self):
        self.behavior.step(self)
        self.eyes.step()
        previous_direction = self.body.direction
        guide, feedforward = self.target, Vec2()
        if self.navigator:
            self.navigator.step(self.body.chunks[0].position, self.arm.maximum_reach)
            guide, feedforward = self.navigator.guide, self.navigator.velocity
        self.pose.step(self)
        direction = self.desired_direction
        for i, chunk in enumerate(self.body.chunks):
            chunk.previous_position = chunk.position
            goal = guide - direction * (i * self.body.connection_length)
            desired_velocity = limited(chunk.velocity * .4 + limited(goal - chunk.position, 100)
                                       * (.062 if i == 0 else .032) + feedforward * .6, 2.4)
            chunk.velocity = (chunk.velocity + limited(desired_velocity - chunk.velocity, .12)
                              if self.navigator else desired_velocity)
            chunk.position = chunk.position + chunk.velocity
        upper, lower = self.body.chunks
        axis = unit(upper.position - lower.position, direction)
        # 直接点击目标没有原版缓慢前移的 Bezier 导引点；额外限制倾斜和角速度，
        # 防止上下移动时上身赶超下身，导致质点身份不变却整个人偶倒转。
        desired_angle = atan2(direction.x, -direction.y)
        angle = atan2(axis.x, -axis.y)
        deviation = (angle - desired_angle + pi) % (2 * pi) - pi
        angle = desired_angle + max(-.55, min(.55, deviation))
        old_angle = atan2(previous_direction.x, -previous_direction.y)
        delta_angle = (angle - old_angle + pi) % (2 * pi) - pi
        angle = old_angle + max(-.055, min(.055, delta_angle))
        axis = Vec2(sin(angle), -cos(angle))
        center = upper.position.lerp(lower.position, .5)
        upper.position = center + axis * (self.body.connection_length * .5)
        lower.position = center - axis * (self.body.connection_length * .5)
        if self.navigator:
            candidate = self.base + limited(upper.position - self.base, self.arm.maximum_reach)
            safe = self.navigator.region.safe_move(upper.previous_position, candidate)
        else:
            safe = self.project_target(upper.position)
        shift = safe - upper.position
        for chunk in self.body.chunks:
            chunk.position = chunk.position + shift
            chunk.velocity = chunk.position - chunk.previous_position
        self.pearl.follow_home(upper.position, self.config.pearl_follow_width, self.config.pearl_follow_height,
                              allow_motion=not self.behavior.controls_pearl)
        self.pearl.step()
        if self.behavior.looking:
            self.look_target = self.pearl.position
        self.previous_look_direction = self.look_direction
        desired_look = limited((self.look_target - upper.position) * .01, 1) if self.look_target is not None else Vec2()
        self.look_direction = self.look_direction.lerp(desired_look, .12)
        self.head.step(upper, self.body.direction, self.look_direction)
        self.arm.step(upper.position - self.body.direction * self.arm.lengths[3],
                      self.base if self.navigator else None, self.base_normal())
        self.appearance.step(self)
        self.ticks += 1
