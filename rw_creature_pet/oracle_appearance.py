"""Moon 的外观状态：固定 40 Hz 的布料、肢体与连接线，不反向驱动物理导航。

参考 OracleGraphics.Gown / UbilicalCord / GenericBodyPart。原版房间中的长线
改为底座供线并允许小幅越界；布料使用固定视觉重力，限幅与阻尼适配窄活动带。
"""
from dataclasses import dataclass
from math import atan2, cos, pi, sin, sqrt

from .geometry import Vec2
from .oracle_cords import OracleCords


def normalized(v, fallback=Vec2(0, -1)):
    length = v.length()
    return v * (1 / length) if length > 1e-9 else fallback


def clamp_length(v, maximum):
    return v * min(1., maximum / max(v.length(), 1e-9))


def perpendicular(v):
    return Vec2(-v.y, v.x)


def rotate(v, angle):
    c, s = cos(angle), sin(angle)
    return Vec2(v.x*c - v.y*s, v.x*s + v.y*c)


@dataclass(slots=True)
class SoftPoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()

    @classmethod
    def at(cls, p):
        return cls(p, p)

    def pin(self, target):
        self.previous_position = self.position
        self.position = target
        self.velocity = target - self.previous_position

    def follow(self, target, spring=.10, damping=.78, slack=4.):
        self.previous_position = self.position
        v = self.velocity * damping + (target - self.position) * spring
        self.position = target + clamp_length(self.position + v - target, slack)
        # 约束后的速度才进入下一 tick，避免在限幅边缘累积能量。
        self.velocity = self.position - self.previous_position

    def sample(self, alpha):
        a, b = self.previous_position, self.position
        return Vec2(a.x+(b.x-a.x)*alpha, a.y+(b.y-a.y)*alpha)


@dataclass(slots=True)
class HangingHand(SoftPoint):
    """原版 GenericBodyPart 手部；积分速度与约束后的实际位移分开保存。"""
    drive_velocity: Vec2 = Vec2()
    MAX_REACH = 15.

    def step(self, origin, host_velocity, force):
        self.previous_position = self.position
        predicted = self.position + self.drive_velocity
        self.position = origin + clamp_length(predicted-origin, self.MAX_REACH)
        correction = predicted-self.position
        # GenericBodyPart.Update -> ConnectToPoint(push=False, adapt=.3,
        # exaggerate=.01) -> OracleGraphics 的垂手受力。屏幕坐标 y 向下。
        velocity = self.drive_velocity*.98 + host_velocity*.01 - correction
        self.drive_velocity = (velocity-host_velocity)*.7 + host_velocity + force
        # 静止时 drive_velocity 仍含下一 tick 会被长度约束抵消的径向分量；
        # 不把它当成可见运动，否则外观永远无法休眠。
        self.velocity = self.position-self.previous_position


@dataclass(slots=True)
class ClothPoint(SoftPoint):
    drive_velocity: Vec2 = Vec2()

    def step(self, goal, force, slack, damping):
        self.previous_position = self.position
        predicted = self.position+self.drive_velocity
        self.position = goal+clamp_length(predicted-goal, slack)
        # Gown.Update：只在超出偏移半径时拉回，半径以内由受力和邻点驱动。
        self.drive_velocity = self.drive_velocity*damping+force+self.position-predicted
        self.velocity = self.position-self.previous_position


def arm_elbow(a, b, length, index, region):
    """沿原版交替弯折侧，使用 2/3 + 1/3 肘部结构；窄带中收拢肘高。

    两主关节仍由已验证的支撑求解器决定。几何只读，渲染插值帧也检查两杆，
    不能用遮罩藏掉穿入中央区的杆件，也不在运动途中突然换弯折侧。
    """
    delta = b - a
    d = max(delta.length(), .001)
    long, short = length * 2/3, length / 3
    along = max(.2*d, min(.8*d, (d*d + long*long - short*short) / (2*d)))
    height = min(24., sqrt(max(0., long*long - along*along)))
    foot = a + normalized(delta) * along
    offset = perpendicular(normalized(delta)) * (height * (1 if index % 2 == 0 else -1))
    def safe(p):
        return region.segment_safe(a, p) and region.segment_safe(p, b)
    candidate = foot + offset
    if safe(candidate):
        return candidate
    lo, hi = 0., 1.
    for _ in range(12):
        mid = (lo + hi) * .5
        if safe(foot + offset * mid):
            lo = mid
        else:
            hi = mid
    return foot + offset * lo


class OracleAppearance:
    CLOTH_DIVS = 11
    CLOTH_SLACK = 9.
    CLOTH_GRAVITY = .45  # 原版 0.9 × room.gravity；桌面使用固定视觉重力 0.5。
    CLOTH_DAMPING = .90  # 原版 .999；桌宠更快收敛，仍保留起停摆动。
    MAIN_CORD_POINTS = 80
    SMALL_CORDS = 14
    SMALL_CORD_POINTS = 20
    NECKLACE_POINTS = 8  # 两个固定端点 + 六颗珠子；移除原中央十字珠。
    NECKLACE_LINK_LENGTH = 2.6
    NECKLACE_GRAVITY = .12
    NECKLACE_DAMPING = .84
    NECKLACE_PASSES = 8
    NECKLACE_ANCHOR_HALF = 4.5
    NECKLACE_ANCHOR_UP = 8.

    def __init__(self, scene):
        self.sway = self.previous_sway = self.sway_velocity = 0.
        self.last_body_velocity = scene.body.chunks[0].velocity
        self.upper = scene.body.chunks[0].position
        self.direction = scene.body.direction
        self.lower = self.upper - self.direction * 9
        self.head = SoftPoint.at(scene.head.position)
        # 从受力平衡位置创建，避免重置时双手从身体中心突然落下。
        self.hands = [HangingHand.at(self.upper + normalized(f)*HangingHand.MAX_REACH)
                      for f in self.hand_forces()]
        self.feet = [SoftPoint.at(p) for p in self.foot_goals()]
        n = self.CLOTH_DIVS
        self._cloth_local = [((2*x/(n-1)-1)*(5+6*y/(n-1)),
                              (5-23*y/(n-1))*(1+sin(pi*x/(n-1))*.35*(2*y/(n-1)-1)))
                             for y in range(n) for x in range(n)]
        self._cloth_forces = []
        for i, (x, y) in enumerate(self._cloth_local):
            angle = pi if y+9 > 0 and abs(x) < 1e-8 else atan2(-x, -(y+9))
            angle *= (i//n)/(n-1)
            self._cloth_forces.append((-.02*cos(angle), -.02*sin(angle)))
        goals = self.cloth_goals()
        # 从接近垂坠平衡的形态创建，避免重置时整片衣袍突然落下。
        # 这只是初始位置，运行时没有指向该姿态的恢复弹簧。
        self.cloth = [ClothPoint.at(p+Vec2(0, self.CLOTH_SLACK*(i//n)/(n-1)))
                      for i, p in enumerate(goals)]
        self.cloth_links = [(y*n+x, y*n+x+1) for y in range(n) for x in range(n-1)]
        self.cloth_links += [(y*n+x, (y+1)*n+x) for y in range(n-1) for x in range(n)]
        # 原版按列更新，每点依次访问左、上、右、下；邻边会从两端各计算一次。
        self._cloth_order = [y*n+x for x in range(n) for y in range(n)]
        self._cloth_neighbors = [
            [(b*n+a, (goals[b*n+a]-goals[y*n+x]).length())
             for a, b in ((x-1, y), (x, y-1), (x+1, y), (x, y+1))
             if 0 <= a < n and 0 <= b < n]
            for y in range(n) for x in range(n)]
        self._cloth_buffers = [[0.]*len(self.cloth) for _ in range(4)]
        side = perpendicular(self.direction)
        self.necklace = [SoftPoint.at(self.upper
            + side*((2*i/(self.NECKLACE_POINTS-1)-1)*self.NECKLACE_ANCHOR_HALF)
            + self.direction*(self.NECKLACE_ANCHOR_UP-9*sin(pi*i/(self.NECKLACE_POINTS-1))))
            for i in range(self.NECKLACE_POINTS)]
        # 只在创建时预收敛，避免第一帧从直线掉下；运行时由重力和长度约束决定。
        for _ in range(120):
            self.step_necklace()
        for p in self.necklace:
            p.previous_position = p.position
            p.velocity = Vec2()
        self.cords = OracleCords(scene, self.head.position)
        self.main_cord = self.cords.main.points
        self.small_cords = [rope.points for rope in self.cords.fine]
        self._points = [self.head, *self.hands, *self.feet, *self.cloth, *self.necklace, *self.main_cord,
                        *(p for cord in self.small_cords for p in cord)]
        self.sleeping = False
        self.revision = 0
        self._quiet_ticks = 0
        self._sleep_inputs = ()
        self.cog_turns = [0.] * 4
        self.previous_cog_turns = self.cog_turns.copy()
        self._arm_spans = self.arm_spans(scene)

    @staticmethod
    def arm_spans(scene):
        nodes = [j.position for j in scene.arm.joints] + [scene.body.chunks[1].position]
        return [(b-a).length() for a, b in zip(nodes, nodes[1:])]

    def hand_forces(self):
        # OracleGraphics.cs:1652-1654；完好 Moon 的零重力场景也保留固定
        # 向画面下方 .5、沿躯干向下 .3、左右外展 .3，不追踪固定放手位置。
        side = perpendicular(self.direction)
        return [Vec2(0, .5) - self.direction*.3 + side*(sign*.3) for sign in (-1, 1)]

    def foot_goals(self):
        side = perpendicular(self.direction)
        return [self.lower + side*(sign*4.) - self.direction*8.5 for sign in (-1, 1)]

    def cloth_goals(self):
        side = perpendicular(self.direction)
        # 原版 IdealPosForPoint：领半宽 5、下摆半宽 11、中央下摆长 18*1.35。
        return [Vec2(self.upper.x+side.x*x+self.direction.x*y,
                     self.upper.y+side.y*x+self.direction.y*y) for x, y in self._cloth_local]

    def necklace_anchors(self):
        side = perpendicular(self.direction)
        return [self.upper+self.direction*self.NECKLACE_ANCHOR_UP
                + side*(sign*self.NECKLACE_ANCHOR_HALF) for sign in (-1, 1)]

    def step_necklace(self):
        """胸前短链：两个颈侧端点固定，六颗珠子靠重力和阻尼下垂。"""
        points, anchors = self.necklace, self.necklace_anchors()
        side = perpendicular(self.direction)
        host_velocity = (anchors[0]-points[0].position+anchors[1]-points[-1].position)*.5
        last = len(points)-1
        for i, p in enumerate(points):
            p.previous_position = p.position
            if i in (0, last):
                p.position = anchors[0 if i == 0 else 1]
            else:
                # 阻尼相对于佩戴者，避免匀速向下移动时全局空气阻力把项链
                # 持续拖到脸前；加减速仍保留相对速度，产生短暂摆动。
                p.position += (host_velocity+(p.velocity-host_velocity)*self.NECKLACE_DAMPING
                               + Vec2(0, self.NECKLACE_GRAVITY))
        for iteration in range(self.NECKLACE_PASSES):
            # 交替求解方向，避免把最后一次修正的偏差固定堆在同一侧。
            edges = range(last) if iteration % 2 == 0 else range(last-1, -1, -1)
            for i in edges:
                a, b = points[i], points[i+1]
                delta = b.position-a.position
                distance = delta.length()
                correction = delta*((distance-self.NECKLACE_LINK_LENGTH)/max(distance, 1e-9))
                if i == 0:
                    b.position -= correction
                elif i+1 == last:
                    a.position += correction
                else:
                    a.position += correction*.5
                    b.position -= correction*.5
            # 胸前投影中的领口表面：链条可松弛摆动，但不能翻到高领/脸前。
            # 仅在进入表面时推出，不把珠子追踪到固定的理想位置。
            for p in points[1:-1]:
                offset = p.position-self.upper
                across = offset.x*side.x+offset.y*side.y
                down = -(offset.x*self.direction.x+offset.y*self.direction.y)
                minimum = (-self.NECKLACE_ANCHOR_UP+.5
                           + 5*sqrt(max(0., 1-(across/self.NECKLACE_ANCHOR_HALF)**2)))
                if down < minimum:
                    p.position += self.direction*(down-minimum)
        for p in points:
            p.velocity = p.position-p.previous_position

    def step_cloth(self):
        goals = self.cloth_goals()
        n = self.CLOTH_DIVS
        direction, side = self.direction, perpendicular(self.direction)
        x, y, vx, vy = self._cloth_buffers
        for i, p in enumerate(self.cloth):
            p.previous_position = p.position
            x[i], y[i] = p.position.x, p.position.y
            vx[i], vy[i] = p.drive_velocity.x, p.drive_velocity.y
        for i in self._cloth_order:
            goal = goals[i]
            depth = (i//n)/(n-1)
            # 力的局部方向仅由布点的固定坐标决定；创建时计算三角函数。
            along, across = self._cloth_forces[i]
            fx, fy = direction.x*along+side.x*across, direction.y*along+side.y*across
            px, py = x[i]+vx[i], y[i]+vy[i]
            dx, dy = px-goal.x, py-goal.y
            factor = min(1., self.CLOTH_SLACK*depth/max(sqrt(dx*dx+dy*dy), 1e-9))
            x[i], y[i] = goal.x+dx*factor, goal.y+dy*factor
            vx[i] = vx[i]*self.CLOTH_DAMPING+fx+x[i]-px
            vy[i] = vy[i]*self.CLOTH_DAMPING+fy+self.CLOTH_GRAVITY+y[i]-py
            for j, rest in self._cloth_neighbors[i]:
                dx, dy = x[j]-x[i], y[j]-y[i]
                distance = sqrt(dx*dx+dy*dy)
                factor = (distance-rest)*.05/max(distance, 1e-9)
                tx, ty = dx*factor, dy*factor
                vx[i] += tx; vy[i] += ty
                vx[j] -= tx; vy[j] -= ty
        for i, p in enumerate(self.cloth):
            p.position = Vec2(x[i], y[i])
            p.velocity = p.position-p.previous_position
            p.drive_velocity = Vec2(vx[i], vy[i])

    def step(self, scene):
        # 转动量只来自主跨度变化；固定 40 Hz 更新，静止不空转，绘制只插值。
        spans = self.arm_spans(scene)
        self.previous_cog_turns = self.cog_turns.copy()
        for i, (old, new) in enumerate(zip(self._arm_spans, spans)):
            self.cog_turns[i] += (old-new)/scene.arm.lengths[i]*2*(-1 if i % 2 == 0 else 1)
        self._arm_spans = spans
        inputs = (scene.body.chunks[0].position, scene.body.chunks[1].position,
                  scene.head.position, scene.look_direction, *(j.position for j in scene.arm.joints))
        if self.sleeping and all((a-b).length() < .001 for a, b in zip(inputs, self._sleep_inputs)):
            # 静置收敛后休眠；新移动、转头、倾角都会唤醒。不依赖墙钟时间。
            return
        self.sleeping = False
        self.revision += 1
        self.previous_sway = self.sway
        upper = scene.body.chunks[0]
        acceleration = upper.velocity - self.last_body_velocity
        side = perpendicular(scene.body.direction)
        lateral = acceleration.x*side.x + acceleration.y*side.y
        self.sway_velocity = self.sway_velocity*.78 - self.sway*.085 + lateral*.035
        self.sway = max(-.065, min(.065, self.sway + self.sway_velocity))
        self.last_body_velocity = upper.velocity
        self.upper = upper.position
        self.direction = rotate(scene.body.direction, self.sway)
        self.lower = self.upper - self.direction * 9
        self.head.pin(self.upper + rotate(scene.head.position-self.upper, self.sway))
        for hand, force in zip(self.hands, self.hand_forces()):
            hand.step(self.upper, upper.velocity, force)
        for p, goal in zip(self.feet, self.foot_goals()):
            p.follow(goal, spring=.075, damping=.80, slack=5.)
            p.position = self.lower + clamp_length(p.position-self.lower, 10)
            p.velocity = p.position-p.previous_position
        self.step_cloth()
        self.step_necklace()
        self.cords.step(scene, self.head.position, self.upper, self.direction, scene.look_direction)
        self._quiet_ticks = (self._quiet_ticks+1 if self.maximum_speed < .002
                             and abs(self.sway_velocity) < 1e-6
                             and max((a-b).length() for a, b in zip(inputs, self._sleep_inputs)) < .001
                             else 0) if self._sleep_inputs else 0
        self._sleep_inputs = inputs
        if self._quiet_ticks >= 30:
            self.sleeping = True
            self._sleep_inputs = inputs
            self.previous_sway = self.sway
            for p in self._points:
                p.previous_position = p.position
                p.velocity = Vec2()

    @property
    def points(self):
        return self._points

    @property
    def maximum_speed(self):
        return max(p.velocity.length() for p in self.points)
