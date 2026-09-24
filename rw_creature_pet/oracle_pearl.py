"""一颗悬浮珍珠。曲线导引限制在边缘带内，阻尼跟随保留柔和的起停。"""
from math import sqrt

from .geometry import Vec2
from .oracle_navigation import CurveRoute, EdgePlanner, approach


class PearlState:
    RADIUS = 3.
    MAX_SPEED = 1.6
    ACCELERATION = .045

    def __init__(self, position, world, region, glyph_id=4):
        self.home = self.position = self.previous_position = position
        self.velocity = Vec2()
        self.radius = self.RADIUS
        self.glyph_id = glyph_id
        self.region = region
        self.planner = EdgePlanner(world, region)
        self.route = CurveRoute([], position)
        self.target = position
        self.distance = self.speed = 0.
        self.settled = True
        self.revision = 0

    def move_to(self, target):
        target = self.region.clamp(target)
        if (target-self.target).length() < 1e-6:
            return
        self.target = target
        self.route = self.planner.plan(self.position, target, self.velocity)
        self.distance = 0.
        self.settled = False

    def return_home(self):
        self.move_to(self.home)

    def step(self):
        self.previous_position = self.position
        if self.settled:
            return
        remaining = max(0., self.route.length-self.distance)
        desired = min(self.route.speed_limit(self.distance, self.MAX_SPEED),
                      sqrt(2*self.ACCELERATION*remaining))
        self.speed = approach(self.speed, desired, self.ACCELERATION)
        self.distance = min(self.route.length, self.distance+self.speed)
        if self.distance >= self.route.length:
            self.speed = 0.
        guide = self.route.sample(self.distance)
        # PebblesPearl 的目标牵引 + 速度阻尼结构；桌面增加阻尼以快速收敛。
        velocity = self.velocity*.72+(guide-self.position)*.032
        length = velocity.length()
        if length > self.MAX_SPEED:
            velocity = velocity*(self.MAX_SPEED/length)
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
