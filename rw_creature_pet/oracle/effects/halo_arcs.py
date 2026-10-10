"""光环电弧：附近边框、可进入中央的曲线，独立随机流与冷却，无物理反馈。"""
from dataclasses import dataclass
from math import ceil, sqrt
from random import Random

from ...shared.geometry import Bounds, Vec2
from ..graphics.appearance import normalized, perpendicular


def curve_length_bound(start, a, b, end, tolerance=.2, depth=10):
    """细分三次 Bezier，以紧贴实际弧长的上界校验长度；仅生成时调用。

    每段弦长为下界、控制多边形长为上界。误差随二分分配，避免稀疏采样
    漏掉回钩；达到递归上限时仍返回安全的上界。
    """
    polygon = (a-start).length()+(b-a).length()+(end-b).length()
    if depth == 0 or polygon-(end-start).length() <= tolerance:
        return polygon
    sa, ab, be = start.lerp(a, .5), a.lerp(b, .5), b.lerp(end, .5)
    left, right = sa.lerp(ab, .5), ab.lerp(be, .5)
    middle = left.lerp(right, .5)
    return (curve_length_bound(start, sa, left, middle, tolerance*.5, depth-1)
            + curve_length_bound(middle, right, be, end, tolerance*.5, depth-1))


@dataclass(frozen=True, slots=True)
class HaloArc:
    edge: int
    endpoint: Vec2
    region: Bounds
    wall_handle: Vec2
    radial_fraction: float
    source_edge: int
    initial_start: Vec2
    length_bound: float

    def controls(self, halo, alpha, maximum):
        center = halo.center_at(alpha)
        delta = self.endpoint-center
        radius = halo.radius_at(2.5, alpha)
        if delta.length() <= radius+2:
            return None
        start = center+normalized(delta)*radius
        # 原版的光环端控制柄沿径向，房间端控制柄在触发后固定。
        # 径向柄按当前弦长缩放，跟随人偶时不每帧重抽曲率或方向。
        a = start.lerp(self.endpoint, self.radial_fraction)
        if not self.region.contains(start) or not self.region.contains(a):
            return None
        # A=(1-f)*start+f*end；起点移动 Δ 后，弧长的增加不超过
        # (|f|+|1-f|)*|Δ|。显示时只做常量开销校验，不重新细分或拟合。
        growth = (abs(self.radial_fraction)+abs(1-self.radial_fraction))*(start-self.initial_start).length()
        if self.length_bound+growth > maximum:
            return None
        return start, a, self.wall_handle, self.endpoint


class HaloArcs:
    TICK_RATE = 40
    MAX_DISTANCE = 360.
    COOLDOWN_SECONDS = 60.
    EXTRA_WAIT_MEAN_SECONDS = 120.
    DURATION_TICKS = 12
    LINE_WIDTH = 3.
    OPACITY = .9
    WIDTH_DECAY = .9          # 与原版 lightUp 相同：每个逻辑帧缩到上帧的 90%
    BOW_FRACTION = (.08, .14)  # 期望峰值偏离弦线的距离 / 弦长
    MAX_BOW = 40.             # 普通弧的期望弯幅上限，逻辑像素
    SHAPE_WEIGHTS = (65, 25, 10)  # 普通弧 / 大弯弧 / 回钩；过长时收小形变
    WIDE_BOW_FRACTION = (.28, .60)
    MAX_WIDE_BOW = 120.
    HOOK_BOW_FRACTION = (.25, .50)
    MAX_HOOK_BOW = 110.

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

    def sample_shape(self):
        return self.random.choices(('arc', 'wide', 'hook'), weights=self.SHAPE_WEIGHTS)[0]

    def make_arc(self, halo, band, edge, primary, endpoint):
        delta = endpoint-halo.center
        direction = normalized(delta)
        start = halo.center+direction*halo.radius_at(2.5)
        length = delta.length()-halo.radius_at(2.5)
        if length <= 2 or length > self.MAX_DISTANCE or not band.contains(endpoint):
            return None
        shape = self.sample_shape()
        if shape == 'hook':
            # 控制点纵向越过终点、退回起点后方，才能出现真正的折返。
            radial_fraction = self.random.uniform(1.35, 1.9)
            wall_fraction = self.random.uniform(-.55, -.1)
            bow_range, bow_max = self.HOOK_BOW_FRACTION, self.MAX_HOOK_BOW
        elif shape == 'wide':
            radial_fraction = self.random.uniform(.45, 1.05)
            wall_fraction = self.random.uniform(-.1, 1.15)
            bow_range, bow_max = self.WIDE_BOW_FRACTION, self.MAX_WIDE_BOW
        else:
            radial_fraction = self.random.uniform(.25, .45)
            wall_fraction = self.random.uniform(.6, .8)
            bow_range, bow_max = self.BOW_FRACTION, self.MAX_BOW
        normal = perpendicular(direction)
        # 只有房间端柄横向偏移，Bezier 的峰值为该偏移的 4/9。
        bend = min(bow_max, length*self.random.uniform(*bow_range))*2.25
        inward = (Vec2(0, 1), Vec2(-1, 0), Vec2(0, -1), Vec2(1, 0))[primary]
        facing = normal.x*inward.x+normal.y*inward.y
        sign = self.random.choice((-1, 1)) if abs(facing) < 1e-6 else (1 if facing > 0 else -1)
        if abs(facing) >= 1e-6 and self.random.random() < .25:
            sign = -sign
        handle = start.lerp(endpoint, wall_fraction)+normal*(sign*bend)
        a = start.lerp(endpoint, radial_fraction)

        margin = 12.
        budget = max(length, self.MAX_DISTANCE-margin)
        bound = curve_length_bound(start, a, handle, endpoint)
        if bound > budget:
            # 向直线的两个控制点连续收缩，保留可用弯折；弧长是控制点的凸函数。
            # 两端不移动、不重抽方向，且为光环运动留出少量长度。
            straight_a, straight_b = start.lerp(endpoint, 1/3), start.lerp(endpoint, 2/3)
            desired_a, desired_b = a, handle
            desired_fraction = radial_fraction
            a, handle, radial_fraction, bound = straight_a, straight_b, 1/3, length
            low, high = 0., 1.
            for _ in range(10):
                middle = (low+high)*.5
                next_a, next_b = straight_a.lerp(desired_a, middle), straight_b.lerp(desired_b, middle)
                next_bound = curve_length_bound(start, next_a, next_b, endpoint)
                if next_bound <= budget:
                    low = middle
                    a, handle, bound = next_a, next_b, next_bound
                    radial_fraction = 1/3+(desired_fraction-1/3)*middle
                else:
                    high = middle

        # 只用作覆盖曲线的重绘范围及运动余量，允许进入中央或超出屏幕。
        # 控制点在此矩形内即保证整条曲线在内；工作区外由窗口自然裁切。
        points = (start, a, handle, endpoint)
        local = Bounds(min(p.x for p in points)-margin, min(p.y for p in points)-margin,
                       max(p.x for p in points)+margin, max(p.y for p in points)+margin)
        arc = HaloArc(edge, endpoint, local, handle, radial_fraction, primary, start, bound)
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
        # 相邻两边常驻候选，但落点仅取它们与当前边带相接的部分。
        # 此边带只限制连接对象；曲线及控制柄可经过中央，仍不连接对边。
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
