"""白蜥蜴外观参数与独立头尾模拟；不反馈修改身体物理。

品种数值来自 LizardBreeds.WhiteLizard；个体倍率暂固定 1。
尾节构造和刚度衰减参考 LizardGraphics / TailSegment。
"""
from dataclasses import dataclass
from math import atan2, cos, sin, pi, isfinite

from .geometry import Vec2
from .color_effects import ColorEffects
from .gaze import Gaze


def unit(vector: Vec2, fallback=Vec2(1, 0)) -> Vec2:
    length = vector.length()
    return vector * (1 / length) if length > 1e-8 else fallback


@dataclass(frozen=True, slots=True)
class WhiteAppearance:
    head_size: float = 1.0
    head_graphics: tuple[int, ...] = (0, 0, 0, 0, 3)
    limb_size: float = 1.0
    limb_thickness: float = 1.0
    tail_segments: int = 5
    tail_length_factor: float = 1.2
    tail_stiffness: float = 800.0
    tail_stiffness_decline: float = 0.1
    neck_stiffness: float = 0.05
    # 当前确定性调试个体，不是 Unity 随机 ID 生成结果。
    individual_head_size: float = 1.0
    fatness: float = 1.0
    tail_length: float = 1.0
    tail_fatness: float = 1.0
    tail_color: float = 0.0


@dataclass(slots=True)
class VisualPoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()
    radius: float = 0.0
    length: float = 0.0
    stretched: float = 1.0


class LizardAppearance:
    def __init__(self, body, params=WhiteAppearance()):
        self.limb_flips = [1.0] * 4
        self.previous_limb_flips = self.limb_flips.copy()
        self.look_target = None
        self.look_ticks = 0
        self.look_angle = 0.0
        self.gaze = Gaze()
        self._head_anchor = None
        self.params = params
        self.colors = ColorEffects()
        axis = unit(body.chunks[0].position - body.chunks[1].position)
        point = body.chunks[0].position + axis * (23 * params.head_size)
        self.head = VisualPoint(point, point, radius=6 * params.head_size)
        self.tail = []
        point = body.chunks[2].position
        for i in range(params.tail_segments):
            radius = 8 * body.breed.body_size * (params.tail_segments - i) / params.tail_segments
            length = ((16 if i == 0 else 8) + radius) / 2 * params.tail_length_factor * params.tail_length
            point = point - axis * length
            self.tail.append(VisualPoint(point, point, radius=radius, length=length))

    def observe(self, point, ticks=400):
        if point is not None and (not isfinite(point.x) or not isfinite(point.y)):
            raise ValueError('观察点必须为有限坐标')
        if type(ticks) is not int or ticks < 1:
            raise ValueError('观察时长必须为正整数 tick')
        self.look_target = point
        self.look_ticks = ticks if point is not None else 0

    def sync_previous(self):
        self.previous_limb_flips = self.limb_flips.copy()
        self.colors.sync_previous()
        for point in [self.head, *self.tail]:
            point.previous_position = point.position

    @staticmethod
    def limb_flip_target(body, foot, previous):
        hip = body.chunks[foot.chunk_index].position
        # 原版前/后腿符号校正，并转换 Unity y 向上到屏幕 y 向下。
        forward = hip-body.chunks[1].position if foot.chunk_index == 0 else body.chunks[1].position-hip
        delta = foot.position-hip
        signed = forward.x*delta.y-forward.y*delta.x
        if abs(signed) < 1e-6:
            return 1.0 if previous >= 0 else -1.0
        return 1.0 if signed > 0 else -1.0

    def update(self, body, world, feet=None, background=False, travel_direction=Vec2()):
        p = self.params
        self.sync_previous()
        self.colors.update()
        if feet is not None:
            for i, foot in enumerate(feet):
                target = self.limb_flip_target(body, foot, self.limb_flips[i])
                self.limb_flips[i] += (target-self.limb_flips[i])*.3
        axis = unit(body.chunks[0].position - body.chunks[1].position)
        self._update_head(body, world, axis, background, travel_direction)
        # 尾节单独细分积分：先施力，再投影接触/长度，最后从实际位移恢复速度。
        # 避免约束前的弹性速度跨帧积累，与地板形成反复拉伸/回弹。
        dt = .25
        for _ in range(4):
            starts = [segment.position for segment in self.tail]
            for i in range(len(self.tail)-1, -1, -1):
                segment = self.tail[i]
                origin = body.chunks[1].position if i == 0 else body.chunks[2].position if i == 1 else self.tail[i-2].position
                origin = origin.lerp(body.chunks[1].position, .2)
                direction = segment.position-origin
                force = p.tail_stiffness*p.tail_stiffness_decline**i/max(direction.length(), 1)
                acceleration = unit(direction, axis*-1)*force
                if not background:
                    acceleration = acceleration + Vec2(0, .9*(i/(len(self.tail)-1))**3)
                segment.velocity = segment.velocity + acceleration*dt
                segment.position = segment.position + segment.velocity*dt
            previous = body.chunks[2].position
            for segment, start in zip(self.tail, starts):
                if background:
                    segment.position = world.background_position(segment.position, segment.radius)
                else:
                    self._collide(segment, world)
                delta = segment.position-previous
                if delta.length() > segment.length:
                    segment.position = previous + unit(delta)*segment.length
                if background:
                    segment.position = world.background_position(segment.position, segment.radius)
                # 前节中心都位于当前尾节可行高度内，长度投影不会再次穿地。
                velocity = (segment.position-start)*(1/dt)
                segment.velocity = velocity * (.85**dt if segment.position.y >= world.floor_y-segment.radius-1e-6 else .9**dt)
                segment.stretched = min(1., max(.2, (segment.length/max((segment.position-previous).length()*.5, 1e-8)+2)/3))
                previous = segment.position

    def _update_head(self, body, world, axis, background, travel_direction):
        p = self.params
        front = body.chunks[0]
        anchor = front.position + axis*(12*p.head_size)
        point = self.gaze.update(anchor, axis, world, self.look_target)
        if self.look_target is not None:
            self.look_ticks -= 1
            if self.look_ticks <= 0:
                self.look_target = None
        direction = unit(point-front.position, axis)
        angle = atan2(direction.y, direction.x)
        # 原版以观察方向为主，再少量混入路径方向。
        if travel_direction.length() > 1e-6:
            turn = (atan2(travel_direction.y, travel_direction.x)-angle+pi) % (2*pi)-pi
            angle += turn*(.15+p.neck_stiffness*.15)
        desired = (angle-atan2(axis.y, axis.x)+pi) % (2*pi)-pi
        # 越接近正后方，越倾向前身方向；保留桌宠的最大观察角保护。
        backward = max(0.0, -cos(desired))
        desired *= 1-(1-(1-backward)**3)*(1-p.neck_stiffness)
        desired = max(-1.2, min(1.2, desired))
        self.look_angle += max(-.06, min(.06, (desired-self.look_angle)*.15))
        view_axis = Vec2(axis.x*cos(self.look_angle)-axis.y*sin(self.look_angle),
                         axis.x*sin(self.look_angle)+axis.y*cos(self.look_angle))
        previous_anchor = self._head_anchor
        if previous_anchor is None:
            previous_anchor = anchor-(front.position-front.previous_position)
        host_velocity = anchor-previous_anchor
        self._head_anchor = anchor
        # 方向驱动力 + 连接点弹性牵引；没有固定伸长的头部目标坐标。
        # 原版驱动力 Lerp(6,2,neckStiffness) 按桌宠阻尼/子步结构缩放。
        drive = view_axis*((6-4*p.neck_stiffness)*.43*p.head_size)
        dt = .25
        for step in range(4):
            origin = previous_anchor.lerp(anchor, (step+1)*dt)
            start = self.head.position
            force = drive + (origin-start)*.24
            relative = (self.head.velocity-host_velocity)*(.5**dt) + force*dt
            point = start + (host_velocity+relative)*dt
            for _ in range(8):
                before = point
                offset = point-origin
                forward = offset.x*axis.x + offset.y*axis.y
                # 头部可向连接点收缩，但不能折回躯干内部。
                if forward < 2*p.head_size:
                    point = point + axis*(2*p.head_size-forward)
                offset = point-origin
                if offset.length() > 11*p.head_size:
                    point = origin + unit(offset)*(11*p.head_size)
                if background:
                    point = world.background_position(point, self.head.radius)
                else:
                    point = Vec2(max(self.head.radius, min(world.width-self.head.radius, point.x)),
                                 min(world.floor_y-self.head.radius, point.y))
                if (point-before).length() < 1e-10:
                    break
            self.head.position = point
            self.head.velocity = (point-start)*(1/dt)

    @staticmethod
    def _collide(segment, world):
        x, y = segment.position.x, segment.position.y
        vx, vy = segment.velocity.x, segment.velocity.y
        if y >= world.floor_y - segment.radius:
            y = world.floor_y - segment.radius
            vx *= .85
            vy = min(0, vy)
        if x < segment.radius or x > world.width - segment.radius:
            x = max(segment.radius, min(world.width - segment.radius, x))
            vx = 0
        segment.position = Vec2(x, y)
        segment.velocity = Vec2(vx, vy)
