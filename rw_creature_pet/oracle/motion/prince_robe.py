"""Prince 下半衣袍的双层网格，固定接缝，独立惯性和重力回摆，固定 40 Hz"""
from dataclasses import dataclass
from math import sin, pi

from ...shared.geometry import Vec2
from ..prince_assets import robe_layout
from .prince import WAIST_DEPTH


CHEST_WIDTH = 8.
CHEST_HEIGHT = 8.
SHOULDER_HALF = 3.7
UPPER_LENGTH = WAIST_DEPTH
COLUMNS = 5
PIN_LENGTH = 6.  # PNG 顶部共同贴合接缝，下方才逐渐分离
# 每组依次为回正、速度保留、加速度惯性、最大偏移，后层比前层更松软
BACK_MOTION = (.045, .78, 1.1, 10.)
FRONT_MOTION = (.07, .70, .75, 7.)
BACK_DRIFT_MOTION = (.022, .88, 1.20, 12.)
FRONT_DRIFT_MOTION = (.038, .83, .85, 9.)


def unit(v, fallback):
    return v*(1/v.length()) if v.length() > 1e-9 else fallback


def upper_cloth_point(x, y, n):
    """窄肩渐宽到素材的实色上口，接缝处外轮廓斜率收平"""
    t, across = y/(n-1), 2*x/(n-1)-1
    art = robe_layout()
    half = SHOULDER_HALF+((art.right-art.left)/2-SHOULDER_HALF)*t*(2-t)
    top = 5.*(1-.35*sin(pi*x/(n-1)))
    return across*half, top*(1-t)-UPPER_LENGTH*t


@dataclass(slots=True)
class RobePoint:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()

    def sample(self, alpha):
        return self.previous_position.lerp(self.position, alpha)


class RobeLayer:
    def __init__(self, goals, coords, *, back):
        self.points = [RobePoint(p, p) for p in goals]
        self.offsets = [Vec2() for _ in goals]
        self.speeds = [Vec2() for _ in goals]
        self.targets = goals
        self.target_speeds = [Vec2() for _ in goals]
        self.motion = BACK_MOTION if back else FRONT_MOTION
        self.drift_motion = BACK_DRIFT_MOTION if back else FRONT_DRIFT_MOTION
        self.spring, self.damping, self.inertia, self.limit = self.motion
        self.weightlessness = 0.
        height = robe_layout().height
        self.weights = [max(0., (p.y-PIN_LENGTH)/(height-PIN_LENGTH))**1.6 for p in coords]
        self.neighbors = [tuple(j for j in (i-COLUMNS, i+COLUMNS,
                          i-1 if i%COLUMNS else -1, i+1 if i%COLUMNS < COLUMNS-1 else -1)
                          if 0 <= j < len(goals)) for i in range(len(goals))]
        self.quiet_ticks = 0
        self.settled = False
        self.gravity = None

    def step(self, goals, gravity, *, weightlessness=0.):
        speeds = [a-b for a, b in zip(goals, self.targets)]
        speed = max(v.length() for v in speeds)
        weightlessness = max(0., min(1., weightlessness))
        softness_changed = weightlessness != self.weightlessness
        if self.settled and speed < 1e-6 and gravity == self.gravity and not softness_changed:
            return
        self.settled = False
        self.weightlessness = weightlessness
        self.spring, self.damping, self.inertia, self.limit = (
            a+(b-a)*weightlessness for a, b in zip(self.motion, self.drift_motion))
        accelerations = [a-b for a, b in zip(speeds, self.target_speeds)]
        self.targets, self.target_speeds, self.gravity = goals, speeds, gravity
        if speed > 60.:
            # 重置、工作区突变等整体搬移不留下长拖尾
            self.offsets = [Vec2() for _ in goals]
            self.speeds = self.target_speeds = [Vec2() for _ in goals]
            for p, goal in zip(self.points, goals):
                p.position = p.previous_position = goal
                p.velocity = Vec2()
            self.quiet_ticks = 0
            return
        offsets, velocities = [], []
        for i, (p, goal, weight) in enumerate(zip(self.points, goals, self.weights)):
            p.previous_position = p.position
            if weight == 0.:
                offset = velocity = Vec2()
            else:
                offset = self.offsets[i]
                neighbors = self.neighbors[i]
                average = Vec2(sum(self.offsets[j].x for j in neighbors),
                               sum(self.offsets[j].y for j in neighbors))*(1/len(neighbors))
                velocity = (self.speeds[i]*self.damping-offset*self.spring
                            +(average-offset)*.10+(gravity-accelerations[i]*self.inertia)*weight)
                offset += velocity
                limit = self.limit*weight
                if offset.length() > limit:
                    normal = unit(offset, Vec2())
                    offset = normal*limit
                    velocity -= normal*max(0., velocity.x*normal.x+velocity.y*normal.y)
            p.position = goal+offset
            p.velocity = p.position-p.previous_position
            offsets.append(offset)
            velocities.append(velocity)
        self.offsets, self.speeds = offsets, velocities
        quiet = (not softness_changed and speed < .001
                 and max(p.velocity.length() for p in self.points) < .001)
        self.quiet_ticks = self.quiet_ticks+1 if quiet else 0
        if self.quiet_ticks >= 20:
            self.settled = True
            self.speeds = [Vec2() for _ in goals]
            for p in self.points:
                p.previous_position, p.velocity = p.position, Vec2()


class PrinceRobe:
    def __init__(self, app):
        self.art = art = robe_layout()
        ys = (0., art.join_y, PIN_LENGTH)+tuple(PIN_LENGTH+(art.height-PIN_LENGTH)*i/6 for i in range(1, 7))
        self.coords = tuple(Vec2(art.width*x/(COLUMNS-1), y) for y in ys for x in range(COLUMNS))
        self.triangles = tuple(ids for y in range(len(ys)-1) for x in range(COLUMNS-1)
                              for i in (y*COLUMNS+x,)
                              for ids in ((i, i+1, i+COLUMNS+1), (i, i+COLUMNS+1, i+COLUMNS)))
        goals, _ = self.goals(app)
        self.back = RobeLayer(goals, self.coords, back=True)
        self.front = RobeLayer(goals, self.coords, back=False)
        self.layers = (self.back, self.front)
        self.points = [p for layer in self.layers for p in layer.points]

    @property
    def settled(self):
        return all(layer.settled for layer in self.layers)

    def goals(self, app):
        art = self.art
        frame = app.prince_posture.frame(app.upper, app.direction)
        # 与上衣共用原点、中心线和单位法线，不再把下摆重新旋转到布料最后一行
        # PNG 透明边距保持原尺寸，实色上口的中点对应躯干中轴
        middle = (art.left+art.right)/2
        goals = tuple(frame.cloth_point(uv.x-middle, -UPPER_LENGTH-(uv.y-art.join_y))
                      for uv in self.coords)
        down = frame.axis(-UPPER_LENGTH)[1]*-1.
        # 重力只激发侧向垂坠，不在静止直立时把 PNG 纵向拉长
        world = Vec2(0., .12*app.gravity_scale)
        gravity = world-down*(world.x*down.x+world.y*down.y)
        return goals, gravity

    def step(self, app):
        goals, gravity = self.goals(app)
        for layer in self.layers:
            layer.step(goals, gravity, weightlessness=app.prince_posture.spine.weightlessness)
