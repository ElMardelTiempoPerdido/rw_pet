"""固定步长平地身体与四足步态模拟。"""
from dataclasses import dataclass
from math import isfinite

from .config import DebugConfig
from .geometry import Vec2
from .lizard import LizardBody
from .gait import FlatGait
from .appearance import LizardAppearance
from .background import BackgroundGrip
from .footholds import spatial_candidates


@dataclass(frozen=True, slots=True)
class FlatWorld:
    width: float
    height: float
    floor_y: float

    def floor_projection(self, point: Vec2) -> Vec2:
        """地板上的最近点，供抓点查询及调试投影共用。"""
        return Vec2(max(0.0, min(self.width, point.x)), self.floor_y)

    def background_position(self, point, radius=0.0):
        """背景姿态的中心范围，预留显示半径；与实体地板碰撞分开。"""
        return Vec2(max(radius, min(self.width-radius, point.x)),
                    max(radius, min(self.floor_y-radius, point.y)))

    def background_regions(self):
        return ((0, 0, self.width, self.floor_y),)

    def background_contains(self, point, radius=0.0):
        return (self.background_position(point, radius)-point).length() < 1e-7

    def background_grip(self, hip: Vec2, goal: Vec2, reach: float) -> Vec2 | None:
        """背景可抓附矩形独立于实体地板；不把身体投影到地面。"""
        if not (0 <= hip.x <= self.width and 0 <= hip.y <= self.floor_y):
            return None
        point = Vec2(max(0, min(self.width, goal.x)), max(0, min(self.floor_y, goal.y)))
        return point if (point - hip).length() <= reach else None

    def background_candidates(self, hip: Vec2, reach: float):
        """只返回当前背景区域内的固定抓点，不将候选吸附到移动的边界位置。"""
        return (point for point in spatial_candidates(hip, reach)
                if self.background_grip(hip, point, reach) == point)


class DebugScene:
    def __init__(self, config: DebugConfig):
        self.world = FlatWorld(config.world_width, config.world_height, config.floor_y)
        self.body = LizardBody.preview(Vec2(self.world.width / 2, self.world.floor_y - 28))
        self.gait = FlatGait(self.body)
        self.appearance = LizardAppearance(self.body)
        self.background = BackgroundGrip(self.body)
        self.background_mode = False
        self.spawn_height = self.world.floor_y / 2
        self.ticks = 0

    def reset(self):
        if self.background_mode:
            self.place_on_background(self.spawn_height, self.background.enabled)
            return
        enabled, speed = self.gait.enabled, self.gait.speed
        self.body = LizardBody.preview(Vec2(self.world.width / 2, self.world.floor_y - 28))
        self.gait = FlatGait(self.body)
        self.appearance = LizardAppearance(self.body)
        self.background = BackgroundGrip(self.body)
        self.gait.enabled = enabled
        self.gait.set_speed(speed)
        self.ticks = 0

    @property
    def feet(self):
        return self.background.feet if self.background_mode else self.gait.feet

    def place_on_background(self, height: float, attached=True):
        if not isfinite(height) or not 8 <= height <= self.world.floor_y - 8:
            raise ValueError('离地高度必须保证身体位于背景范围内')
        self.spawn_height = height
        self.body = LizardBody.preview(Vec2(self.world.width / 2, self.world.floor_y - height))
        self.appearance = LizardAppearance(self.body)
        self.gait = FlatGait(self.body)
        self.background = BackgroundGrip(self.body)
        self.background_mode = True
        self.background.set_enabled(attached, self.body, self.world)
        self.ticks = 0

    def set_background_mode(self, enabled):
        if enabled:
            self.place_on_background(self.spawn_height)
        else:
            self.background_mode = False
            self.reset()

    def set_horizontal_velocity(self, velocity: float):
        """一次性速度干预；保留正在下落的竖直速度。"""
        if not isfinite(velocity):
            raise ValueError("速度必须为有限数值")
        for chunk in self.body.chunks:
            chunk.velocity = Vec2(velocity, chunk.velocity.y)

    def step(self):
        if self.background_mode:
            self.background.update(self.body, self.world, self.appearance.look_target)
            self.background.drive(self.body)
            if self.background.attached:
                self.body.step(self.world, gravity=0.0, air_friction=.8,
                               reach_limits=self.background.reach_limits(), background=True)
            else:
                self.body.step(self.world)
            self.background.validate_contacts(self.body)
            travel = self.background.direction if self.background.was_moving else Vec2()
        else:
            self.gait.update(self.body, self.world)
            self.gait.drive(self.body)
            self.body.step(self.world)
            self.gait.validate_contacts(self.body)
            travel = Vec2(self.gait.facing, 0) if self.gait.enabled and self.gait.speed else Vec2()
        self.appearance.update(self.body, self.world, self.feet,
                               background=self.background_mode and self.background.attached,
                               travel_direction=travel)
        self.ticks += 1


class FixedStepper:
    """实际计时独立于画面重绘；暂停丢弃积压，慢帧限制追赶量。"""
    def __init__(self, tick_rate: int, max_steps: int = 4):
        self.dt = 1.0 / tick_rate
        self.max_steps = max_steps
        self.paused = False
        self.accumulator = 0.0
        self.dropped_seconds = 0.0

    @property
    def alpha(self) -> float:
        return 1.0 if self.paused else self.accumulator / self.dt

    def set_paused(self, paused: bool):
        self.paused = paused
        self.accumulator = 0.0

    def advance(self, elapsed: float, step) -> int:
        if not isfinite(elapsed) or elapsed < 0:
            raise ValueError("elapsed 必须为非负有限数值")
        if self.paused:
            return 0
        self.accumulator += elapsed
        count = int((self.accumulator + 1e-12) / self.dt)
        if count > self.max_steps:
            dropped = (count - self.max_steps) * self.dt
            self.dropped_seconds += dropped
            self.accumulator -= dropped
            count = self.max_steps
        for _ in range(count):
            step()
        self.accumulator = max(0.0, self.accumulator - count * self.dt)
        return count

    def single_step(self, step):
        self.set_paused(True)
        step()
