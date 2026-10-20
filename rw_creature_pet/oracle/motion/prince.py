"""Prince 从腰部弯曲的身体轴与分段惯性，固定 40 Hz，导航支点保持独立"""
from dataclasses import dataclass, field
from math import cos, sin

from ...shared.geometry import Vec2
from ..prince_assets import robe_layout
from .prince_spine import PrinceSpine, SpineCurve, unit


WAIST_DEPTH = 14.
CHEST_DROP = .65  # 正面静止仍保留轻微弓身
LOOK_BEND = .12  # 平视或仰视只保留轻微的躯干前弯，弧度
LOW_LOOK_BEND = 1.02  # 向下的注视分量逐渐增加俯身，最大幅度保持不变
NECK_LOOK_BEND = .25  # 颈部转向独立于躯干，平视时仍能侧看
LOW_NECK_BEND = 1.0  # 深度俯视时允许颈部进一步接近水平
NECK_BEND = .18
BODY_BOW_POWER = 1.3  # 大于 1 时，躯干主要在低头的后段参与
NECK_BOW_POWER = 2.  # 大于 1 时，颈部更早低下，末段平滑接近上限
CHEST_FOLLOW = .16
HEAD_FOLLOW = .10
LOW_LOOK_FOLLOW = .12


def side_of(direction):
    return Vec2(-direction.y, direction.x)


def dot(a, b):
    return a.x*b.x+a.y*b.y


def turn(direction, angle):
    return direction*cos(angle)+side_of(direction)*sin(angle)


def projected_bend(direction, facing, base_angle, bow_angle):
    """低头决定下沉量，朝向只决定前伸的横向投影；不归一化以保留正面透视缩短"""
    angle = base_angle+bow_angle
    drop = cos(angle)-cos(base_angle)
    sideways = (sin(angle)-sin(base_angle))*facing
    return turn(direction, base_angle*facing)+direction*drop+side_of(direction)*sideways


def follow(value, target, rate):
    value += (target-value)*rate
    return target if abs(target-value) < 1e-5 else value


@dataclass(frozen=True, slots=True)
class PostureFrame:
    points: tuple[Vec2, ...]
    stations: tuple[float, ...]
    facing: float
    head_facing: float
    curve: SpineCurve = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, 'curve', SpineCurve(self.points, self.stations))

    @property
    def chest(self):
        return self.points[2]

    @property
    def chest_direction(self):
        return self.curve.tangents[2]

    @property
    def head_direction(self):
        return self.curve.tangents[4]

    def axis(self, y):
        return self.curve.sample(y)

    def cloth_point(self, x, y):
        center, direction = self.axis(y)
        return center+side_of(direction)*x

    def neck_controls(self, head):
        root = self.points[3]
        length = (head-root).length()
        return (root, root+self.curve.tangents[3]*(length*.40),
                head-self.head_direction*(length*.30), head)


class PrincePosture:
    def __init__(self, upper, direction, look, neck_length):
        self.upper = self.previous_upper = upper
        self.direction = self.previous_direction = direction
        self.facing = self.previous_facing = self.target_facing(direction, look)
        self.head_facing = self.previous_head_facing = self.facing
        self.low_look = max(0., -dot(look, direction))
        self.neck_length = neck_length
        art = robe_layout()
        self.tail_length = art.height-art.join_y
        self.stations = (-WAIST_DEPTH-self.tail_length, -WAIST_DEPTH, 0., 6., neck_length)
        goals = self.goals(upper, direction)
        self.spine = PrinceSpine(goals)
        self.points = self.spine.points
        self.target = goals[-1]
        self.offset = Vec2()
        self.maximum_speed = 0.

    @staticmethod
    def target_facing(direction, look):
        return max(-1., min(1., dot(look, side_of(direction))*1.35))

    @property
    def settled(self):
        return self.spine.settled

    def frame(self, upper, direction, alpha=1.):
        origin = self.previous_upper.lerp(self.upper, alpha)
        axis = unit(self.previous_direction.lerp(self.direction, alpha), self.direction)
        old_side, side = side_of(axis), side_of(direction)
        points = []
        for p in self.points:
            delta = p.sample(alpha)-origin
            points.append(upper+side*dot(delta, old_side)+direction*dot(delta, axis))
        return PostureFrame(tuple(points), self.stations,
                            self.previous_facing+(self.facing-self.previous_facing)*alpha,
                            self.previous_head_facing+(self.head_facing-self.previous_head_facing)*alpha)

    def goals(self, upper, direction):
        waist = upper-direction*WAIST_DEPTH
        low = max(0., min(1., self.low_look))
        body_low = low**BODY_BOW_POWER
        neck_low = 1.-(1.-low)**NECK_BOW_POWER
        chest_axis = projected_bend(direction, self.facing, LOOK_BEND,
                                    LOW_LOOK_BEND*body_low)
        neck_axis = projected_bend(direction, self.facing, NECK_LOOK_BEND+NECK_BEND,
                                   LOW_NECK_BEND*neck_low)
        head_axis = projected_bend(direction, self.head_facing, NECK_LOOK_BEND*.85+NECK_BEND,
                                   LOW_NECK_BEND*.85*neck_low)
        chest = waist+chest_axis*(WAIST_DEPTH-CHEST_DROP)
        neck = chest+neck_axis*6.
        head = neck+head_axis*(self.neck_length-6.)
        return (waist-direction*self.tail_length, waist, chest, neck, head)

    def reset_head(self, head):
        head.position = head.previous_position = self.points[-1].position
        head.velocity = head.drive_velocity = Vec2()

    def step(self, head, upper, direction, look, *, grab=None, gravity=1.):
        self.previous_upper, self.upper = self.upper, upper
        self.previous_direction, self.direction = self.direction, direction
        self.previous_facing, self.previous_head_facing = self.facing, self.head_facing
        facing = self.target_facing(direction, look)
        self.facing = follow(self.facing, facing, CHEST_FOLLOW)
        self.head_facing = follow(self.head_facing, self.facing, HEAD_FOLLOW)
        self.low_look = follow(self.low_look, max(0., -dot(look, direction)), LOW_LOOK_FOLLOW)
        goals = self.goals(upper, direction)
        self.spine.step(goals, grab=grab, gravity=gravity)
        self.target = goals[-1]
        point = self.points[-1]
        head.position, head.previous_position, head.velocity = point.position, point.previous_position, point.velocity
        head.drive_velocity = Vec2()
        self.offset = head.position-self.target
        self.maximum_speed = max(self.spine.maximum_speed,
                                 abs(self.facing-self.previous_facing)*20.,
                                 abs(self.head_facing-self.previous_head_facing)*self.neck_length)
