"""Oracle 边缘导航。几何路径、弧长计时和底座控制均独立于 Qt。

四边区域是非凸的环，路径用相邻边的角落连接，并用 Bezier 凸包验证整段安全。
轨道参数以实际长度表示，矩形长短边速度一致；连续参数允许跨过周长接缝。
"""
from bisect import bisect_right
from dataclasses import dataclass
from heapq import heappop, heappush
from math import atan2, ceil, cos, pi, sin, sqrt, tan

from ..shared.geometry import Bounds, Vec2


def normalized(v, fallback=Vec2(1, 0)):
    return v * (1 / v.length()) if v.length() > 1e-9 else fallback


def approach(value, target, step):
    return value + max(-step, min(step, target - value))


class EdgeRegion:
    def __init__(self, world, body=True, reach=None):
        m = world.body_margin if body else 7.
        pad = world.body_margin if body else world.rail_inset
        inner = world.inner
        self.outer = Bounds(pad, pad, world.width - pad, world.height - pad)
        self.hole = Bounds(inner.left - m, inner.top - m, inner.right + m, inner.bottom + m)
        if reach is not None:
            # 大工作区 / 宽活动带中，几何上属于边缘的深处也可能超出所有
            # 底座位置的可达范围。收窄规划走廊，避免生成永远走不到的终点。
            depth = world.rail_inset + reach - 16
            self.hole = Bounds(min(self.hole.left, depth), min(self.hole.top, depth),
                               max(self.hole.right, world.width - depth),
                               max(self.hole.bottom, world.height - depth))
        self.boxes = (
            Bounds(pad, pad, world.width - pad, self.hole.top),
            Bounds(self.hole.right, pad, world.width - pad, world.height - pad),
            Bounds(pad, self.hole.bottom, world.width - pad, world.height - pad),
            Bounds(pad, pad, self.hole.left, world.height - pad),
        )

    def contains(self, p, tolerance=1e-6):
        return any(box.contains(p, tolerance) for box in self.boxes)

    def clamp(self, p):
        return min((box.clamp(p) for box in self.boxes), key=lambda q: (q - p).length())

    def segment_safe(self, a, b):
        if not (self.contains(a) and self.contains(b)):
            return False
        # Liang–Barsky：与中央开矩形相交才算越界；切于边界的线允许通过。
        lo, hi = 0., 1.
        for start, delta, lower, upper in ((a.x, b.x - a.x, self.hole.left + 1e-7, self.hole.right - 1e-7),
                                           (a.y, b.y - a.y, self.hole.top + 1e-7, self.hole.bottom - 1e-7)):
            if abs(delta) < 1e-12:
                if not lower <= start <= upper:
                    return True
            else:
                u, v = sorted(((lower - start) / delta, (upper - start) / delta))
                lo, hi = max(lo, u), min(hi, v)
                if lo > hi:
                    return True
        return lo > hi

    def safe_move(self, previous, candidate):
        candidate = self.clamp(candidate)
        if self.segment_safe(previous, candidate):
            return candidate
        options = [box.clamp(candidate) for box in self.boxes if box.contains(previous)]
        return min(options, key=lambda p: (p - candidate).length()) if options else previous

    def separate_segment(self, a, b, fixed_a=False, fixed_b=False):
        if self.segment_safe(a, b):
            return a, b
        options = []
        # 用穿过禁区角点外侧的切线作最小转动。直接把两端都投到同一条边，
        # 会把本来只穿入零点几单位的跨角杆件一下挪动几十单位。
        h = self.hole
        corners = (Vec2(h.left-.002, h.top-.002), Vec2(h.right+.002, h.top-.002),
                   Vec2(h.right+.002, h.bottom+.002), Vec2(h.left-.002, h.bottom+.002))
        length = (b - a).length()
        for corner in corners:
            if not fixed_b:
                y = self.clamp(a + normalized(corner - a) * length)
                if self.segment_safe(a, y):
                    options.append(((b - y).length(), a, y))
            if not fixed_a:
                x = self.clamp(b + normalized(corner - b) * length)
                if self.segment_safe(x, b):
                    options.append(((a - x).length(), x, b))
        for box in self.boxes:
            if (fixed_a and not box.contains(a)) or (fixed_b and not box.contains(b)):
                continue
            x, y = (a if fixed_a else box.clamp(a)), (b if fixed_b else box.clamp(b))
            options.append(((a - x).length() + (b - y).length(), x, y))
        if not options:
            return a, b
        _, x, y = min(options, key=lambda item: item[0])
        return x, y


@dataclass(frozen=True, slots=True)
class RailPiece:
    start: Vec2
    end: Vec2
    length: float
    center: Vec2 | None = None
    angle: float = 0.

    def sample(self, distance, radius):
        t = max(0., min(1., distance / self.length))
        if self.center is None:
            return self.start.lerp(self.end, t), normalized(self.end - self.start)
        angle = self.angle + t * pi / 2
        return self.center + Vec2(cos(angle), sin(angle)) * radius, Vec2(-sin(angle), cos(angle))


class RoundedRail:
    def __init__(self, world):
        l, t = world.rail_inset, world.rail_inset
        r, b = world.width - l, world.height - t
        self.radius = min(32., world.height * world.edge_fraction * .30)
        d = self.radius
        self.pieces = (
            RailPiece(Vec2(l + d, t), Vec2(r - d, t), r - l - 2*d),
            RailPiece(Vec2(r - d, t), Vec2(r, t + d), pi*d/2, Vec2(r - d, t + d), -pi/2),
            RailPiece(Vec2(r, t + d), Vec2(r, b - d), b - t - 2*d),
            RailPiece(Vec2(r, b - d), Vec2(r - d, b), pi*d/2, Vec2(r - d, b - d), 0),
            RailPiece(Vec2(r - d, b), Vec2(l + d, b), r - l - 2*d),
            RailPiece(Vec2(l + d, b), Vec2(l, b - d), pi*d/2, Vec2(l + d, b - d), pi/2),
            RailPiece(Vec2(l, b - d), Vec2(l, t + d), b - t - 2*d),
            RailPiece(Vec2(l, t + d), Vec2(l + d, t), pi*d/2, Vec2(l + d, t + d), pi),
        )
        self.ends = []
        total = 0.
        for piece in self.pieces:
            total += piece.length
            self.ends.append(total)
        self.length = total

    def sample(self, s):
        s %= self.length
        i = min(len(self.pieces) - 1, bisect_right(self.ends, s))
        return self.pieces[i].sample(s - (self.ends[i - 1] if i else 0), self.radius)

    def normal(self, s):
        _, tangent = self.sample(s)
        return Vec2(-tangent.y, tangent.x)

    def delta(self, start, end):
        return (end - start + self.length / 2) % self.length - self.length / 2

    def project(self, point, reference=None):
        candidates, offset = [], 0.
        for piece in self.pieces:
            if piece.center is None:
                v, direction = point - piece.start, normalized(piece.end - piece.start)
                distance = max(0., min(piece.length, v.x * direction.x + v.y * direction.y))
            else:
                v = point - piece.center
                angle = atan2(v.y, v.x)
                angle = piece.angle + (angle - piece.angle + pi) % (2*pi) - pi
                distance = max(0., min(pi/2, angle - piece.angle)) * self.radius
            p, _ = piece.sample(distance, self.radius)
            s = offset + distance
            candidates.append(((p - point).length(), s))
            offset += piece.length
        # 在等距的角落使用前一次位置破除平局，避免环参数跳到另一边。
        _, s = min(candidates, key=lambda item: (round(item[0], 7),
                    abs(self.delta(reference, item[1])) if reference is not None else item[1]))
        return s if reference is None else reference + self.delta(reference, s)


@dataclass(frozen=True, slots=True)
class Bezier:
    a: Vec2
    b: Vec2
    c: Vec2
    d: Vec2

    def sample(self, t):
        u = 1 - t
        return self.a*(u*u*u) + self.b*(3*u*u*t) + self.c*(3*u*t*t) + self.d*(t*t*t)

    def split(self):
        ab, bc, cd = self.a.lerp(self.b, .5), self.b.lerp(self.c, .5), self.c.lerp(self.d, .5)
        abc, bcd = ab.lerp(bc, .5), bc.lerp(cd, .5)
        mid = abc.lerp(bcd, .5)
        return Bezier(self.a, ab, abc, mid), Bezier(mid, bcd, cd, self.d)

    def certified_safe(self, region, depth=0):
        if any(all(box.contains(p) for p in (self.a, self.b, self.c, self.d)) for box in region.boxes):
            return True
        if depth >= 12:
            return False
        first, second = self.split()
        return first.certified_safe(region, depth + 1) and second.certified_safe(region, depth + 1)


class CurveRoute:
    def __init__(self, curves, start):
        self.curves = curves
        self.start = start
        self.samples = [start]
        self.distances = [0.]
        self.parameters = [(0, 0.)]
        self.curve_offsets = []
        length = 0.
        for index, curve in enumerate(curves):
            self.curve_offsets.append(length)
            polygon_length = sum((b - a).length() for a, b in zip((curve.a, curve.b, curve.c), (curve.b, curve.c, curve.d)))
            count = max(12, ceil(polygon_length / 2))
            for j in range(1, count + 1):
                p = curve.sample(j / count)
                length += (p - self.samples[-1]).length()
                self.samples.append(p)
                self.distances.append(length)
                self.parameters.append((index, j / count))
        self.length = length

    def sample(self, distance):
        if not self.curves:
            return self.start
        distance = max(0., min(self.length, distance))
        i = min(len(self.distances) - 1, max(1, bisect_right(self.distances, distance)))
        index, end_t = self.parameters[i]
        prev_index, start_t = self.parameters[i - 1]
        if prev_index != index:
            start_t = 0.
        f = (distance - self.distances[i - 1]) / max(1e-12, self.distances[i] - self.distances[i - 1])
        return self.curves[index].sample(start_t + (end_t - start_t) * f)

    def speed_limit(self, distance, maximum):
        a, b, c = (self.sample(distance + offset) for offset in (0, 4, 8))
        v, w = normalized(b - a), normalized(c - b)
        if (c - b).length() < .01 or (b - a).length() < .01:
            return maximum
        angle = abs(atan2(v.x*w.y - v.y*w.x, v.x*w.x + v.y*w.y))
        return min(maximum, sqrt(.065 * 4 / max(angle, 1e-6)))


class EdgePlanner:
    def __init__(self, world, region, *, corner_clearance=None):
        self.region = region
        x = (region.outer.left + region.hole.left) / 2
        y = (region.outer.top + region.hole.top) / 2
        if corner_clearance is not None:
            x = max(region.outer.left, region.hole.left-corner_clearance)
            y = max(region.outer.top, region.hole.top-corner_clearance)
        self.corners = (Vec2(x, y), Vec2(world.width - x, y),
                        Vec2(world.width - x, world.height - y), Vec2(x, world.height - y))

    def plan(self, start, target, velocity=Vec2()):
        nodes = [start, target, *self.corners]
        graph = [[] for _ in nodes]
        for i, a in enumerate(nodes):
            for j in range(i + 1, len(nodes)):
                b = nodes[j]
                if any(box.contains(a) and box.contains(b) for box in self.region.boxes):
                    graph[i].append((j, (b - a).length()))
                    graph[j].append((i, (b - a).length()))
        heap, seen = [(0., 0, [0])], set()
        while heap:
            cost, index, path = heappop(heap)
            if index == 1:
                return self.round_polyline([nodes[i] for i in path], velocity)
            if index in seen:
                continue
            seen.add(index)
            for next_index, length in graph[index]:
                if next_index not in seen:
                    heappush(heap, (cost + length, next_index, path + [next_index]))
        raise ValueError('无法在边缘区域内连接目标')

    def lap(self, start, clockwise=True):
        # 找到所在边；角落平局优先与当前点最近的下一角，沿指定方向通过四个角。
        choices = []
        for edge, box in enumerate(self.region.boxes):
            if box.contains(start):
                next_corner = (edge + 1) % 4 if clockwise else edge
                choices.append(((self.corners[next_corner] - start).length(), next_corner))
        _, first = min(choices)
        direction = 1 if clockwise else -1
        points = [start] + [self.corners[(first + i*direction) % 4] for i in range(4)] + [start]
        return self.round_polyline(points)

    def adjacent(self, start, target, source_edge, target_edge, velocity=Vec2()):
        """自主跨边只经过两边共用的一个角，不允许规划器改走另一侧长路。"""
        if (target_edge-source_edge) % 4 not in (1, 3):
            raise ValueError('跨边目标必须是当前边的相邻边')
        source, destination = self.region.boxes[source_edge], self.region.boxes[target_edge]
        if not source.contains(start) or not destination.contains(target):
            raise ValueError('跨边路径端点必须位于指定的边')
        corner = target_edge if (target_edge-source_edge) % 4 == 1 else source_edge
        points = [start, target] if destination.contains(start) else [start, self.corners[corner], target]
        return self.round_polyline(points, velocity)

    @staticmethod
    def local_arc(start, center, box, preferred_sign=1):
        """只选完整凸包位于同一走廊的局部绕珠弧；空间不足返回 None。"""
        radius = (start-center).length()
        if not 32 <= radius <= 72 or not box.contains(start):
            return None
        angle = atan2(start.y-center.y, start.x-center.x)
        candidates = []
        for sign in (preferred_sign, -preferred_sign):
            for degrees in (110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 12):
                sweep = sign*degrees*pi/180
                count = ceil(abs(sweep)/(pi/4))
                step = sweep/count
                handle = 4/3*tan(step/4)*radius
                curves = []
                a = start
                for i in range(count):
                    t0, t1 = angle+i*step, angle+(i+1)*step
                    d = center+Vec2(cos(t1), sin(t1))*radius
                    b = a+Vec2(-sin(t0), cos(t0))*handle
                    c = d-Vec2(-sin(t1), cos(t1))*handle
                    curves.append(Bezier(a, b, c, d))
                    a = d
                if all(box.contains(p) for curve in curves for p in (curve.a, curve.b, curve.c, curve.d)):
                    candidates.append(CurveRoute(curves, start))
                    break
        return max(candidates, key=lambda route: route.length) if candidates else None

    def round_polyline(self, points, velocity=Vec2(), *, box=None):
        clean = [points[0]]
        for p in points[1:]:
            if (p - clean[-1]).length() > 1e-7:
                clean.append(p)
        if len(clean) == 1:
            return CurveRoute([], clean[0])
        curves = []

        def line(a, b):
            if (a - b).length() > 1e-7:
                curves.append(Bezier(a, a.lerp(b, 1/3), a.lerp(b, 2/3), b))

        if len(clean) == 2:
            a, b = clean
            box = box or next(box for box in self.region.boxes if box.contains(a) and box.contains(b))
            v = b - a
            side = Vec2(-normalized(v).y, normalized(v).x)
            bend = min(10., v.length() * .12)
            c1, c2 = a.lerp(b, 1/3) + side*bend, a.lerp(b, 2/3) + side*bend
            if velocity.length() > .1:
                c1 = a + normalized(velocity)*min(24., v.length()/3)
            curves.append(Bezier(a, box.clamp(c1), box.clamp(c2), b))
        else:
            cursor = clean[0]
            for i in range(1, len(clean) - 1):
                before, corner, after = clean[i - 1:i + 2]
                incoming, outgoing = normalized(corner - before), normalized(after - corner)
                cut = min(60., (corner - before).length()*.3, (after - corner).length()*.3)
                while True:
                    entry, exit_point = corner - incoming*cut, corner + outgoing*cut
                    arc = Bezier(entry, entry.lerp(corner, 2/3), exit_point.lerp(corner, 2/3), exit_point)
                    if arc.certified_safe(self.region):
                        break
                    cut *= .5
                    if cut < 1e-6:
                        raise ValueError('角落空间不足以生成安全曲线')
                line(cursor, entry)
                curves.append(arc)
                cursor = exit_point
            line(cursor, clean[-1])
        if not all(curve.certified_safe(self.region) for curve in curves):
            raise ValueError('路径凸包超出边缘安全区')
        return CurveRoute(curves, clean[0])


class SlidingBase:
    def __init__(self, rail, position, speed):
        self.rail = rail
        self.s = self.previous_s = rail.project(position)
        self.goal_s = self.s
        self.velocity = 0.
        self.max_speed = speed
        self.moving = False
        self.consistent_ticks = 0
        self.candidate_sign = 0
        self.committed_sign = 0
        self.reversals = 0
        self.starts = 0

    @property
    def position(self):
        return self.rail.sample(self.s)[0]

    def step(self, desired, body, reach):
        self.previous_s = self.s
        candidate = self.rail.project(desired, self.goal_s)
        if abs(candidate - self.goal_s) > 12:
            self.goal_s = candidate
        error = self.rail.delta(self.s, self.goal_s)
        sign = 1 if error > 0 else -1
        if sign == self.candidate_sign:
            self.consistent_ticks += 1
        else:
            self.candidate_sign, self.consistent_ticks = sign, 0
        start = min(80., reach * .3)
        stop = start * .25
        urgent = (self.position - body).length() > reach * .72
        if not self.moving and abs(error) > start and (self.consistent_ticks >= 20 or urgent):
            self.moving = True
            self.starts += 1
        target_speed = 0.
        if self.moving and abs(error) > stop:
            # 反向先刹车，并等待方向稳定；不会直接翻转底座速度。
            reverse_wait = sign != self.committed_sign and self.committed_sign != 0 and self.consistent_ticks < 20
            if not reverse_wait:
                if sign != self.committed_sign:
                    self.reversals += int(self.committed_sign != 0)
                    self.committed_sign = sign
                corner_limit = self.max_speed
                _, tangent = self.rail.sample(self.s)
                _, next_tangent = self.rail.sample(self.s + sign * 8)
                if (tangent - next_tangent).length() > .02:
                    corner_limit = min(corner_limit, sqrt(.08 * self.rail.radius))
                target_speed = sign * min(corner_limit, sqrt(2 * .065 * (abs(error) - stop)))
        self.velocity = approach(self.velocity, target_speed, .065)
        candidate_s = self.s + self.velocity
        if (self.rail.sample(candidate_s)[0] - body).length() > reach - 4:
            # 不能为追赶远处路径而把已经支撑着的人偶拉出可达范围。
            self.velocity = 0.
            candidate_s = self.s
        self.s = candidate_s
        if abs(self.velocity) < 1e-8 and abs(error) <= stop:
            self.moving = False


class FloatNavigator:
    def __init__(self, world, position, base_position, reach, speed=1.6, base_speed=2.8):
        self.region = EdgeRegion(world, reach=reach)
        self.planner = EdgePlanner(world, self.region)
        self.rail = RoundedRail(world)
        self.base = SlidingBase(self.rail, base_position, base_speed)
        self.route = CurveRoute([], position)
        self.distance = self.speed = 0.
        self.max_speed = speed
        self.guide = position
        self.velocity = Vec2()
        self.waiting_for_base = False

    @property
    def done(self):
        return self.distance >= self.route.length - 1e-7 and self.speed < 1e-7

    def set_route(self, route):
        self.route = route
        self.distance = 0.
        self.guide = route.start
        self.velocity = Vec2()
        # 保留已有速度，下一步按加速度收敛到本次行动的上限。

    def extend_to(self, target, box):
        """将当前终点变成途经点；保留当前曲线、导引位置和推进速度。"""
        if self.done or not self.route.curves:
            return False
        last = self.route.curves[-1]
        start, forward = last.d, normalized(last.d-last.c)
        offset = target-start
        distance = offset.length()
        outgoing = normalized(offset)
        # 掉头或指向边界时保留原来的终点刹车，不硬拼一个尖角。
        if distance < 30 or forward.x*outgoing.x+forward.y*outgoing.y < .35:
            return False
        curve = Bezier(start, start+forward*min(24., distance/3), target-offset*(1/3), target)
        if not all(box.contains(p) for p in (curve.a, curve.b, curve.c, curve.d)):
            return False
        # 只保留尚未走完的曲线，长达数分钟的漫游不会累计路径历史。
        index = max(0, bisect_right(self.route.curve_offsets, self.distance)-1)
        distance = self.distance-self.route.curve_offsets[index]
        curves = [*self.route.curves[index:], curve]
        self.route = CurveRoute(curves, curves[0].a)
        self.distance = distance
        return True

    def step(self, body, reach, *, speed_limit=None):
        remaining = max(0., self.route.length - self.distance)
        preview = self.route.sample(self.distance + min(60., reach*.28))
        self.base.step(preview, body, reach)
        maximum = self.max_speed if speed_limit is None else speed_limit
        desired_speed = min(self.route.speed_limit(self.distance, maximum), sqrt(2 * .045 * remaining))
        probe = self.route.sample(self.distance + max(24., self.speed * 18))
        reserve = reach - (probe - self.base.position).length()
        desired_speed *= max(0., min(1., (reserve - 12) / 32))
        self.speed = approach(self.speed, desired_speed, .045)
        advance = min(remaining, self.speed)
        candidate = self.route.sample(self.distance + advance)
        self.waiting_for_base = (candidate - self.base.position).length() > reach - 8
        if self.waiting_for_base:
            advance = 0.
            self.speed = 0.
            candidate = self.guide
        self.velocity = candidate - self.guide
        self.guide = candidate
        self.distance += advance
        if self.distance >= self.route.length - 1e-7:
            self.speed = 0.
