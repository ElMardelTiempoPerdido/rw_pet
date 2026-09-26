"""固定悬浮珠及卫星树：局部保持悬浮点，超距整族迁移。

原版三种卫星组合：18 单卫星、38 双卫星、42 + 12 二级卫星。
预留整棵卫星树的全相位外形，避免为子珠逐帧规划或逐颗夹边。
"""
from dataclasses import dataclass
from math import cos, radians, sin, tau
from random import Random

from ..shared.geometry import Bounds, Vec2
from .navigation import EdgeRegion
from .pearl import PearlState
from .pearl_layout import PearlGroupRegion, balanced_colors, group_follow_boxes


class FamilyRegion(EdgeRegion):
    """根珠坐标的可行区域；包含卫星半径、珠体和右上投影。"""

    def __init__(self, world, radius):
        a, b = radius+6, radius+17
        w, h, inner = world.width, world.height, world.inner
        self.outer = Bounds(a, b, w-b, h-a)
        self.hole = Bounds(inner.left-b, inner.top-a, inner.right+a, inner.bottom+b)
        self.boxes = (Bounds(a, b, w-b, self.hole.top), Bounds(self.hole.right, b, w-b, h-a),
                      Bounds(a, self.hole.bottom, w-b, h-a), Bounds(a, b, self.hole.left, h-a))


class FixedPearl(PearlState):
    LABEL_OFFSET = Vec2(5.5, -5.5)

    def __init__(self, preferred, world, body_region, center, width, height, radius, glyph, color):
        self.family_radius = radius
        self.body_region = body_region
        self.half_size = Vec2(radius+11.5, radius+11.5)
        self.group_region = PearlGroupRegion(world, self.half_size)
        region = FamilyRegion(world, radius) if radius else body_region
        home = self.nearby_home(preferred, center, region, width, height)
        super().__init__(home, world, region, glyph, color_slot=color)
        self.follow_home(center, width, height)

    def nearby_home(self, point, center, region, width, height, *, inset=False):
        if not self.family_radius:
            return PearlState.nearby_home(point, center, region, width, height, inset=inset)
        boxes = group_follow_boxes(center, self.body_region, self.group_region, width, height, self.half_size)
        candidates = []
        for box in boxes:
            dx = min(32., (box.right-box.left)*.25) if inset else 0.
            dy = min(32., (box.bottom-box.top)*.25) if inset else 0.
            q = Bounds(box.left+dx, box.top+dy, box.right-dx, box.bottom-dy).clamp(point+self.LABEL_OFFSET)
            candidates.append(q-self.LABEL_OFFSET)
        return min(candidates, key=lambda p: (p-point).length())

    def follow_home(self, center, width, height, *, allow_motion=True):
        if not self.family_radius:
            return super().follow_home(center, width, height, allow_motion=allow_motion)
        self.follow_bounds = Bounds(center.x-width/2, center.y-height/2, center.x+width/2, center.y+height/2)
        self._replan_ticks = max(0, self._replan_ticks-1)
        boxes = group_follow_boxes(center, self.body_region, self.group_region, width, height, self.half_size)
        if not any(box.contains(self.home+self.LABEL_OFFSET) for box in boxes):
            home = self.nearby_home(self.home, center, self.region, width, height, inset=True)
            if home != self.home:
                self.home = home
                self.revision += 1
        if allow_motion and self.returning_home and self.target != self.home and self._replan_ticks == 0:
            self._set_target(self.home, catch_up=True)
            self._replan_ticks = self.REPLAN_TICKS


@dataclass(frozen=True, slots=True)
class Satellite:
    root: int
    parent: int | None  # None 为根珠；否则为更早创建的卫星编号。
    radius: float
    phase: float
    speed: float
    axis: float
    glyph_id: int
    color_slot: int


class FixedPearls:
    ROOT_COLORS = (1, 1, 2, 2, 0, 2, 2, 1, 1, 0, 0)
    SATELLITE_COLORS = (0, 1, 2, 1, 0)

    def __init__(self, world, body_region, center, normal, width, height, fixed_count, satellite_count):
        if any(type(n) is not int or not 0 <= n <= 32 for n in (fixed_count, satellite_count)):
            raise ValueError('固定珠和卫星珠数量必须为 0～32 的整数')
        self.width, self.height = width, height
        # 没有母珠时不隐式补珠；保留配置，下次开启固定珠再恢复卫星。
        satellite_count = satellite_count if fixed_count else 0
        specs, reaches = [], [0.]*fixed_count
        for i in range(satellite_count):
            block, role = divmod(i, 5)
            family = (0, 1, 1, 2, 2)[role]
            root = ((1, 2, 10)[family] if fixed_count == 11 and block == 0
                    else (block*3+family) % fixed_count)
            parent = i-1 if role == 4 else None
            radius = (18., 38., 38., 42., 12.)[role]
            speed = .8 if role == 3 else 1.2  # 桌面延续慢环绕；42 轨道保留原版 0.8。
            reach = radius+(42. if parent is not None else 0.)
            reaches[root] = max(reaches[root], reach)
            specs.append((root, parent, radius, speed, family))
        maximum = min((min(world.inner.left, world.inner.top)-39)/2, min(width, height)/4-2)
        scales = [min(1., maximum/max(1., r)) for r in reaches]
        colors = balanced_colors(fixed_count, (3, 4, 4), self.ROOT_COLORS)
        random = Random(12846)
        tangent = Vec2(normal.y, -normal.x)
        roots = []
        for i, color in enumerate(colors):
            along = (90., 138.)[i] if i < 2 else -120.+(i % 7)*40.
            preferred = center+tangent*along+Vec2(0, -12+(i//7)*20.)
            # 靠角初生时优先选可容纳的一侧，保持与原观察调试一致的可达性。
            if i == 0:
                candidates = [body_region.clamp(center+tangent*sign*90+Vec2(0, -12)) for sign in (1, -1)]
                preferred = max(candidates, key=lambda p: (p-center).length())
            roots.append(FixedPearl(preferred, world, body_region, center, width, height,
                                    reaches[i]*scales[i], random.randrange(14), color))
        self.roots = tuple(roots)
        colors = balanced_colors(satellite_count, (2, 2, 1), self.SATELLITE_COLORS)
        satellites = []
        for i, ((root, parent, radius, speed, family), color) in enumerate(zip(specs, colors)):
            # 同一母珠、半径的同级卫星共享相位，均匀分布；无邻居两两遍历。
            peers = [j for j, spec in enumerate(specs) if spec[:4] == specs[i][:4]]
            phase = tau*peers.index(i)/len(peers)+family*.8
            satellites.append(Satellite(root, parent, radius*scales[root], phase, radians(speed),
                                        radians((-25, 30, -40)[family]), random.randrange(14), color))
        self.satellites = tuple(satellites)
        self.tick = self._satellite_revision = 0
        self.positions = self.previous_positions = self._positions()

    @property
    def roots_settled(self):
        return all(p.settled for p in self.roots)

    @property
    def settled(self):
        return self.roots_settled and not self.satellites

    @property
    def revision(self):
        return sum(p.revision for p in self.roots)+self._satellite_revision

    def _positions(self):
        positions = []
        for s in self.satellites:
            parent = self.roots[s.root].position if s.parent is None else positions[s.parent]
            angle = (s.phase+self.tick*s.speed) % tau
            x, y = cos(angle)*s.radius, sin(angle)*s.radius*.8
            positions.append(parent+Vec2(x*cos(s.axis)-y*sin(s.axis), x*sin(s.axis)+y*cos(s.axis)))
        return tuple(positions)

    def sync_positions(self):
        """工作区重建后前后帧一致，卫星跟着新坐标中的母珠初始化。"""
        self.positions = self.previous_positions = self._positions()

    def step(self, center, controlled=None):
        self.previous_positions = self.positions
        for pearl in self.roots:
            pearl.follow_home(center, self.width, self.height, allow_motion=pearl is not controlled)
            pearl.step()
        if self.satellites:
            self.tick += 1
            self.positions = self._positions()
            self._satellite_revision += 1

    def samples(self, alpha=1.):
        for pearl in self.roots:
            yield pearl.sample(alpha), pearl.glyph_id, pearl.color_slot
        for before, after, member in zip(self.previous_positions, self.positions, self.satellites):
            yield before.lerp(after, alpha), member.glyph_id, member.color_slot
