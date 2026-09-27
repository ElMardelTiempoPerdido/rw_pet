"""克制的光环电弧：连接附近工作区边框，独立随机流与冷却，无物理反馈。"""
from dataclasses import dataclass
from math import ceil, sqrt
from random import Random

from ..shared.geometry import Bounds, Vec2
from .appearance import normalized, perpendicular


def ray_room(region, origin, direction):
    """沿给定方向还可移动的距离；缩短控制柄而不改变其方向。"""
    reach = float('inf')
    for value, component, low, high in ((origin.x, direction.x, region.left, region.right),
                                       (origin.y, direction.y, region.top, region.bottom)):
        if abs(component) > 1e-9:
            reach = min(reach, ((high if component > 0 else low)-value)/component)
    return max(0., reach)


@dataclass(frozen=True, slots=True)
class HaloArc:
    edge: int
    endpoint: Vec2
    region: Bounds
    wall_handle: Vec2
    radial_fraction: float
    source_edge: int

    def controls(self, halo, alpha, maximum):
        center = halo.center_at(alpha)
        delta = self.endpoint-center
        radius = halo.radius_at(2.5, alpha)
        if delta.length() <= radius+2:
            return None
        start = center+normalized(delta)*radius
        if not self.region.contains(start):
            return None
        # 原版的光环端控制柄沿径向，房间端控制柄在触发后固定。
        # 径向柄按当前弦长缩放，跟随人偶时不每帧重抽曲率或方向。
        a = start.lerp(self.endpoint, self.radial_fraction)
        points = (start, a, self.wall_handle, self.endpoint)
        # 控制多边形长度是整条三次曲线弧长的上界，比只限制两端距离更保守。
        return points if sum((q-p).length() for p, q in zip(points, points[1:])) <= maximum else None


class HaloArcs:
    TICK_RATE = 40
    MAX_DISTANCE = 360.
    COOLDOWN_SECONDS = 60.
    EXTRA_WAIT_MEAN_SECONDS = 120.
    DURATION_TICKS = 12
    LINE_WIDTH = 4.
    OPACITY = .9
    WIDTH_DECAY = .9          # 与原版 lightUp 相同：每个逻辑帧缩到上帧的 90%
    BOW_FRACTION = (.08, .14)  # 期望峰值偏离弦线的距离 / 弦长
    MAX_BOW = 40.             # 逻辑像素；实际还受边带空间和总长度限制

    def __init__(self, world, max_count=3):
        self.world, self.max_count = world, max_count
        self.random = Random(150319)
        self.arcs = ()
        self.age = 0
        self.revision = 0
        self.wait = self.next_wait()

    def next_wait(self):
        return ceil(self.TICK_RATE*(self.COOLDOWN_SECONDS
                    + self.random.expovariate(1/self.EXTRA_WAIT_MEAN_SECONDS)))

    def clear(self):
        if self.arcs:
            self.arcs = ()
            self.revision += 1

    def edge_regions(self):
        w, inner, pad = self.world, self.world.inner, self.LINE_WIDTH*.5
        return (Bounds(pad, pad, w.width-pad, inner.top-pad),
                Bounds(inner.right+pad, pad, w.width-pad, w.height-pad),
                Bounds(pad, inner.bottom+pad, w.width-pad, w.height-pad),
                Bounds(pad, pad, inner.left-pad, w.height-pad))

    def endpoint_range(self, halo, band, edge):
        """目标边框与当前边带的交段；搜索半径随 MAX_DISTANCE 增长。"""
        center = halo.center
        horizontal = edge % 2 == 0
        wall = (band.top, band.right, band.bottom, band.left)[edge]
        normal = wall-(center.y if horizontal else center.x)
        reach = halo.radius_at(2.5)+self.MAX_DISTANCE
        if abs(normal) >= reach:
            return None
        span = sqrt(reach*reach-normal*normal)
        along = center.x if horizontal else center.y
        lo = max(band.left if horizontal else band.top, along-span)
        hi = min(band.right if horizontal else band.bottom, along+span)
        return (lo, hi) if hi > lo else None

    def sample_count(self):
        # 手动只跳过冷却；两种触发共用数量分布，并覆盖完整配置范围。
        return self.random.choices(range(1, self.max_count+1),
                                   weights=range(self.max_count, 0, -1))[0]

    def make_arc(self, halo, band, edge, primary, endpoint):
        delta = endpoint-halo.center
        direction = normalized(delta)
        start = halo.center+direction*halo.radius_at(2.5)
        length = delta.length()-halo.radius_at(2.5)
        if length <= 2 or length > self.MAX_DISTANCE or not band.contains(start):
            return None
        radial_fraction = self.random.uniform(.25, .45)
        a = start.lerp(endpoint, radial_fraction)
        foot = endpoint-direction*(length*self.random.uniform(.2, .4))
        normal = perpendicular(direction)
        # 只有房间端柄横向偏移，Bezier 的峰值为该偏移的 4/9。
        bend = min(self.MAX_BOW, length*self.random.uniform(*self.BOW_FRACTION))*2.25
        sign = self.random.choice((-1, 1))
        room = ray_room(band, foot, normal*sign)
        opposite = ray_room(band, foot, normal*-sign)
        if room < bend*.5 and opposite > room:
            sign, room = -sign, opposite
        bend = min(bend, room)
        offset = normal*(sign*bend)
        handle = band.clamp(foot+offset)

        def polygon_length(b):
            return (a-start).length()+(b-a).length()+(endpoint-b).length()

        margin = 12.
        budget = max(length, self.MAX_DISTANCE-margin)
        if polygon_length(handle) > budget:
            # 只在创建时收缩控制柄，为长线保留可用的弧度；每帧仅做合法性检查。
            # 留出少量长度供光环继续移动，避免长弧一出现就因微小位移消失。
            low, high = 0., 1.
            for _ in range(10):
                middle = (low+high)*.5
                if polygon_length(foot+offset*middle) <= budget:
                    low = middle
                else:
                    high = middle
            handle = band.clamp(foot+offset*low)

        # 先允许控制柄使用完整边带，再据真实形状收紧脏区；12px 仅留给运动。
        points = (start, a, handle, endpoint)
        local = Bounds(max(band.left, min(p.x for p in points)-margin),
                       max(band.top, min(p.y for p in points)-margin),
                       min(band.right, max(p.x for p in points)+margin),
                       min(band.bottom, max(p.y for p in points)+margin))
        arc = HaloArc(edge, endpoint, local, handle, radial_fraction, primary)
        return arc if arc.controls(halo, 1., self.MAX_DISTANCE) is not None else None

    def trigger(self, halo, *, manual=False):
        if self.arcs or (not manual and self.wait > 0):
            return 0
        # 失败的自然尝试也重新排期，避免无端点时每帧搜索；手动失败不消耗冷却。
        if not manual:
            self.wait = self.next_wait()
        center, w = halo.center, self.world
        distances = (center.y, w.width-center.x, w.height-center.y, center.x)
        primary = min(range(4), key=distances.__getitem__)
        regions = self.edge_regions()
        band = regions[primary]
        if not band.contains(center):
            return 0
        # 相邻两边常驻候选，但落点仅取它们与当前边带相接的部分。
        # 因而连向邻边也能保持整个控制凸包在同一边带，不斜穿中央。
        ranges = {edge: span for edge in (primary, (primary-1) % 4, (primary+1) % 4)
                  if (span := self.endpoint_range(halo, band, edge)) is not None}
        if not ranges:
            return 0
        count = self.sample_count()
        adjacent_limit = self.max_count//2
        adjacent_count = 0
        arcs = []
        for _ in range(count*20):
            edges = [edge for edge in ranges if edge == primary or adjacent_count < adjacent_limit]
            if not edges:
                break
            edge = self.random.choice(edges)
            along = self.random.uniform(*ranges[edge])
            endpoint = band.clamp((Vec2(along, band.top) if edge == 0 else
                                   Vec2(band.right, along) if edge == 1 else
                                   Vec2(along, band.bottom) if edge == 2 else Vec2(band.left, along)))
            if any((endpoint-arc.endpoint).length() < 14 for arc in arcs):
                continue
            arc = self.make_arc(halo, band, edge, primary, endpoint)
            if arc is not None:
                arcs.append(arc)
                adjacent_count += edge != primary
            if len(arcs) == count:
                break
        if arcs:
            self.arcs, self.age = tuple(arcs), 0
            self.revision += 1
            if manual:
                self.wait = self.next_wait()
        return len(arcs)

    def curves(self, halo, alpha=1.):
        return tuple(points for arc in self.arcs
                     if (points := arc.controls(halo, alpha, self.MAX_DISTANCE)) is not None)

    def width_at(self, alpha=1.):
        if max(0., self.age-1+alpha) >= self.DURATION_TICKS:
            return 0.
        previous = self.LINE_WIDTH*self.WIDTH_DECAY**max(0, self.age-1)
        current = self.LINE_WIDTH*self.WIDTH_DECAY**self.age
        return previous+(current-previous)*alpha

    def step(self, halo, enabled=True):
        self.wait = max(0, self.wait-1)
        if not enabled:
            self.clear()
            return
        if self.arcs:
            self.age += 1
            self.revision += 1
            if self.age > self.DURATION_TICKS or not self.curves(halo):
                self.clear()
        elif self.wait == 0:
            self.trigger(halo)

    def inherit_cooldown(self, previous):
        # 尺寸变化丢弃旧端点，保留全局等待，防止重建绕过冷却。
        self.wait = previous.wait
        self.random.setstate(previous.random.getstate())
