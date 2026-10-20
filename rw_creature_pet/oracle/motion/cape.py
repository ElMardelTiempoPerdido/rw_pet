"""斗篷下摆的轻量惯性：固定 40 Hz 更新，三个响应点，不反向驱动人偶"""
from dataclasses import dataclass

from ...shared.geometry import Vec2


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


def dot(a, b):
    return a.x*b.x+a.y*b.y


def arm_lift(upper, direction, hands, shoulder_width):
    side, down = Vec2(-direction.y, direction.x), direction*(-1)
    result = []
    for hand, sign in zip(hands, (-1, 1)):
        delta = hand-upper-side*(sign*shoulder_width/2)
        result.append(smooth((1-dot(delta, down)/max(delta.length(), 1e-9)-.04)/.85))
    return tuple(result)


def side_tensions(lift):
    """横向一起贴合袖缘，纵向主要由同侧手臂撑起，对侧只传递少量上提"""
    highest = max(lift)
    across = smooth(highest/.38)
    shortening = tuple(across*(.25+.75*value/max(highest, 1e-9)) for value in lift)
    return across, shortening


def motion_shape(shape):
    return (shape.cape.length, shape.chest_height, shape.shoulder_width,
            shape.sleeve_root_width, shape.sleeve_cuff_width)


def max_deflection(length):
    return min(9., length*.23)


@dataclass(frozen=True, slots=True)
class CapeOffsets:
    left: Vec2 = Vec2()
    right: Vec2 = Vec2()
    bottom: Vec2 = Vec2()

    def sample(self, other, alpha):
        return CapeOffsets(*(a.lerp(b, alpha) for a, b in zip(self.points, other.points)))

    @property
    def points(self):
        return self.left, self.right, self.bottom


class CapeMotion:
    """以姿态参考点的加速度激发回摆，匀速移动和静止时恢复已有静态轮廓"""
    def __init__(self, shape, upper, direction, hands):
        self.shape = motion_shape(shape)
        length = self.shape[0]
        self.spring = .09/(.7+length/24)
        self.damping = .84+.04*(length-8)/40
        self.limit = max_deflection(length)
        self.targets = self.reference_points(upper, direction, hands)
        self.target_velocities = (Vec2(),)*3
        self.offsets = (Vec2(),)*3
        self.velocities = (Vec2(),)*3
        self.previous = self.current = CapeOffsets()
        self.settled = True
        self.quiet_ticks = 0

    def reference_points(self, upper, direction, hands):
        length, chest_height, shoulder_width, root_width, cuff_width = self.shape
        side, down = Vec2(-direction.y, direction.x), direction*(-1)
        lift = arm_lift(upper, direction, hands, shoulder_width)
        tension, shortening = side_tensions(lift)
        width = shoulder_width/2+root_width*.7
        top = -chest_height*.75
        # 只捕捉撑起姿态的变化，不在物理步中构建袖子路径或 Qt 裁剪几何
        targets = []
        for hand, sign, shorten in zip(hands, (-1, 1), shortening):
            resting = upper+side*(sign*width)+down*(top+length-min(3., length*.14))
            raised = hand-down*(cuff_width*.5)
            delta = raised-resting
            targets.append(resting+side*(dot(delta, side)*tension)+down*(dot(delta, down)*shorten))
        targets.append(upper+side*(width*.54*(lift[0]-lift[1]))
                       + down*(top+length-length*(.07*max(lift)+.04*min(lift))))
        return tuple(targets)

    def step(self, upper, direction, hands):
        targets = self.reference_points(upper, direction, hands)
        speeds = tuple(a-b for a, b in zip(targets, self.targets))
        accelerations = tuple(a-b for a, b in zip(speeds, self.target_velocities))
        self.targets, self.target_velocities = targets, speeds
        self.previous = self.current
        # 重置位置或工作区突变整体搬移，不能留下巨大惯性；也清除上一帧插值
        if max(v.length() for v in speeds) > max(80., self.shape[0]*2):
            self.target_velocities = (Vec2(),)*3
            self.settle()
            return
        forcing = max(v.length() for v in accelerations)
        if self.settled and forcing < .001:
            return
        self.settled = False
        offsets, velocities = [], []
        for i, (offset, velocity, acceleration) in enumerate(zip(self.offsets, self.velocities, accelerations)):
            # 自由底弧比侧边响应更慢；世界坐标受力保留转身时的方向惯性
            spring = self.spring*(.75 if i == 2 else 1.)
            velocity = velocity*self.damping-offset*spring-acceleration*.65
            offset += velocity
            limit = self.limit*(1. if i == 2 else .65)
            size = offset.length()
            if size > limit:
                normal = offset*(1/size)
                offset = normal*limit
                # 限幅只去掉向外速度，不积累下一轮反弹能量
                velocity -= normal*max(0., dot(velocity, normal))
            offsets.append(offset)
            velocities.append(velocity)
        self.offsets, self.velocities = tuple(offsets), tuple(velocities)
        side, down = Vec2(-direction.y, direction.x), direction*(-1)
        self.current = CapeOffsets(*(Vec2(dot(v, side), dot(v, down)) for v in offsets))
        quiet = (forcing < .001 and max(v.length() for v in offsets) < .008
                 and max(v.length() for v in velocities) < .002)
        self.quiet_ticks = self.quiet_ticks+1 if quiet else 0
        if self.quiet_ticks >= 8:
            self.settle()

    def settle(self):
        self.offsets = self.velocities = (Vec2(),)*3
        self.previous = self.current = CapeOffsets()
        self.settled = True
        self.quiet_ticks = 0

    def sample(self, alpha):
        return self.previous.sample(self.current, alpha)

    @property
    def maximum_speed(self):
        return max((a-b).length() for a, b in zip(self.current.points, self.previous.points))
