"""Oracle 场景：滑动底座、边缘曲线漂浮、两质点身体及独立观察。

坐标 y 向下，固定 40 Hz；速度为单位 / tick。没有 Qt 或墙钟依赖。
原版参考 Oracle.cs / OracleGraphics.cs；关节求解和边缘范围为桌面适配。
"""
from dataclasses import dataclass, replace
from enum import Enum
from math import atan2, cos, isfinite, pi, radians, sin, sqrt

from ..shared.geometry import Bounds, Vec2
from .config import OracleConfig
from .navigation import EdgeRegion, FloatNavigator, RoundedRail
from .appearance import OracleAppearance
from .behavior import Activity, OracleBehavior
from .eyes import OracleEyes
from .halo import OracleHalo
from .pearl_matrix import PearlMatrix
from .pearl_orbits import PearlOrbits
from .pearl_fixed import FixedPearls
from .pose import OraclePose
from .drag import OracleDrag
from .drag_reactions import OracleDragReactions


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

    def _unfold_at_boundary(self, joint, anchor, minimum):
        """径向推出被边界抵消时，沿边界解最小跨度圆的最近交点。"""
        delta = joint.position-anchor
        if delta.length() >= minimum-1e-6 or self.corridor.contains(anchor+unit(delta)*minimum):
            return
        candidates = []
        boxes = self.corridor.boxes if isinstance(self.corridor, EdgeRegion) else (self.corridor,)
        for box in boxes:
            for x in (box.left, box.right):
                square = minimum**2-(x-anchor.x)**2
                if square >= 0:
                    candidates.extend((Vec2(x, anchor.y+sqrt(square)), Vec2(x, anchor.y-sqrt(square))))
            for y in (box.top, box.bottom):
                square = minimum**2-(y-anchor.y)**2
                if square >= 0:
                    candidates.extend((Vec2(anchor.x+sqrt(square), y), Vec2(anchor.x-sqrt(square), y)))
        candidates = [p for p in candidates if self.corridor.contains(p) and (
            not isinstance(self.corridor, EdgeRegion) or self.corridor.segment_safe(anchor, p))]
        if candidates:
            joint.position = min(candidates, key=lambda p: ((p-joint.position).length(),
                                                           (p-joint.previous_position).length()))

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
            for i, joint in enumerate(self.joints[1:3]):
                before = joint.position
                joint.position = self.corridor.clamp(joint.position)
                if joint.position != before:
                    self._unfold_at_boundary(joint, self.base if i == 0 else tip,
                                             self.minimum_spans[0 if i == 0 else 2])
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
        if self.constraint_error > .02:
            # 大倾角末端经过窄角落时，边界投影偶尔耗尽首轮预算。
            # 只为未收敛帧补一轮；常规移动和静置不增加迭代数。
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
        self.pearl_matrix_enabled = config.pearl_matrix_enabled
        self.pearl_orbits_enabled = config.pearl_orbits_enabled
        self.body_region = EdgeRegion(self.world)
        self.arm_region = EdgeRegion(self.world, body=False)
        self.navigator = None
        self.tilt_degrees = 0.0
        self.reset()

    @property
    def desired_direction(self):
        # 普通行为的 ±25° 目标限制在 pose 中；漫游与回正必须连续经过大倾角。
        angle = radians(self.tilt_degrees+self.pose.angle)
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
        drag_enabled = self.drag.enabled if hasattr(self, 'drag') else False
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
        self.travel_speed = None
        self.look_target = None
        self.look_direction = Vec2()
        self.previous_look_direction = Vec2()
        self.behavior = OracleBehavior()
        self.eyes = OracleEyes()
        self.drag_reactions = OracleDragReactions(self.config.drag_reactions)
        self._reset_fixed_pearls()
        self.pearl_matrix = None
        self.set_pearl_matrix(self.pearl_matrix_enabled)
        self.pearl_orbits = None
        self.set_pearl_orbits(self.pearl_orbits_enabled)
        self.ticks = 0
        self.appearance = OracleAppearance(self)
        self.halo = OracleHalo(self.world, self.orbit_center, self.config.halo_scale)
        self.drag = OracleDrag(self, drag_enabled)

    def set_halo_enabled(self, enabled):
        was_enabled = self.config.halo_enabled
        self.config = replace(self.config, halo_enabled=enabled)
        if enabled and not was_enabled:
            self.halo.center = self.halo.previous_center = self.halo.region.clamp(self.orbit_center)

    def set_halo_scale(self, scale=1.):
        self.halo.set_scale(scale)

    def pulse_halo(self, scale=1.25, hold_seconds=.8):
        self.halo.pulse(scale, hold_seconds)

    @property
    def halo_visible(self):
        return self.config.halo_enabled and self.config.projection_opacity > 0

    @property
    def halo_visual_revision(self):
        return (self.halo, self.halo.revision) if self.halo_visible else None

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
        if self.drag.controlling:
            self.drag.release(cancel=True)
            return
        self.behavior.cancel(self, stop_body=False)
        self._move_to(point)

    def _move_to(self, point, *, route=None, speed=None):
        """导航入口；行为控制器调用它，不触发手动接管。"""
        if getattr(self, 'drag', None) is not None and self.drag.controlling:
            return
        finite_point(point)
        self.requested_target = point
        self.target = self.project_target(point)
        self.travel_speed = speed
        if self.navigator:
            upper = self.body.chunks[0]
            self.navigator.set_route(route if route is not None else
                                     self.navigator.planner.plan(upper.position, self.target, upper.velocity))

    def set_sliding_base(self, enabled):
        self.sliding_base = bool(enabled)
        self.reset()

    def start_lap(self, clockwise=True):
        if self.drag.controlling:
            return
        self.behavior.cancel(self, stop_body=False)
        if not self.navigator:
            return
        upper = self.body.chunks[0]
        self.requested_target = self.target = upper.position
        self.travel_speed = None
        self.navigator.set_route(self.navigator.planner.lap(upper.position, clockwise))

    def stop(self):
        self.set_target(self.body.chunks[0].position)

    def set_look_target(self, point):
        if self.drag.controlling:
            return
        if point is not None:
            finite_point(point)
        self.behavior.cancel(self)
        self.look_target = point
        if point is None:
            self.eyes.end_observation()
        else:
            self.eyes.begin_observation()

    def set_autonomous(self, enabled):
        if self.drag.controlling:
            self.drag.resume_autonomy = bool(enabled)
            return
        self.behavior.set_enabled(self, enabled)

    def set_pearl_matrix(self, enabled):
        """关闭时结束矩阵观察；单珠行为和自主/失重开关保持不变。"""
        self.pearl_matrix_enabled = bool(enabled)
        if enabled and self.config.pearl_matrix_count and self.pearl_matrix is None:
            self.pearl_matrix = PearlMatrix(self.world, self.body_region,
                                            self.body.chunks[0].position, self.base_normal(),
                                            self.config.pearl_follow_width, self.config.pearl_follow_height,
                                            self.config.pearl_matrix_count)
        elif not enabled or not self.config.pearl_matrix_count:
            if self.behavior.matrix_observation:
                self.eyes.end_observation()
                self._move_to(self.body.chunks[0].position)
                self.behavior.resume_or_idle(self)
            self.pearl_matrix = None

    @property
    def orbit_center(self):
        # 原版 OracleGraphics.Halo.Center：从上身穿过头部，继续向外 20。
        upper, head = self.body.chunks[0].position, self.head.position
        return head+unit(head-upper, self.body.direction)*20

    def set_pearl_orbits(self, enabled):
        self.pearl_orbits_enabled = bool(enabled)
        if enabled and (self.config.pearl_inner_count or self.config.pearl_outer_count):
            if self.pearl_orbits is None:
                self.pearl_orbits = PearlOrbits(self.world, self.body_region,
                    self.body.chunks[0].position, self.orbit_center,
                    self.config.pearl_follow_width, self.config.pearl_follow_height,
                    self.config.pearl_inner_count, self.config.pearl_outer_count)
        else:
            self.pearl_orbits = None

    def _reset_fixed_pearls(self):
        region = self.navigator.region if self.navigator else self.body_region
        self.fixed_pearls = FixedPearls(self.world, region, self.body.chunks[0].position,
            self.base_normal(), self.config.pearl_follow_width, self.config.pearl_follow_height,
            self.config.pearl_fixed_count, self.config.pearl_satellite_count)

    def set_pearl_counts(self, *, matrix=None, inner=None, outer=None, fixed=None, satellite=None):
        """调试即时数量预览；先验证整份配置，再重建发生变化的组。"""
        changes = {name: value for name, value in (
            ('pearl_matrix_count', matrix), ('pearl_inner_count', inner), ('pearl_outer_count', outer),
            ('pearl_fixed_count', fixed), ('pearl_satellite_count', satellite))
            if value is not None}
        settings = replace(self.config, **changes)
        matrix_changed = settings.pearl_matrix_count != self.config.pearl_matrix_count
        orbits_changed = (settings.pearl_inner_count, settings.pearl_outer_count) != (
            self.config.pearl_inner_count, self.config.pearl_outer_count)
        fixed_changed = (settings.pearl_fixed_count, settings.pearl_satellite_count) != (
            self.config.pearl_fixed_count, self.config.pearl_satellite_count)
        self.config = settings
        if matrix_changed:
            enabled = self.pearl_matrix_enabled
            self.set_pearl_matrix(False)  # 结束旧槽位观察；不能留下已删除成员的引用。
            self.set_pearl_matrix(enabled)
        if orbits_changed:
            self.pearl_orbits = None
            self.set_pearl_orbits(self.pearl_orbits_enabled)
        if fixed_changed:
            if self.behavior.observation_pearl in self.fixed_pearls.roots:
                self.eyes.end_observation()
                self._move_to(self.body.chunks[0].position)
                self.behavior.resume_or_idle(self)
            self._reset_fixed_pearls()

    @property
    def pearl(self):
        """旧诊断脚本的首颗固定珠别名；不再创建额外调试单珠。"""
        return self.fixed_pearls.roots[0] if self.fixed_pearls.roots else None

    @property
    def observed_pearl(self):
        return self.behavior.observation_pearl or self.pearl

    @property
    def observation_returned(self):
        if self.behavior.matrix_observation:
            return self.pearl_matrix is not None and self.pearl_matrix.extracted is None
        return self.observed_pearl is None or self.observed_pearl.settled

    @property
    def pearl_visual_revision(self):
        matrix = self.pearl_matrix
        orbits = self.pearl_orbits
        return (self.fixed_pearls, self.fixed_pearls.revision, matrix, matrix.revision if matrix else 0,
                orbits, orbits.revision if orbits else 0)

    @property
    def pearls_settled(self):
        return self.observation_pearls_settled and self.fixed_pearls.settled and self.pearl_orbits is None

    @property
    def observation_pearls_settled(self):
        """环绕持续运动不阻塞停留、冥想或下一次观察。"""
        return self.fixed_pearls.roots_settled and (self.pearl_matrix is None or self.pearl_matrix.settled)

    def observe_pearl(self, mode='approach'):
        if self.drag.controlling:
            return False
        if mode not in ('approach', 'recall', 'orbit'):
            raise ValueError('观察方式必须为 approach、recall 或 orbit')
        if not self.behavior.notice(self, mode):
            return False
        self.behavior.enabled = False  # 调试按钮明确运行一次；循环由自主开关启动。
        return True

    def observe_matrix_pearl(self, slot=None):
        """手动抽取一次；已抽出时继续使用同一颗，关闭矩阵时无操作。"""
        if self.drag.controlling:
            return False
        if not self.behavior.notice(self, 'recall', matrix=True, slot=slot):
            return False
        self.behavior.enabled = False
        return True

    def meditate(self):
        """手动触发一次冥想；失重中保留当前模式，结束后继续本段漫游。"""
        if self.drag.controlling:
            return
        self.behavior.enabled = False
        self.behavior.start_meditation(self)

    def roam(self, *, adjacent=False):
        """调试入口：手动触发一次短途或邻边移动，不开启自主循环。"""
        if self.drag.controlling:
            return False
        self.behavior.cancel(self, stop_body=False)
        return self.behavior.start_roam(self, adjacent=adjacent)

    def drift(self):
        """手动触发一次完整反重力漫游，结束后停留。"""
        if self.drag.controlling:
            return
        self.behavior.cancel(self, stop_body=False)
        self.behavior.start_drift(self)

    def set_pearl_home(self, point):
        if self.drag.controlling:
            return False
        finite_point(point)
        if not self.fixed_pearls.roots:
            return False
        pearl = min(self.fixed_pearls.roots, key=lambda p: (p.position-point).length())
        self.behavior.cancel(self)
        pearl.home = pearl.nearby_home(self.project_target(point), self.body.chunks[0].position,
                                      pearl.region, self.config.pearl_follow_width, self.config.pearl_follow_height)
        pearl.return_home()
        return True

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
        if self.drag.controlling:
            self.drag.step_body()
        else:
            self._step_motion()
        self.drag_reactions.step(self)
        self._step_appearance()
        self.drag.after_step()

    def _step_motion(self):
        self.behavior.step(self)
        self.eyes.step()
        previous_direction = self.body.direction
        guide, feedforward = self.target, Vec2()
        if self.navigator:
            self.navigator.step(self.body.chunks[0].position, self.arm.maximum_reach,
                                speed_limit=self.travel_speed)
            guide, feedforward = self.navigator.guide, self.navigator.velocity
        self.pose.step(self)
        direction = self.desired_direction
        observe_force = Vec2(-direction.y, direction.x)*self.pose.observation_force(self)
        for i, chunk in enumerate(self.body.chunks):
            chunk.previous_position = chunk.position
            goal = guide - direction * (i * self.body.connection_length)
            # 失重时下身少接受一部分导航前馈，由连接带着跟上上身。
            # 差异只存在于移动中，提供运动产生的转矩，不指定躺倒角度。
            carry = .6-(.12*self.pose.weightlessness if i == 1 and self.behavior.drift_active else 0.)
            desired_velocity = limited(chunk.velocity * .4 + limited(goal - chunk.position, 100)
                                       * (.062 if i == 0 else .032) + feedforward * carry
                                       + observe_force*(1 if i == 0 else -1), 2.4)
            if not self.navigator:
                desired_velocity = limited(desired_velocity, self.travel_speed or 2.4)
            chunk.velocity = (chunk.velocity + limited(desired_velocity - chunk.velocity, .12)
                              if self.navigator else desired_velocity)
            chunk.position = chunk.position + chunk.velocity
        upper, lower = self.body.chunks
        axis = unit(upper.position - lower.position, direction)
        # 普通活动围绕受控朝向，失重时参考上一帧真实身体方向。
        # 两个质点响应速度不同而产生转动，安全角速度限制防止瞬间翻转。
        desired_angle = atan2(direction.x, -direction.y)
        angle = atan2(axis.x, -axis.y)
        deviation = (angle - desired_angle + pi) % (2 * pi) - pi
        angle = desired_angle + max(-.55, min(.55, deviation))
        old_angle = atan2(previous_direction.x, -previous_direction.y)
        delta_angle = (angle - old_angle + pi) % (2 * pi) - pi
        angle_limit = self.pose.DRIFT_ANGULAR_LIMIT if self.behavior.drift_active else .055
        angle = old_angle + max(-angle_limit, min(angle_limit, delta_angle))
        axis = Vec2(sin(angle), -cos(angle))
        center = upper.position.lerp(lower.position, .5)
        upper.position = center + axis * (self.body.connection_length * .5)
        lower.position = center - axis * (self.body.connection_length * .5)
        if self.navigator:
            candidate = self.base + limited(upper.position - self.base, self.arm.maximum_reach)
            safe = self.navigator.region.safe_move(upper.previous_position, candidate)
        else:
            safe = self.project_target(upper.position)
        if self.behavior.drift_active and self.navigator:
            # 普通漫游锁在当前边；明确跨边时只开放起点边和目标邻边。
            # 仍保留上方的逐段禁区检查和人偶外形余量。
            boxes = self.navigator.region.boxes
            edges = (self.behavior.drift_edge, self.behavior.destination_edge) if (
                self.behavior.state == Activity.DRIFT_CROSS_EDGE) else (self.behavior.drift_edge,)
            safe = min((boxes[edge].clamp(safe) for edge in edges), key=lambda p: (p-safe).length())
        shift = safe - upper.position
        for chunk in self.body.chunks:
            chunk.position = chunk.position + shift
            chunk.velocity = chunk.position - chunk.previous_position
    def _step_appearance(self):
        upper = self.body.chunks[0]
        # 珍珠本轮尚不可抓取，仍在活动带内跟随人偶对应的边缘投影。
        pearl_center = self.project_target(upper.position) if self.drag.controlling else upper.position
        self.fixed_pearls.step(pearl_center, self.observed_pearl if self.behavior.controls_pearl else None)
        if self.pearl_matrix is not None:
            self.pearl_matrix.step(pearl_center)
        if self.behavior.looking:
            self.look_target = self.observed_pearl.position
        self.previous_look_direction = self.look_direction
        desired_look = limited((self.look_target - upper.position) * .01, 1) if self.look_target is not None else Vec2()
        self.look_direction = self.look_direction.lerp(desired_look, .12)
        self.head.step(upper, self.body.direction, self.look_direction)
        if self.pearl_orbits is not None:
            self.pearl_orbits.step(pearl_center, self.orbit_center)
        self.arm.step(upper.position - self.body.direction * self.arm.lengths[3],
                      self.base if self.navigator else None, self.base_normal())
        self.appearance.step(self)
        if self.halo_visible:
            if self.drag.controlling:
                preferred = (self.halo.region.clamp(self.orbit_center) if self.drag.recovering
                             else self.orbit_center)
                self.halo.step(preferred, region=self.drag.halo_region)
            else:
                self.halo.step(self.orbit_center)
        self.ticks += 1
