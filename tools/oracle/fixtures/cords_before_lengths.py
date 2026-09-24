"""Oracle 线缆：底座供线、单导向点、可活动分线端和独立软线。

固定 40 Hz 的位置约束绳索；只影响外观，允许少量探出边缘活动带。
保留绳长、导向点和身体附近约束，屏幕外沿由窗口裁剪。
"""
from dataclasses import dataclass
from math import hypot, sin, pi
from random import Random

from rw_creature_pet.shared.geometry import Vec2


@dataclass(slots=True)
class CordPoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()

    def sample(self, alpha):
        a, b = self.previous_position, self.position
        return Vec2(a.x+(b.x-a.x)*alpha, a.y+(b.y-a.y)*alpha)


def path_length(path):
    return sum((b-a).length() for a, b in zip(path, path[1:]))


def sample_path(path, count):
    lengths = [(b-a).length() for a, b in zip(path, path[1:])]
    total = sum(lengths)
    result, index, passed = [], 0, 0.
    for i in range(count):
        distance = total*i/(count-1)
        while index < len(lengths)-1 and distance > passed+lengths[index]:
            passed += lengths[index]
            index += 1
        result.append(path[index].lerp(path[index+1],
                      min(1., max(0., (distance-passed)/max(lengths[index], 1e-9)))))
    result[0], result[-1] = path[0], path[-1]
    return result


def short_route(region, path):
    """只用于初始化和供线长度；不把绳点逐帧拉回这条路径。"""
    result = [path[0]]
    while len(path) > 1:
        index = next(i for i in range(len(path)-1, 0, -1)
                     if region.segment_safe(path[0], path[i]))
        result.append(path[index])
        path = path[index:]
    return result


def close_inputs(a, b, tolerance=.001):
    """休眠比较保留参考输入，亚像素微动不会反复唤醒；累计移动仍会唤醒。"""
    if type(a) is not type(b):
        return False
    if isinstance(a, Vec2):
        return abs(a.x-b.x) <= tolerance and abs(a.y-b.y) <= tolerance
    if isinstance(a, (float, int)):
        return abs(a-b) <= tolerance
    if isinstance(a, tuple):
        return len(a) == len(b) and all(close_inputs(x, y, tolerance) for x, y in zip(a, b))
    return a == b


class Rope:
    def __init__(self, positions, lengths, gravity, damping):
        self.points = [CordPoint(p, p) for p in positions]
        self.rest = list(lengths)
        self.gravity, self.damping = gravity, damping
        self.sleeping = False
        self.quiet_ticks = 0
        self.last_inputs = None
        n = len(positions)
        self._x, self._y = [0.]*n, [0.]*n
        self._weights = [1.]*n
        self._pin_indices = None
        self._long_indices = [(i, i+stride) for stride in (16, 8, 4)
                              for i in range(0, n-stride, stride//2)] if n > 30 else []
        self._prefix = [0.]*n
        self.iterations = 0

    def __eq__(self, other):
        return isinstance(other, Rope) and self.__dict__ == other.__dict__

    def step(self, pins, *, disk=None, end_disk=None, forces=None, supply=None, inputs=()):
        key = (tuple(pins.items()), disk, end_disk, inputs, supply)
        stable = close_inputs(key, self.last_inputs)
        if self.sleeping and stable:
            self.iterations = 0
            for p in self.points:
                p.previous_position = p.position
            # 端点仍严格连接，容差只用于是否重新求解。
            for i, position in pins.items():
                self.points[i].position = position
            return
        self.sleeping = False
        if not stable:
            self.quiet_ticks = 0
            self.last_inputs = key
        if supply is not None:
            for start, end, length in supply:
                desired = length/(end-start)
                for i in range(start, end):
                    self.rest[i] += max(-.025, min(.025, (desired-self.rest[i])*.08))
        n = len(self.points)
        x, y, weights = self._x, self._y, self._weights
        pin_indices = tuple(pins)
        if pin_indices != self._pin_indices:
            weights[:] = [0. if i in pins else 1. for i in range(n)]
            self._pin_indices = pin_indices
        for i, p in enumerate(self.points):
            p.previous_position = p.position
            x[i] = p.position.x+p.velocity.x*self.damping
            y[i] = p.position.y+p.velocity.y*self.damping+self.gravity
            if 0 < i < n-1:
                a, b = self.points[i-1].position, self.points[i+1].position
                x[i] += (a.x+b.x-2*p.position.x)*.035
                y[i] += (a.y+b.y-2*p.position.y)*.035
        for i, f in (forces or {}).items():
            x[i] += f.x
            y[i] += f.y

        def project():
            if disk is not None:
                center, radius = disk
                radius2 = radius*radius
                for i in range(n):
                    dx, dy = x[i]-center.x, y[i]-center.y
                    d2 = dx*dx+dy*dy
                    if d2 > radius2:
                        f = radius/d2**.5
                        x[i], y[i] = center.x+dx*f, center.y+dy*f
            if end_disk is not None:
                center, radius = end_disk
                dx, dy = x[-1]-center.x, y[-1]-center.y
                d2 = dx*dx+dy*dy
                if d2 > radius*radius:
                    f = radius/d2**.5
                    x[-1], y[-1] = center.x+dx*f, center.y+dy*f
            for i, p in pins.items():
                x[i], y[i] = p.x, p.y

        project()
        prefix = self._prefix
        for i, rest in enumerate(self.rest):
            prefix[i+1] = prefix[i]+rest
        long_links = [(i, j, prefix[j]-prefix[i]) for i, j in self._long_indices]
        minimum, maximum, tolerance = (4, 12, .35) if n > 30 else (2, 10, .30)
        if stable:
            # 输入停稳后锁住已采用的精度，只允许增加，避免求解遍数在
            # 阈值两侧切换而不断激发细抖；少量额外收敛随后换来休眠。
            minimum = max(minimum, self.iterations)
            maximum = 24 if n > 30 else 20
            if n <= 30:
                tolerance = .18
        for iteration in range(maximum):
            # 跨节点约束只传递拉力；松弛时不把绳子拉直。
            for i, j, length in long_links:
                dx, dy = x[j]-x[i], y[j]-y[i]
                d2, w = dx*dx+dy*dy, weights[i]+weights[j]
                if d2 > length*length and w:
                    d = d2**.5
                    f = (d-length)/(d*w)
                    x[i] += dx*f*weights[i]; y[i] += dy*f*weights[i]
                    x[j] -= dx*f*weights[j]; y[j] -= dy*f*weights[j]
            indices = range(n-1) if iteration % 2 == 0 else range(n-2, -1, -1)
            for i in indices:
                j = i+1
                dx, dy = x[j]-x[i], y[j]-y[i]
                d = hypot(dx, dy)
                w = weights[i]+weights[j]
                if d < 1e-9 or not w:
                    continue
                f = (d-self.rest[i])/(d*w)
                x[i] += dx*f*weights[i]; y[i] += dy*f*weights[i]
                x[j] -= dx*f*weights[j]; y[j] -= dy*f*weights[j]
            project()
            self.iterations = iteration+1
            if self.iterations >= minimum and self.iterations % 2 == 0:
                # 按收敛误差提前结束，不按帧耗时改变行为，回放保持确定性。
                if all(abs(hypot(x[i+1]-x[i], y[i+1]-y[i])-rest) <= tolerance
                       for i, rest in enumerate(self.rest)):
                    break
        speed2 = 0.
        for i, p in enumerate(self.points):
            p.position = Vec2(x[i], y[i])
            p.velocity = p.position-p.previous_position
            speed2 = max(speed2, p.velocity.x*p.velocity.x+p.velocity.y*p.velocity.y)
        settled_supply = supply is None or all(abs(self.rest[a]-length/(b-a)) < .001
                                                for a, b, length in supply)
        self.quiet_ticks = self.quiet_ticks+1 if speed2 < .002**2 and settled_supply else 0
        if self.quiet_ticks >= 30:
            self.sleeping = True
            for p in self.points:
                p.previous_position = p.position
                p.velocity = Vec2()


class OracleCords:
    MAIN_COUNT = 80
    GUIDE_INDEX = 60
    FINE_COUNT = 14
    FINE_POINTS = 20

    def __eq__(self, other):
        if not isinstance(other, OracleCords):
            return False
        return (self.region.__dict__ == other.region.__dict__ and
                {k: v for k, v in self.__dict__.items() if k != 'region'} ==
                {k: v for k, v in other.__dict__.items() if k != 'region'})

    def __init__(self, scene, head):
        self.region = scene.arm_region
        self.guide = self.guide_position(scene)
        junction = scene.arm.joints[-1].position
        first, last = self.routes(scene, junction)
        lengths = self.supply_lengths(first, last)
        positions = sample_path(first, 61)+sample_path(last, 20)[1:]
        self.main = Rope(positions, [lengths[0]/60]*60+[lengths[1]/19]*19, .20, .86)
        rng = Random(10544)
        self.fine = []
        self.head_dirs, self.colors, self.fine_lengths = [], [], []
        for index in range(self.FINE_COUNT):
            extra = rng.uniform(5., 22.)
            direction = Vec2(rng.uniform(-1., 1.), rng.uniform(-.6, .6))
            self.fine_lengths.append(38.+extra)
            self.head_dirs.append(direction)
            self.colors.append(rng.randrange(3))
            # 仅初始化时分开绳子；运行后由受力决定弧线，不再追踪扇形目标。
            positions = [junction.lerp(head, k/19)+Vec2(sin(pi*k/19)*direction.x*8, 0)
                         for k in range(20)]
            length = self.fine_lengths[-1]
            self.fine.append(Rope(positions, [length/19]*19, .16, .82))

    @staticmethod
    def guide_position(scene):
        # 参考原版第二段臂的导线点；不再钉住每个主关节。
        return scene.arm.joints[1].position.lerp(scene.arm.joints[2].position, .4)

    def routes(self, scene, junction):
        joints = [j.position for j in scene.arm.joints]
        first = short_route(self.region, [joints[0], joints[1], self.guide])
        # 活动分线端位于身体安全圆内；末段到身体的连线由原有支撑约束保证。
        last = short_route(self.region, [self.guide, joints[2], joints[3], junction])
        return first, last

    @staticmethod
    def supply_lengths(first, last):
        a, b = path_length(first), path_length(last)
        return max(65., a+min(24., a*.15+8)), max(24., b+min(12., b*.12+4))

    def step(self, scene, head, upper, direction, look):
        self.guide = self.guide_position(scene)
        first, last = self.routes(scene, scene.arm.joints[-1].position)
        lengths = self.supply_lengths(first, last)
        normal = scene.base_normal()
        force = {i: normal*(.10*(1-i/12)) for i in range(1, 12)}
        # 末端仅限制在上身附近，允许惯性、重力和绳索张力决定其位置。
        self.main.step({0: scene.base, 60: self.guide},
                       end_disk=(upper, 24.), forces=force,
                       supply=((0, 60, lengths[0]), (60, 79, lengths[1])), inputs=(normal,))
        junction = self.main.points[-1].position
        delta = junction-self.main.points[-2].position
        exit_dir = delta*(1/max(delta.length(), 1e-9))
        side = Vec2(-direction.y, direction.x)
        span = (head-junction).length()+2.
        for index, rope in enumerate(self.fine):
            seed = self.head_dirs[index]
            head_dir = side*seed.x+direction*seed.y+look*.5
            forces = {1: exit_dir*.18, 2: exit_dir*.10, 3: exit_dir*.04,
                      18: head_dir*-.12, 17: head_dir*-.06}
            # 细线固定个体长度；必要时平滑补足头部与分线端的实际跨度。
            length = max(self.fine_lengths[index], span)
            rope.step({0: junction, 19: head}, disk=(upper, 32.), forces=forces,
                      supply=((0, 19, length),), inputs=(exit_dir, head_dir))

    @property
    def sleeping(self):
        return self.main.sleeping and all(rope.sleeping for rope in self.fine)
