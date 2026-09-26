"""两圈反向椭圆环绕：共享软牵引锚点和安全包围框，成员等相位分布。

原版 PebblesPearl 按 orbitCircle 共享相位和椭圆参数、奇偶圈反向。
桌面缩小半径与角速度；只规划整组路径，不逐珠搜索邻居或规划路径。
"""
from dataclasses import dataclass
from math import cos, pi, radians, sin, tau
from random import Random

from ..shared.geometry import Vec2
from .pearl import PearlColorSlot, PearlState
from .pearl_layout import PearlGroupRegion, balanced_colors, group_follow_boxes


@dataclass(frozen=True, slots=True)
class OrbitPearl:
    circle: int
    index: int
    phase: float
    glyph_id: int
    color_slot: PearlColorSlot


class PearlOrbits:
    # 单位为弧度/tick，40 Hz。桌面内圈约 7.5 秒一周，外圈约 11.25 秒。
    ANGULAR_SPEEDS = (radians(1.2), radians(-.8))
    AXES = (radians(-25), radians(30))
    FLATTEN = (.8, .72)
    LABEL_OFFSET = Vec2(5.5, -5.5)  # 右上字形使可见包围框中心偏离轨道中心。
    TARGET_HYSTERESIS = 3.

    def __init__(self, world, body_region, center, halo_center, width, height, inner_count, outer_count):
        for count in (inner_count, outer_count):
            if type(count) is not int or not 0 <= count <= 32:
                raise ValueError('每圈数量必须为 0～32 的整数')
        if not inner_count+outer_count:
            raise ValueError('至少开启一颗环绕珠')
        self.body_region, self.width, self.height = body_region, width, height
        # 整圈 + 23px 珠体/字形外框 + 16px 锚点转弯走廊。
        outer_radius = min(70., (min(world.inner.left, world.inner.top)-39.)/2,
                           min(width, height)/4-2.)
        self.radii = (min(35., outer_radius*.60), outer_radius)
        radius = outer_radius if outer_count else self.radii[0]
        self.half_size = Vec2(radius+11.5, radius+11.5)
        self.region = PearlGroupRegion(world, self.half_size)
        self.phases = [0., pi/2]
        members = []
        for circle, count in enumerate((inner_count, outer_count)):
            colors = balanced_colors(count, ((3, 2, 1), (1, 0, 1))[circle],
                                      ((0, 0, 1, 1, 0, 2), (0, 2))[circle])
            random = Random(12844+circle)
            members.extend(OrbitPearl(circle, i, tau*i/count, random.randrange(14), color)
                           for i, color in enumerate(colors))
        self.pearls = tuple(members)
        self.anchor = PearlState(self._target(center, halo_center), world, self.region)
        self._replan_ticks = 0
        self.revision = 0
        self.positions = self.previous_positions = self._positions()

    @property
    def settled(self):
        return False  # 开启的轨道持续旋转；不可用于判定观察行为能否启动。

    def _target(self, center, halo_center):
        boxes = group_follow_boxes(center, self.body_region, self.region, self.width, self.height, self.half_size)
        preferred = halo_center+self.LABEL_OFFSET
        return min((box.clamp(preferred) for box in boxes), key=lambda p: (p-preferred).length())

    def _positions(self):
        center = self.anchor.position-self.LABEL_OFFSET
        positions = []
        for member in self.pearls:
            circle = member.circle
            phase = self.phases[circle]+member.phase
            radius, axis = self.radii[circle], self.AXES[circle]
            x, y = cos(phase)*radius, sin(phase)*radius*self.FLATTEN[circle]
            positions.append(center+Vec2(x*cos(axis)-y*sin(axis), x*sin(axis)+y*cos(axis)))
        return tuple(positions)

    def step(self, center, halo_center):
        self.previous_positions = self.positions
        self._replan_ticks = max(0, self._replan_ticks-1)
        target = self._target(center, halo_center)
        if self._replan_ticks == 0 and (target-self.anchor.target).length() > self.TARGET_HYSTERESIS:
            self.anchor.home = target
            self.anchor._set_target(target, catch_up=True)
            self._replan_ticks = self.anchor.REPLAN_TICKS
        self.anchor.step()
        for circle in (0, 1):
            self.phases[circle] = (self.phases[circle]+self.ANGULAR_SPEEDS[circle]) % tau
        self.positions = self._positions()
        self.revision += 1

    def samples(self, alpha=1.):
        for previous, current, member in zip(self.previous_positions, self.positions, self.pearls):
            yield previous.lerp(current, alpha), member.glyph_id, member.color_slot
