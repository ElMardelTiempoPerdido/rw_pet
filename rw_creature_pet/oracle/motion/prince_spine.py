"""Prince 的九点身体轴，中下段共同传递弯曲，腰部保留独立导航支点"""
from dataclasses import dataclass
from math import atan2, cos, pi, radians, sqrt

from ...shared.geometry import Vec2


TAIL, WAIST, CHEST, NECK, HEAD = 0, 3, 6, 7, 8
LANDMARKS = (TAIL, WAIST, CHEST, NECK, HEAD)
PASSES = 16
# 躯干把转角分到多段，较细的颈部仍保留原先的大幅转动
BEND_LIMITS = (38., 38., 40., 28., 28., 55., 60.)
# 普通状态轻微滞后；失重时中下段更软、保留较多惯性，胸颈仍有支撑
SPRING = (.036, .040, .044, 0., .065, .068, .075, .065, .055)
DAMPING = .80
DRIFT_SPRING = (.010, .012, .016, 0., .030, .036, .045, .050, .045)
DRIFT_DAMPING = .90
DRAG_DAMPING = .88
DRAG_SPRING = .012
DRAG_GRAVITY = .16
# 下摆可自由下垂，上半身由腰部支撑，避免短颈段承受过大的轴向压缩
DRAG_GRAVITY_WEIGHTS = (1., .67, .33, 0., .04, .08, .12, .10, .08)
# 每轮约束的柔性角度恢复力度，腰部较软，胸颈保持连续弯曲
DRAG_BEND_STIFFNESS = (.008, .008, .008, .008, .008, .08, .08)
BEND_SMOOTHING = .10  # 平滑相邻段的额外曲率，保留目标姿态本身的弓身
HOLD_SETTLE_SPEED = .0005
HOLD_SETTLE_TICKS = 24


def unit(v, fallback=Vec2(0., -1.)):
    length = v.length()
    return v*(1/length) if length > 1e-9 else fallback


def limited(v, maximum):
    return v*min(1., maximum/max(v.length(), 1e-9))


def bend_angle(a, b):
    return atan2(a.x*b.y-a.y*b.x, a.x*b.x+a.y*b.y)


@dataclass(slots=True)
class SpinePoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()

    def sample(self, alpha):
        return self.previous_position.lerp(self.position, alpha)


class PrinceSpine:
    def __init__(self, goals):
        self.points = [SpinePoint(p, p) for p in goals]
        self.targets = tuple(goals)
        self.settled = True
        self.quiet_ticks = 0
        self.maximum_speed = 0.
        self.last_grab = None
        self.gravity = None
        self.weightlessness = 0.

    def reset(self, goals):
        for p, target in zip(self.points, goals):
            p.position = p.previous_position = target
            p.velocity = Vec2()
        self.targets = tuple(goals)
        self.maximum_speed = 0.
        self.settled = True
        self.quiet_ticks = 0
        self.last_grab = None

    def step(self, goals, *, grab=None, gravity=1., weightlessness=0.):
        changes = max((a-b).length() for a, b in zip(goals, self.targets))
        gravity_changed = gravity != self.gravity
        # 抓取期间不混入漫游的柔软参数，即使场景的失重程度仍在缓慢退出
        weightlessness = 0. if grab is not None else max(0., min(1., weightlessness))
        softness_changed = weightlessness != self.weightlessness
        grab_motion = (0. if grab is None and self.last_grab is None else
                       (grab[1]-self.last_grab[1]).length() if grab is not None
                       and self.last_grab is not None and grab[0] == self.last_grab[0] else float('inf'))
        grab_changed = grab_motion > 1e-8
        if (goals[WAIST]-self.targets[WAIST]).length() > 60.:
            self.reset(goals)
            self.gravity, self.weightlessness = gravity, weightlessness
            return
        if (self.settled and changes < 1e-8 and not grab_changed
                and not gravity_changed and not softness_changed):
            if changes > 0. and grab is None:
                self.reset(goals)
            return
        self.last_grab, self.gravity = grab, gravity
        self.weightlessness = weightlessness
        self.targets = tuple(goals)
        self.settled = False
        damping = (DRAG_DAMPING if grab is not None else
                   DAMPING+(DRIFT_DAMPING-DAMPING)*weightlessness)
        for i, (p, goal) in enumerate(zip(self.points, goals)):
            p.previous_position = p.position
            if i == WAIST:
                p.position = goal
                continue
            if grab is None:
                spring = SPRING[i]+(DRIFT_SPRING[i]-SPRING[i])*weightlessness
                force = (goal-p.position)*spring
            else:
                force = ((goal-p.position)*DRAG_SPRING
                         +Vec2(0., DRAG_GRAVITY*gravity*DRAG_GRAVITY_WEIGHTS[i]))
                if i == grab[0]:
                    force += limited((grab[1]-p.position)*.30, 2.4)
            p.position += p.velocity*damping+force

        # 固定各段长度，角度恢复只提供柔性支撑，不把整条身体重建为一根直杆
        lengths = [(b-a).length() for a, b in zip(goals, goals[1:])]
        angles = [bend_angle(b-a, c-b) for a, b, c in zip(goals, goals[1:], goals[2:])]
        spans = [sqrt(a*a+b*b+2*a*b*cos(radians(angle)))
                 for a, b, angle in zip(lengths, lengths[1:], BEND_LIMITS)]
        for iteration in range(PASSES):
            if grab is not None:
                self.restore_bends(angles)
            self.smooth_bends(lengths, angles)
            for i, minimum in enumerate(spans):
                a, b = self.points[i], self.points[i+2]
                delta = b.position-a.position
                distance = delta.length()
                if distance < minimum:
                    correction = unit(delta, unit(goals[i+2]-goals[i]))*(distance-minimum)
                    wa, wb = float(i != WAIST), float(i+2 != WAIST)
                    a.position += correction*(wa/(wa+wb))
                    b.position -= correction*(wb/(wa+wb))
            edges = range(len(lengths)) if iteration%2 == 0 else reversed(range(len(lengths)))
            for i in edges:
                a, b = self.points[i:i+2]
                delta = b.position-a.position
                correction = unit(delta, unit(goals[i+1]-goals[i]))*(delta.length()-lengths[i])
                wa, wb = float(i != WAIST), float(i+1 != WAIST)
                a.position += correction*(wa/(wa+wb))
                b.position -= correction*(wb/(wa+wb))
        for p in self.points:
            p.velocity = p.position-p.previous_position
        self.maximum_speed = max(p.velocity.length() for p in self.points)
        quiet = (changes < .0001 and grab_motion < .0001
                 and not gravity_changed and not softness_changed)
        if grab is None:
            quiet = (quiet and self.maximum_speed < .002
                     and max((p.position-g).length() for p, g in zip(self.points, goals)) < .03)
        else:
            quiet = quiet and self.maximum_speed < HOLD_SETTLE_SPEED
        self.quiet_ticks = self.quiet_ticks+1 if quiet else 0
        if self.quiet_ticks >= (16 if grab is None else HOLD_SETTLE_TICKS):
            if grab is None:
                self.reset(goals)
            else:
                # 抓住不动时冻结已经收敛的受力姿态，不强行重置为直立
                for p in self.points:
                    p.previous_position, p.velocity = p.position, Vec2()
                self.maximum_speed = 0.
                self.settled = True

    def restore_bends(self, preferred):
        for i, (angle, stiffness) in enumerate(zip(preferred, DRAG_BEND_STIFFNESS)):
            a, b, c = self.points[i:i+3]
            u, v = b.position-a.position, c.position-b.position
            u2, v2 = u.x*u.x+u.y*u.y, v.x*v.x+v.y*v.y
            if min(u2, v2) < 1e-9:
                continue
            error = (bend_angle(u, v)-angle+pi) % (2*pi)-pi
            gu, gv = Vec2(-u.y/u2, u.x/u2), Vec2(-v.y/v2, v.x/v2)
            gradients = (gu, (gu+gv)*-1., gv)
            weights = tuple(float(j != WAIST) for j in range(i, i+3))
            total = sum(w*(g.x*g.x+g.y*g.y) for w, g in zip(weights, gradients))
            correction = -stiffness*error/max(total, 1e-9)
            for p, w, g in zip((a, b, c), weights, gradients):
                p.position += g*(w*correction)

    def smooth_bends(self, lengths, preferred):
        # 比较单位长度上的弯曲量，让一处折弯传给相邻段；头颈保留独立响应
        for i in range(CHEST-2):
            groups = (self.points[i:i+3], self.points[i+1:i+4])
            ratio = (lengths[i]+lengths[i+1])/(lengths[i+1]+lengths[i+2])
            gradients = [Vec2() for _ in range(4)]
            error = 0.
            for j, (group, factor) in enumerate(zip(groups, (1., -ratio))):
                a, b, c = (p.position for p in group)
                u, v = b-a, c-b
                u2, v2 = u.x*u.x+u.y*u.y, v.x*v.x+v.y*v.y
                if min(u2, v2) < 1e-9:
                    continue
                rest = preferred[i+j]
                error += factor*((bend_angle(u, v)-rest+pi) % (2*pi)-pi)
                gu, gv = Vec2(-u.y/u2, u.x/u2), Vec2(-v.y/v2, v.x/v2)
                for k, g in enumerate((gu, (gu+gv)*-1., gv)):
                    gradients[j+k] += g*factor
            weights = tuple(float(j != WAIST) for j in range(i, i+4))
            total = sum(w*(g.x*g.x+g.y*g.y) for w, g in zip(weights, gradients))
            correction = -BEND_SMOOTHING*error/max(total, 1e-9)
            for p, w, g in zip(self.points[i:i+4], weights, gradients):
                p.position += g*(w*correction)


def tangent(points, index):
    if index == 0:
        return unit(points[1]-points[0])
    if index == len(points)-1:
        return unit(points[-1]-points[-2])
    before, after = unit(points[index]-points[index-1]), unit(points[index+1]-points[index])
    # 接缝两侧使用相同切线，不再额外把腰部切线偏向较直的下半身
    return unit(before+after, after)


class SpineCurve:
    """每个绘制帧准备一次曲线，多列网格共享同一高度的中心与单位切线"""
    def __init__(self, points, stations):
        self.points, self.stations = points, stations
        self.tangents = tuple(tangent(points, i) for i in range(len(points)))
        self.coefficients = []
        self.samples = dict(zip(stations, zip(points, self.tangents)))
        for i, (a, b) in enumerate(zip(points, points[1:])):
            distance = (b-a).length()
            u, v = self.tangents[i]*distance, self.tangents[i+1]*distance
            self.coefficients.append((a*2-b*2+u+v, a*-3+b*3-u*2-v, u, a))

    def sample(self, y):
        if y in self.samples:
            return self.samples[y]
        points, stations = self.points, self.stations
        if y <= stations[0]:
            axis = self.tangents[0]
            result = points[0]+axis*(y-stations[0]), axis
        elif y >= stations[-1]:
            axis = self.tangents[-1]
            result = points[-1]+axis*(y-stations[-1]), axis
        else:
            i = next(i for i in range(len(stations)-1) if stations[i+1] >= y)
            t = (y-stations[i])/(stations[i+1]-stations[i])
            a, b, c, d = self.coefficients[i]
            center = Vec2(((a.x*t+b.x)*t+c.x)*t+d.x, ((a.y*t+b.y)*t+c.y)*t+d.y)
            derivative = Vec2((3*a.x*t+2*b.x)*t+c.x, (3*a.y*t+2*b.y)*t+c.y)
            result = center, unit(derivative, self.tangents[i])
        self.samples[y] = result
        return result
