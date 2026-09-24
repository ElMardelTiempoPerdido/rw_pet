"""间歇选择并保留空间观察点；不改变导航或躯干姿态。"""
from math import cos, sin
from random import Random

from ..shared.geometry import Vec2


class Gaze:
    def __init__(self):
        self.ambient_target = None
        self.hold_ticks = 0
        self.point = None
        self._age = 0
        # 独立的确定性调试序列，不消耗运动/颜色随机数，也不模拟 Unity 生物 ID。
        self._random = Random(731)

    def update(self, origin, axis, world, explicit=None):
        delta = self.ambient_target-origin if self.ambient_target is not None else Vec2()
        distance = delta.length()
        behind = distance > 0 and (delta.x*axis.x + delta.y*axis.y)/distance < -.15
        # 边界可能把观察点裁到很近；短暂冷却避免连续转向时每帧重新抽点。
        invalid = distance < 28 or distance > 280 or behind
        if self.hold_ticks <= 0 or (self._age >= 20 and invalid):
            angle = self._random.uniform(-.6, .6)
            direction = Vec2(axis.x*cos(angle)-axis.y*sin(angle),
                             axis.x*sin(angle)+axis.y*cos(angle))
            candidate = origin + direction*self._random.uniform(100, 160)
            self.ambient_target = Vec2(max(6, min(world.width-6, candidate.x)),
                                       max(6, min(world.floor_y-6, candidate.y)))
            self.hold_ticks = self._random.randint(100, 200)
            self._age = 0
        self.hold_ticks -= 1
        self._age += 1
        # 手动观察期间也维护自动观察的独立节奏，结束后平滑恢复。
        self.point = explicit if explicit is not None else self.ambient_target
        return self.point
