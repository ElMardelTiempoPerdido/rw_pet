"""两段悬垂腿：固定腿根、独立膝脚惯性和限长，不反向推动人偶"""
from math import atan2, cos, pi, sin

from ...shared.geometry import Vec2


def unit(value, fallback):
    length = value.length()
    return value*(1/length) if length > 1e-9 else fallback


def limit_direction(value, reference, maximum):
    reference = unit(reference, Vec2(0, 1))
    direction = unit(value, reference)
    angle = atan2(reference.x*direction.y-reference.y*direction.x,
                  reference.x*direction.x+reference.y*direction.y)
    angle = max(-maximum, min(maximum, angle))
    c, s = cos(angle), sin(angle)
    return Vec2(reference.x*c-reference.y*s, reference.x*s+reference.y*c)


class LegMotion:
    KNEE_SPRING = .001
    FOOT_SPRING = .0002
    KNEE_DAMPING = .88  # 每步保留的速度比例；运动中略减阻尼，让脚部滞后跟随
    FOOT_DAMPING = .91
    KNEE_MOVING_DAMPING = .94
    FOOT_MOVING_DAMPING = .96
    KNEE_GRAVITY = .025
    FOOT_GRAVITY = .035
    HIP_LIMIT = 15*pi/180
    KNEE_LIMIT = 30*pi/180
    SOLVER_PASSES = 4

    def __init__(self, knee, foot, root, knee_goal, foot_goal):
        self.knee, self.foot = knee, foot
        self.reset(root, knee_goal, foot_goal)

    def reset(self, root, knee_goal, foot_goal):
        self.last_root = root
        self.upper_length = (knee_goal-root).length()
        self.lower_length = (foot_goal-knee_goal).length()
        for p, goal in ((self.knee, knee_goal), (self.foot, foot_goal)):
            p.position = p.previous_position = goal
            p.velocity = Vec2()

    def step(self, root, knee_goal, foot_goal, gravity):
        motion = min(1., (root-self.last_root).length()/.3)
        self.last_root = root
        for p, goal, spring, rest, moving, weight in (
                (self.knee, knee_goal, self.KNEE_SPRING, self.KNEE_DAMPING,
                 self.KNEE_MOVING_DAMPING, self.KNEE_GRAVITY),
                (self.foot, foot_goal, self.FOOT_SPRING, self.FOOT_DAMPING,
                 self.FOOT_MOVING_DAMPING, self.FOOT_GRAVITY)):
            p.previous_position = p.position
            p.position += (p.velocity*(rest+(moving-rest)*motion)
                           +(goal-p.position)*spring+Vec2(0, weight*gravity))
        knee, foot = self.knee.position, self.foot.position
        down = unit(knee_goal-root, Vec2(0, 1))
        # 先让小腿张力传回膝部，再精确投影两个杆长；不会随迭代次数伸缩
        for _ in range(self.SOLVER_PASSES):
            knee = root+unit(knee-root, down)*self.upper_length
            delta = foot-knee
            correction = unit(delta, down)*((delta.length()-self.lower_length)*.5)
            knee += correction
            foot -= correction
        upper = limit_direction(knee-root, down, self.HIP_LIMIT)
        knee = root+upper*self.upper_length
        lower = limit_direction(foot-knee, upper, self.KNEE_LIMIT)
        foot = knee+lower*self.lower_length
        # 只保留约束后真正发生的位移，不积累被限长或关节限位抵消的速度
        for p, position in ((self.knee, knee), (self.foot, foot)):
            p.position = position
            p.velocity = position-p.previous_position
