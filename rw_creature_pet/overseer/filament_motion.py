"""触须独立的间歇绕转与张合，参考 OverseerGraphics.myceliaMovements"""
from dataclasses import dataclass
from math import cos, pi, sin
from random import Random


@dataclass(slots=True)
class _Motion:
    value: float
    start: float
    goal: float
    progress: float = 1.
    increment: float = 0.

    @classmethod
    def at(cls, value):
        return cls(value, value, value)

    def step(self, rng, probability, speed, *, rotation=False):
        if self.progress >= 1 and rng.random() < probability:
            self.start = self.value
            self.goal = (self.value+rng.random()**3*.8*rng.choice((-1, 1))
                         if rotation else rng.random())
            self.progress = 0.
            self.increment = speed/max(abs(self.goal-self.start), 1e-8)
        self.progress = min(1., self.progress+self.increment)
        # 原版 Custom.SCurve(t, 0.5)，两段有理曲线在中点连续衔接
        t = self.progress
        weight = .5*t/(1.5-2*t) if t < .5 else .5+.75*(2*t-1)/(2*t-.5)
        self.value = self.start+(self.goal-self.start)*weight


class FilamentMotion:
    ROTATION_PROBABILITY = 1/80  # 40 Hz 下，完成一次转动后平均等待约 2 秒
    ROTATION_SPEED = .01  # 每 tick 的名义转数，实际速度由缓动曲线决定
    SPREAD_PROBABILITY = 1/20
    SPREAD_SPEED = .02
    FRIEND_ORBIT_SCALE = .35  # 观察时的双须绕转幅度，平时仍使用原 C/S 弧

    def __init__(self, seed):
        self.random = Random(seed ^ 0xF11A6E17)
        self.rotation = _Motion.at(self.random.random())
        self.spread = _Motion.at(self.random.random())

    def step(self):
        self.rotation.step(self.random, self.ROTATION_PROBABILITY, self.ROTATION_SPEED, rotation=True)
        self.spread.step(self.random, self.SPREAD_PROBABILITY, self.SPREAD_SPEED)

    @property
    def radius(self):
        return 25-10*self.spread.value

    def ring_offsets(self, model, count, radius, back=0.):
        """绕视线轴的引导环，按原版 MyceliaPosTo2D 旋转后投影到当前边缘局部坐标"""
        gaze, _ = model.head_gaze()
        # 使用边缘局部坐标，四条边旋转后的姿态仍保持一致
        pitch = -(gaze.x*model.normal.x+gaze.y*model.normal.y)
        yaw = gaze.x*model.tangent.x+gaze.y*model.tangent.y
        cp, sp, cy, sy = cos(pitch), sin(pitch), cos(yaw), sin(yaw)
        phase = self.rotation.value*2*pi
        offsets = []
        for index in range(count):
            angle = phase+index*2*pi/count
            x, y = cos(angle)*radius, sin(angle)*radius
            projected_y, z = y*cp-back*sp, y*sp+back*cp
            projected_x = z*sy+x*cy
            offsets.append(model.tangent*projected_x+model.normal*projected_y)
        return offsets
