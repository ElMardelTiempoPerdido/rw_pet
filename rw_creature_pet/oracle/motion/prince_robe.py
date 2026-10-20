"""Prince 下半衣袍的双层网格，固定接缝，独立惯性和重力回摆，固定 40 Hz"""
from dataclasses import dataclass
from math import floor, sin, pi

from ...shared.geometry import Vec2
from ..prince_assets import robe_layout
from .prince import WAIST_DEPTH, dot, side_of


CHEST_WIDTH = 8.
CHEST_HEIGHT = 8.
SHOULDER_HALF = 3.7
UPPER_LENGTH = 14.
UPPER_SLACK = 3.
COLUMNS = 5
PIN_LENGTH = 6.  # PNG 顶部共同贴合接缝，下方才逐渐分离


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


def row_point(cloth, row, n, u):
    # 透明边距也参与网格；在实色连接段外线性延长，保持原 PNG 的自然宽度
    x = u*(n-1)
    index = max(0, min(n-2, floor(x)))
    a, b = cloth[row*n+index:row*n+index+2]
    return a.position.lerp(b.position, x-index)


class RobeLayer:
    def __init__(self, goals, coords, *, back):
        self.points = [RobePoint(p, p) for p in goals]
        self.offsets = [Vec2() for _ in goals]
        self.speeds = [Vec2() for _ in goals]
        self.targets = goals
        self.target_speeds = [Vec2() for _ in goals]
        self.spring, self.damping, self.inertia, self.limit = ((.045, .78, 1.1, 10.) if back
                                                             else (.07, .70, .75, 7.))
        height = robe_layout().height
        self.weights = [max(0., (p.y-PIN_LENGTH)/(height-PIN_LENGTH))**1.6 for p in coords]
        self.neighbors = [tuple(j for j in (i-COLUMNS, i+COLUMNS,
                          i-1 if i%COLUMNS else -1, i+1 if i%COLUMNS < COLUMNS-1 else -1)
                          if 0 <= j < len(goals)) for i in range(len(goals))]
        self.quiet_ticks = 0
        self.settled = False
        self.gravity = None

    def step(self, goals, gravity):
        speeds = [a-b for a, b in zip(goals, self.targets)]
        speed = max(v.length() for v in speeds)
        if self.settled and speed < 1e-6 and gravity == self.gravity:
            return
        self.settled = False
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
        quiet = speed < .001 and max(p.velocity.length() for p in self.points) < .001
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
        n, art = app.CLOTH_DIVS, self.art
        seams = []
        for x in range(COLUMNS):
            u = (art.width*x/(COLUMNS-1)-art.left)/(art.right-art.left)
            seams.append(row_point(app.cloth, n-1, n, u))
        center = seams[COLUMNS//2]
        middle_u = (art.width/2-art.left)/(art.right-art.left)
        above = row_point(app.cloth, n-2, n, middle_u)
        down = unit(center-above, app.direction*-1.)
        side = Vec2(down.y, -down.x)
        native = tuple(center+side*(art.width*x/(COLUMNS-1)-art.width/2)
                       for x in range(COLUMNS))
        frame = app.prince_posture.frame(app.upper, app.direction)
        root, root_up = frame.axis(-WAIST_DEPTH)
        root_side, root_down = side_of(root_up), root_up*-1.
        def orient(v):
            return side*dot(v, root_side)+down*dot(v, root_down)
        rows = {}
        for uv in self.coords[::COLUMNS]:
            p, up = frame.axis(-WAIST_DEPTH-(uv.y-art.join_y))
            rows[uv.y] = center+orient(p-root), unit(orient(side_of(up)), side)
        # 沿身体轴逐行弯曲，但每行仍使用单位法线和原图宽度，避免转弯时撑宽
        # 顶部贴合真实接缝；两层自己的细小惯性叠加在共同身体轴之上
        goals = []
        for i, uv in enumerate(self.coords):
            column = i%COLUMNS
            t = max(0., min(1., (uv.y-art.join_y)/max(PIN_LENGTH-art.join_y, 1e-9)))
            join_weight = 1-t*t*(3-2*t)
            row_center, row_side = rows[uv.y]
            goals.append(row_center+row_side*(uv.x-art.width/2)
                         +(seams[column]-native[column])*join_weight)
        # 重力只激发侧向垂坠，不在静止直立时把 PNG 纵向拉长
        world = Vec2(0., .12*app.gravity_scale)
        gravity = world-down*(world.x*down.x+world.y*down.y)
        return tuple(goals), gravity

    def step(self, app):
        goals, gravity = self.goals(app)
        for layer in self.layers:
            layer.step(goals, gravity)
