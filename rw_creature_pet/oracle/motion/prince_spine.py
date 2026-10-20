"""Prince 的五点身体轴，腰部跟随导航支点，其余节点通过距离约束传力"""
from dataclasses import dataclass
from math import atan2, cos, pi, radians, sqrt

from ...shared.geometry import Vec2


WAIST = 1
PASSES = 16
# 只限制相邻段反折，整体仍可倾斜或倒立
BEND_LIMITS = (95., 55., 60.)
SPRING = (.045, 0., .075, .065, .055)
DAMPING = .78
DRAG_DAMPING = .88
DRAG_SPRING = .012
DRAG_GRAVITY = .16
# 下摆可自由下垂，上半身由腰部支撑，避免短颈段承受过大的轴向压缩
DRAG_GRAVITY_WEIGHTS = (1., 0., .12, .10, .08)
# 每轮约束的柔性角度恢复力度，腰部较软，胸颈保持连续弯曲
DRAG_BEND_STIFFNESS = (.008, .08, .08)
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

    def reset(self, goals):
        for p, target in zip(self.points, goals):
            p.position = p.previous_position = target
            p.velocity = Vec2()
        self.targets = tuple(goals)
        self.maximum_speed = 0.
        self.settled = True
        self.quiet_ticks = 0
        self.last_grab = None

    def step(self, goals, *, grab=None, gravity=1.):
        changes = max((a-b).length() for a, b in zip(goals, self.targets))
        gravity_changed = gravity != self.gravity
        grab_motion = (0. if grab is None and self.last_grab is None else
                       (grab[1]-self.last_grab[1]).length() if grab is not None
                       and self.last_grab is not None and grab[0] == self.last_grab[0] else float('inf'))
        grab_changed = grab_motion > 1e-8
        if (goals[WAIST]-self.targets[WAIST]).length() > 60.:
            self.reset(goals)
            return
        if self.settled and changes < 1e-8 and not grab_changed and not gravity_changed:
            if changes > 0. and grab is None:
                self.reset(goals)
            return
        self.last_grab, self.gravity = grab, gravity
        self.targets = tuple(goals)
        self.settled = False
        for i, (p, goal) in enumerate(zip(self.points, goals)):
            p.previous_position = p.position
            if i == WAIST:
                p.position = goal
                continue
            if grab is None:
                force = (goal-p.position)*SPRING[i]
                damping = DAMPING
            else:
                force = ((goal-p.position)*DRAG_SPRING
                         +Vec2(0., DRAG_GRAVITY*gravity*DRAG_GRAVITY_WEIGHTS[i]))
                damping = DRAG_DAMPING
                if i == grab[0]:
                    force += limited((grab[1]-p.position)*.28, 2.4)
            p.position += p.velocity*damping+force

        # 固定各段长度，角度恢复只提供柔性支撑，不把整条身体重建为一根直杆
        lengths = [(b-a).length() for a, b in zip(goals, goals[1:])]
        angles = ([bend_angle(b-a, c-b) for a, b, c in zip(goals, goals[1:], goals[2:])]
                  if grab is not None else ())
        spans = [sqrt(a*a+b*b+2*a*b*cos(radians(angle)))
                 for a, b, angle in zip(lengths, lengths[1:], BEND_LIMITS)]
        for iteration in range(PASSES):
            if grab is not None:
                self.restore_bends(angles)
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
        quiet = changes < .0001 and grab_motion < .0001 and not gravity_changed
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


def tangent(points, index):
    if index == 0:
        return unit(points[1]-points[0])
    if index == len(points)-1:
        return unit(points[-1]-points[-2])
    before, after = unit(points[index]-points[index-1]), unit(points[index+1]-points[index])
    # 腰部保留更多下摆方向，上身可从这里独立前弯
    weight = .25 if index == WAIST else .5
    return unit(before*(1-weight)+after*weight, after)


class SpineCurve:
    """每个绘制帧准备一次曲线，多列网格共享同一高度的中心与单位切线"""
    def __init__(self, points, stations):
        self.points, self.stations = points, stations
        self.tangents = tuple(tangent(points, i) for i in range(len(points)))
        self.coefficients = []
        self.samples = {}
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
