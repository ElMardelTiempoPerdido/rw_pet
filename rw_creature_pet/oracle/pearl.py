"""一颗悬浮珍珠。曲线导引限制在边缘带内，阻尼跟随保留柔和的起停。"""
from enum import IntEnum
from math import sqrt

from ..shared.geometry import Bounds, Vec2
from .navigation import CurveRoute, EdgePlanner, approach


class PearlColorSlot(IntEnum):
    """独立于排列/运动方式的颜色档位，编号对应原版 CreateMarble。"""
    PRIMARY = 0
    COMMON = 1
    SECONDARY = 2


class PearlState:
    RADIUS = 3.
    MAX_SPEED = 1.6
    FOLLOW_SPEED = 2.4
    ACCELERATION = .045
    FOLLOW_INSET = 64.
    REPLAN_TICKS = 12

    def __init__(self, position, world, region, glyph_id=4, *, color_slot=PearlColorSlot.COMMON):
        self.home = self.position = self.previous_position = position
        self.velocity = Vec2()
        self.radius = self.RADIUS
        self.glyph_id = glyph_id
        self.color_slot = PearlColorSlot(color_slot)
        self.region = region
        # 珍珠无需给机械臂让出整条走廊。靠近内角绕行，避免跟随时先向
        # 远处的走廊中线退让一大圈；region 已预留珠体和字符的安全边距。
        self.planner = EdgePlanner(world, region, corner_clearance=16.)
        self.route = CurveRoute([], position)
        self.target = position
        self.distance = self.speed = 0.
        self.settled = True
        self.revision = 0
        self.follow_bounds = None
        self.returning_home = True
        self.catching_up = False
        self._replan_ticks = 0

    @classmethod
    def nearby_home(cls, point, center, region, width, height, *, inset=False):
        """投影到矩形与人偶当前走廊的交集，防止悬浮点隔着内角留在旧边。"""
        x, y = width/2, height/2
        if inset:
            x -= min(cls.FOLLOW_INSET, x*.4)
            y -= min(cls.FOLLOW_INSET, y*.4)
        candidates = []
        for box in region.boxes:
            if not box.contains(center):
                continue
            l, r = max(box.left, center.x-x), min(box.right, center.x+x)
            t, b = max(box.top, center.y-y), min(box.bottom, center.y+y)
            if l <= r and t <= b:
                candidates.append(Bounds(l, t, r, b).clamp(point))
        # 人偶自身位于走廊内，交集始终存在。
        return min(candidates, key=lambda p: (p-point).length())

    def follow_home(self, center, width, height, *, allow_motion=True):
        self.follow_bounds = Bounds(center.x-width/2, center.y-height/2,
                                    center.x+width/2, center.y+height/2)
        self._replan_ticks = max(0, self._replan_ticks-1)
        shared_corridor = any(box.contains(center) and box.contains(self.home) for box in self.region.boxes)
        if not self.follow_bounds.contains(self.home) or not shared_corridor:
            # 虚拟悬浮点向内收一段，留出滞回；真实珠子保持原位置和速度。
            self.home = self.nearby_home(self.home, center, self.region, width, height, inset=True)
            self.revision += 1
        if (allow_motion and self.returning_home and self.target != self.home
                and self._replan_ticks == 0):
            self._set_target(self.home, catch_up=True)
            self._replan_ticks = self.REPLAN_TICKS

    def move_to(self, target):
        self.returning_home = False
        self._set_target(target)

    def _set_target(self, target, *, catch_up=False):
        target = self.region.clamp(target)
        if (target-self.target).length() < 1e-6:
            return
        self.target = target
        self.route = self.planner.plan(self.position, target, self.velocity)
        self.catching_up = catch_up
        # 更新移动中的悬浮点时保留牵引导引的前置距离，否则每次重规划
        # 都会把导引退回珠心、反复刹车，导致珠子永远追不上人偶。
        tangent = self.route.sample(4)-self.position
        forward = max(0., (self.velocity.x*tangent.x+self.velocity.y*tangent.y)
                      / max(1e-9, tangent.length()))
        self.distance = min(self.route.length, max(0., forward*.28/.032-self.speed)) if catch_up else 0.
        self.settled = False

    def return_home(self):
        self.returning_home = True
        self._set_target(self.home)

    def step(self):
        self.previous_position = self.position
        if self.settled:
            return
        remaining = max(0., self.route.length-self.distance)
        maximum = self.FOLLOW_SPEED if self.catching_up else self.MAX_SPEED
        desired = min(self.route.speed_limit(self.distance, maximum),
                      sqrt(2*self.ACCELERATION*remaining))
        self.speed = approach(self.speed, desired, self.ACCELERATION)
        self.distance = min(self.route.length, self.distance+self.speed)
        if self.distance >= self.route.length:
            self.speed = 0.
        guide = self.route.sample(self.distance)
        # PebblesPearl 的目标牵引 + 速度阻尼结构；桌面增加阻尼以快速收敛。
        velocity = self.velocity*.72+(guide-self.position)*.032
        acceleration = velocity-self.velocity
        if acceleration.length() > .09:
            velocity = self.velocity+acceleration*(.09/acceleration.length())
        length = velocity.length()
        # 从追赶切换到观察时逐渐减速，保留手动打断时的连续性。
        maximum = max(maximum, self.velocity.length()-self.ACCELERATION)
        if length > maximum:
            velocity = velocity*(maximum/length)
        candidate = self.region.safe_move(self.position, self.position+velocity)
        if (self.distance >= self.route.length and (candidate-self.target).length() < .015
                and velocity.length() < .01):
            candidate = self.target
            self.settled = True
        self.position = candidate
        self.velocity = Vec2() if self.settled else candidate-self.previous_position
        self.revision += 1

    def sample(self, alpha):
        return self.previous_position.lerp(self.position, alpha)
