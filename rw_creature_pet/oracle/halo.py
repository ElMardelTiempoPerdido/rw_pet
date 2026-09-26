"""Halo 的圆环/短条状态；纯视觉、独立随机流，不参与身体或珍珠受力。"""
from dataclasses import dataclass
from math import isfinite
from random import Random

from ..shared.geometry import Vec2
from .pearl_layout import PearlGroupRegion


def ease(value, target, amount):
    return target if abs(target-value) < .0001 else value+(target-value)*amount


def lerp_and_tick(value, target, amount, tick):
    value += (target-value)*amount
    return min(value+tick, target) if value < target else max(value-tick, target)


def valid_scale(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or not .6 <= value <= 1.4):
        raise ValueError('光环交互倍率必须在 0.6～1.4')
    return float(value)


@dataclass(slots=True)
class HaloRing:
    angle: float
    previous: float
    start: float
    target: float
    elapsed: int
    duration: int
    wait: int

    def step(self, random):
        self.previous = self.angle
        if self.elapsed < self.duration:
            self.elapsed += 1
            t = self.elapsed/self.duration
            self.angle = self.start+(self.target-self.start)*t*t*(3-2*t)
        elif self.wait > 0:
            self.wait -= 1
        else:
            self.start = self.angle
            self.target = self.angle+random.choice((-1, 1))*random.uniform(15, 90)
            self.elapsed, self.duration = 0, random.randint(60, 160)
            self.wait = random.randint(60, 240)


@dataclass(slots=True)
class HaloBit:
    fill: float
    previous: float
    target: float
    speed: float
    blink_counter: int = 0

    def set_to_max(self):
        self.target = 1.
        self.speed += (.25-self.speed)*.25
        self.blink_counter = 20

    def fill_at(self, alpha):
        # 原版先伸长，再以 2 帧显示 / 2 帧隐藏闪烁；不把零长度插值成淡出。
        if self.blink_counter % 4 > 1 and self.fill == self.target:
            return 0.
        return self.previous+(self.fill-self.previous)*alpha

    def step(self, random):
        self.previous = self.fill
        delta = self.target-self.fill
        if delta:
            self.fill = lerp_and_tick(self.fill, self.target, .03, self.speed)
        elif self.blink_counter > 0:
            self.blink_counter -= 1
        elif random.random() < 1/60:
            # 原版稳定后逐帧随机选目标；速度为均匀分母的倒数，并非均匀速度。
            self.target = random.random()
            self.speed = 1/(2+78*random.random())


class OracleHalo:
    COUNTS = (10, 30, 60)
    RING_RADII = (30., 40.)
    BIT_RADII = (35., 45., 55.)
    TICK_RATE = 40

    def __init__(self, world, preferred, scale=.8):
        self.random = Random(1054407)
        # 原版外圈半径最大 (5.5+3)*2*10=170，另含固定尺寸短条和像素余量。
        # 用固定包围框预留空间，避免实心化/扩张时中心来回挪动。
        self.extent = min(176*scale*1.4+2, min(world.inner.left, world.inner.top)/2-6)
        # 连窄调试窗口也为常用的 1.25 倍短反应留出余量。
        self.base_scale = min(scale, (self.extent-2)/(61*1.25))
        self.region = PearlGroupRegion(world, Vec2(self.extent, self.extent))
        self.center = self.previous_center = self.region.clamp(preferred)
        self.expand = self.previous_expand = self.target_expand = 1.
        self.push = self.previous_push = self.target_push = 0.
        self.white = self.previous_white = self.target_white = 0.
        self.interaction = self.previous_interaction = self.target_interaction = 1.
        self.pulse_scale, self.pulse_ticks = 1., 0
        self.rings, self.bits = [], []
        for count in self.COUNTS:
            angle = self.random.uniform(0, 360)
            self.rings.append(HaloRing(angle, angle, angle, angle, 0, 0,
                                       self.random.randint(20, 180)))
            row = []
            for _ in range(count):
                fill = self.random.random()
                row.append(HaloBit(fill, fill, fill, 0.))
            self.bits.append(row)
        self.revision = 0

    def flash_ring(self, index):
        if type(index) is not int or not 0 <= index < len(self.bits):
            raise ValueError('光环短条圈编号必须为 0、1 或 2')
        for bit in self.bits[index]:
            bit.set_to_max()

    def change_radii(self):
        self.target_expand = .8+1.2*self.random.random()**1.5
        self.target_push = float(-1+self.random.randrange(self.random.randrange(1, 6)))

    def pulse_fill(self):
        """只强制进入实心目标；持续和退出均沿用自然随机逻辑，不另设倒计时。"""
        self.target_white = 1.
        self.change_radii()

    def set_scale(self, scale=1.):
        """持续交互意愿；传 1 平滑恢复。不会累计乘倍率或接管自主行为。"""
        self.target_interaction = valid_scale(scale)
        self.pulse_ticks = 0

    def pulse(self, scale=1.25, hold_seconds=.8):
        """一次短反应：平滑接近倍率，保持结束后回到持续意愿。"""
        scale = valid_scale(scale)
        if (isinstance(hold_seconds, bool) or not isinstance(hold_seconds, (int, float))
                or not isfinite(hold_seconds) or not 0 < hold_seconds <= 30):
            raise ValueError('光环反应保持时间必须大于 0 且不超过 30 秒')
        self.pulse_scale = scale
        self.pulse_ticks = max(1, round(hold_seconds*self.TICK_RATE))

    def geometry_at(self, alpha=1.):
        expand = self.previous_expand+(self.expand-self.previous_expand)*alpha
        push = self.previous_push+(self.push-self.previous_push)*alpha
        interaction = self.previous_interaction+(self.interaction-self.previous_interaction)*alpha
        detail_scale = self.base_scale*interaction
        # 只限制半径；条宽/条长不跟随 expand、push 或碰到上限而收缩。
        radial_scale = min(detail_scale*expand,
                           (self.extent-2-5*detail_scale)/((5.5+push)*10))
        return radial_scale, push, detail_scale

    def scale_at(self, alpha=1.):
        return self.geometry_at(alpha)[0]

    def radius_at(self, ring, alpha=1.):
        scale, push, _ = self.geometry_at(alpha)
        return (3+ring+push)*10*scale

    def white_at(self, alpha=1.):
        return self.previous_white+(self.white-self.previous_white)*alpha

    def center_at(self, alpha=1.):
        return self.previous_center.lerp(self.center, alpha)

    def step(self, preferred, *, region=None):
        region = self.region if region is None else region
        self.previous_center = self.center
        target = region.clamp(preferred)
        candidate = target if (target-self.center).length() < .01 else self.center.lerp(target, .18)
        self.center = region.safe_move(self.center, candidate)
        self.previous_expand, self.previous_interaction = self.expand, self.interaction
        self.previous_push, self.previous_white = self.push, self.white
        self.expand = lerp_and_tick(self.expand, self.target_expand, .05, .0125)
        self.push = lerp_and_tick(self.push, self.target_push, .02, .025)
        self.white = lerp_and_tick(self.white, self.target_white, .07, 1/44)
        self.interaction = ease(self.interaction,
                                self.pulse_scale if self.pulse_ticks else self.target_interaction, .10)
        self.pulse_ticks = max(0, self.pulse_ticks-1)
        for ring, row in zip(self.rings, self.bits):
            ring.step(self.random)
            for bit in row:
                bit.step(self.random)
        if self.random.random() < 1/60:
            self.flash_ring(self.random.randrange(len(self.bits)))
        entered_white = False
        if self.random.random() < 1/160:
            target = float(self.random.random() < .125)
            entered_white = target == 1. and self.target_white < 1.
            self.target_white = target
        if (self.random.random() < 1/160) or entered_white:
            self.target_expand = (1. if self.random.random() < .5 and not entered_white
                                  else .8+1.2*self.random.random()**1.5)
        if (self.random.random() < 1/160) or entered_white:
            self.target_push = (0. if self.random.random() < .5 and not entered_white
                                else float(-1+self.random.randrange(self.random.randrange(1, 6))))
        self.revision += 1
