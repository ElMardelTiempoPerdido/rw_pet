"""与 Qt、生物和墙钟无关的抓取会话及固定 tick 柔性跟随。"""
from dataclasses import dataclass
from math import isfinite

from ..shared.geometry import Vec2


def limited(vector, maximum):
    return vector * min(1., maximum / max(vector.length(), 1e-12))


def finite(point):
    return isfinite(point.x) and isfinite(point.y)


@dataclass(frozen=True, slots=True)
class DragHandle:
    key: object
    position: Vec2


class DragController:
    """只有 press 调用命中函数；move 永远不能新建抓取。"""
    def __init__(self):
        self.handle = None
        self.pointer = Vec2()
        self.offset = Vec2()

    @property
    def active(self):
        return self.handle is not None

    @property
    def target(self):
        return self.pointer + self.offset

    def press(self, point, pick):
        if self.active or not finite(point):
            return False
        handle = pick(point)
        if handle is None:
            return False
        self.handle, self.pointer = handle, point
        self.offset = handle.position-point
        return True

    def move(self, point):
        if self.active and finite(point):
            self.pointer = point

    def release(self):
        handle, self.handle = self.handle, None
        return handle


def follow_velocity(position, velocity, target, *, speed=7., acceleration=.8):
    """40 Hz 阻尼跟随；调用者先约束 target，限位外距离不会积累能量。"""
    desired = limited((target-position)*.24, speed)
    return limited(velocity + limited((desired-velocity)*.5, acceleration), speed)
