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


def follow_velocity(position, velocity, target, *, speed=7., acceleration=.8, responsiveness=.5):
    """40 Hz 阻尼跟随；调用者先约束 target，限位外距离不会积累能量。"""
    delta = target-position
    if responsiveness >= 1.:
        return delta
    # 50% 完整保留旧跟随；低档同时减弱追赶、加速和速度，0% 仍然能移动
    rate = min(1., .25+1.5*responsiveness)
    desired = limited(delta*(.24*rate), speed*rate)
    follow = limited(velocity + limited((desired-velocity)*(.5*rate), acceleration*rate*rate), speed*rate)
    # 高档逐渐增加当前目标的位置约束，避免靠无限增大弹簧或子步数换取跟手
    return follow.lerp(delta, (responsiveness-.5)*2) if responsiveness > .5 else follow
