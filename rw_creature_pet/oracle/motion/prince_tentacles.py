"""Prince 的边缘支撑、逐条换抓点与悬空探查，固定 40 Hz"""
from array import array
from dataclasses import dataclass
from math import atan2, ceil, cos, pi, sin

from ...shared.geometry import Vec2
from ..config import EDGE_NAMES
from ..prince_tentacles import TubePath, default_study, make_path
from .navigation import RailPiece, RoundedRail, normalized
from .prince_free_search import FreeTipSearch, WallProbe
from .prince_tentacle_numeric import tentacle_solver


def limited(value, maximum):
    return value*min(1., maximum/max(value.length(), 1e-9))


def perpendicular(value):
    return Vec2(-value.y, value.x)


def edge_direction(directions, outward):
    """按连续的离边朝向混合相邻配置，不随边缘旋转屏幕坐标向量"""
    weights = (max(0., -outward.y), max(0., outward.x),
               max(0., outward.y), max(0., -outward.x))
    result = Vec2()
    for direction, weight in zip(directions, weights):
        result += direction*weight
    # 相邻边配置为相反方向时允许偏好衰减至零，避免归一化造成跳转
    return result*(1./max(1e-9, sum(weights)))


def path_length(points):
    return sum((b-a).length() for a, b in zip(points, points[1:]))


def fit_length(points, maximum):
    """固定两端，收拢求解误差产生的多余弧长，不指定任何参考造型"""
    if maximum is None or path_length(points) <= maximum:
        return points
    line = [points[0].lerp(points[-1], i/(len(points)-1)) for i in range(len(points))]
    line[0], line[-1] = points[0], points[-1]
    lo, hi = 0., 1.
    for _ in range(16):
        weight = (lo+hi)*.5
        candidate = [a.lerp(b, weight) for a, b in zip(line, points)]
        if path_length(candidate) <= maximum:
            lo = weight
        else:
            hi = weight
    result = [a.lerp(b, lo) for a, b in zip(line, points)]
    result[0], result[-1] = points[0], points[-1]
    return result


class GripRail(RoundedRail):
    """从工作区四边内缩的触手抓附轨道，沿用导航的环参数和允许边顺序"""
    EDGE_INSET = 8.  # 逻辑像素，为末端管宽、偏心囊肿及像素化留出显示空间

    def __init__(self, world):
        self.width, self.height = world.width, world.height
        self.inset = min(self.EDGE_INSET, max(0., (min(world.width, world.height)-1.)*.5))
        pad = self.inset
        corners = (Vec2(pad, pad), Vec2(world.width-pad, pad),
                   Vec2(world.width-pad, world.height-pad), Vec2(pad, world.height-pad))
        allowed = {i for i, edge in enumerate(EDGE_NAMES) if edge in world.allowed_edges}
        self.closed = len(allowed) == 4
        first = 0 if self.closed else next(i for i in allowed if (i-1) % 4 not in allowed)
        edges = [(first+i) % 4 for i in range(len(allowed))]
        self.pieces = tuple(RailPiece(corners[i], corners[(i+1) % 4],
                                    (corners[(i+1) % 4]-corners[i]).length()) for i in edges)
        self.ends, total = [], 0.
        for piece in self.pieces:
            total += piece.length
            self.ends.append(total)
        self.length, self.radius = total, 0.

    def bounded(self, s):
        return s if self.closed else max(0., min(self.length, s))


@dataclass
class Node:
    position: Vec2
    previous_position: Vec2
    velocity: Vec2 = Vec2()

    def sample(self, alpha):
        return self.previous_position.lerp(self.position, alpha)


class SupportTentacle:
    """独立分段长度、局部伸出偏好和屏幕重力驱动的柔性支撑链"""
    GRAVITY = .14  # 固定朝屏幕下方，不随停靠边旋转
    ROOT_DIRECTION_FORCE = .65
    ROOT_DIRECTION_SPAN = .22
    BEND_STIFFNESS = .24  # 只抑制相邻节点尖折，不恢复参考弧度
    REST_VELOCITY_RETENTION = .82
    MOVING_VELOCITY_RETENTION = .90
    FREE_TRACK_STIFFNESS = .020
    FREE_TRACK_FORCE = .85
    FREE_LENGTH_RETURN = .003  # 每步收回自然长度的此比例，避免松开瞬间缩跳
    EXTEND_ROOT_RETENTION = .20  # 探查/回抓时根部偏好让位，保留少量出发方向
    EXTEND_TRACK_RAMP = .15
    EXTEND_TRACK_BASE = .35
    REGRIP_STRENGTH = 1.6
    REGRIP_RESPONSE = .14
    REGRIP_CONTACT_DISTANCE = 2.
    REGRIP_CONTACT_SPAN = 12.  # 允许沿墙在目标附近实际碰到的位置落脚
    REGRIP_PRESS = 6.  # 施力目标略过抓附轨道，提供接触压力，节点仍受工作区约束
    REGRIP_SLACK = .025  # 回抓留少量弧长余量，触墙后逐步收回，避免瞬间拉直
    SOLVER_ITERATIONS = 12
    SEGMENT_TOLERANCE = .02  # 有限轮约束求解允许的局部相对误差，总长仍有硬限制
    SETTLE_SPEED = .025
    SETTLE_TICKS = 24

    def __init__(self, definition, root, outward, grip_s, rail, *, backend='python', search_seed=None):
        self.definition = definition
        path = make_path(definition)
        self.reference_length = definition.length if definition.length is not None else path.length
        self.length_limit = None
        self.attached = True
        count = max(12, min(48, ceil(self.reference_length/5)))
        # 未显式配置方向时才使用参考图的根部方向，不逐点对应物理链
        self.launch = normalized(path.sample(min(.08, 8./path.length))[0]-path.points[0])
        self.grip_s = grip_s
        self.grip = rail.sample(grip_s)[0]
        self.target_s = grip_s
        self.transfer_start = self.grip
        self.transfer_tick = self.transfer_duration = 0
        self.reaching = False
        self.reach_weight = 0.
        self.reach_from = self.grip
        self.contact_length = 0.
        self.cooldown = 0
        self.nodes = [Node(p, p) for p in self.initial_points(root, outward, self.grip, count)]
        self._solver = tentacle_solver(backend)
        self._solve_x = array('d', (p.position.x for p in self.nodes))
        self._solve_y = array('d', (p.position.y for p in self.nodes))
        self._line_x = array('d', [0.])*len(self.nodes)
        self._line_y = array('d', [0.])*len(self.nodes)
        self.sleeping = False
        self.quiet_ticks = 0
        self.last_inputs = None
        self.motion = 0.
        self.free_length = self.reference_length
        self.free_direction = None
        self.passive = False
        self.free_search = FreeTipSearch(search_seed)
        self.wall_probe = WallProbe(search_seed)
        # 中心线包围盒的统一余量，囊肿即使偏心或旋转也不会被清除范围裁掉
        self.padding = max([w/2+2 for _, w in definition.widths] + [
            abs(b.offset)+max(b.width, b.height)/2+2
            for b in (*definition.bumps, *definition.cores) if b.enabled])

    @property
    def transferring(self):
        return self.reaching or self.transfer_tick < self.transfer_duration

    @property
    def free(self):
        # 受力回抓仍使用自由末端，只占用换点名额，不钉住末端
        return not self.attached and (self.reaching or not self.transferring)

    def shape_length_limit(self, root, tip):
        if self.free:
            return self.free_length if self.length_limit is None else min(self.free_length, self.length_limit)
        # 展开自然弧长后才允许伸长，拖拽期间仍遵守硬上限
        length = max(self.reference_length, (tip-root).length(), self.contact_length)
        return length if self.length_limit is None else min(length, self.length_limit)

    def preferred_direction(self, outward, root, tip):
        if self.definition.root_directions is not None:
            return edge_direction(self.definition.root_directions, outward)
        # 右边参考图的 x 表示朝向抓附边，y 始终表示屏幕上下
        # 左右停靠仅镜像水平伸展；上下停靠混合朝边方向和原有下垂倾向
        # 少量朝抓点的分量避免在顶部两项抵消时发生方向突变
        reach = normalized(tip-root, outward)
        return normalized(outward*self.launch.x+Vec2(0, self.launch.y)+reach*.25, reach)

    def initial_points(self, root, outward, tip, count):
        slack = max(0., self.reference_length-(tip-root).length())
        launch = self.preferred_direction(outward, root, tip)
        result = []
        for i in range(count+1):
            t = i/count
            # 仅用于创建时打破完全共线，之后不再以这些点为目标
            result.append(root.lerp(tip, t)+Vec2(0, slack*.4*sin(pi*t))
                          +launch*(slack*.25*sin(pi*t)*(1.-t)**4))
        result[0], result[-1] = root, tip
        return fit_length(result, self.shape_length_limit(root, tip))

    def solve_chain(self, root, tip, rail):
        """相邻段使用固定限长；松弛时不将压缩段硬撑成锯齿"""
        x, y = self._solve_x, self._solve_y
        for i, node in enumerate(self.nodes):
            x[i], y[i] = node.position.x, node.position.y
        x[0], y[0] = root.x, root.y
        if not self.free:
            x[-1], y[-1] = tip.x, tip.y
        budget = self.shape_length_limit(root, tip)
        pad = min(self.padding, rail.inset)
        args = (x, y, self._line_x, self._line_y, float(budget), float(pad),
                float(rail.width), float(rail.height), self.SOLVER_ITERATIONS)
        error = self._solver(*args, True) if self.free else self._solver(*args)
        for i, node in enumerate(self.nodes):
            node.position = Vec2(x[i], y[i])
        self.nodes[0].position = root
        if not self.free:
            self.nodes[-1].position = tip
        return error

    def release(self, target_s, rail):
        physical = self.free
        self.attached = False
        self.target_s = rail.bounded(target_s)
        if physical:
            if not self.reaching:
                self.reach_weight = 0.
                self.reach_from = self.last_inputs[2] if self.last_inputs else self.nodes[-1].position
            self.reaching = True
            self.transfer_tick = self.transfer_duration = 0
            self.sleeping = False
            self.quiet_ticks = 0
            return
        self.transfer_start = self.nodes[-1].position
        distance = (rail.sample(self.target_s)[0]-self.transfer_start).length()
        self.transfer_duration = max(18, min(48, ceil(distance/2.5)))
        self.transfer_tick = 0
        self.sleeping = False
        self.quiet_ticks = 0

    def detach(self, *, passive=None):
        """不可达时保持松开，不把已经够不到的屏幕点继续当作固定端"""
        if passive is not None:
            self.passive = passive
        self.free_search.begin()
        self.wall_probe.begin()
        self.free_length = max(self.reference_length, path_length([p.position for p in self.nodes]))
        if self.length_limit is not None:
            self.free_length = min(self.free_length, self.length_limit)
        self.free_direction = None
        self.attached = False
        self.reaching = False
        self.reach_weight = 0.
        self.contact_length = 0.
        self.transfer_tick = self.transfer_duration = 0
        self.sleeping = False
        self.quiet_ticks = 0

    def free_target(self, root, outward, rail):
        """围绕边缘方向探寻，只提供施力目标，不指定末端或中段坐标"""
        target = rail.sample(rail.project(root, self.grip_s))[0]
        direction = normalized(target-root, outward)
        self.free_direction = (direction if self.free_direction is None else
                               normalized(self.free_direction.lerp(direction, .04), direction))
        search = self.wall_probe.step(self.free_search.step())
        direction = self.free_direction*cos(search.angle)+perpendicular(self.free_direction)*sin(search.angle)
        reach = self.reference_length*search.reach
        return root+direction*min((target-root).length(), reach)

    def step(self, root, outward, rail):
        was_moving = self.transferring
        self.contact_length = max(0., self.contact_length-self.reference_length*self.FREE_LENGTH_RETURN)
        self.cooldown = max(0, self.cooldown-1)
        tip = self.grip
        if was_moving and not self.reaching:
            self.transfer_tick += 1
            t = self.transfer_tick/self.transfer_duration
            eased = t*t*(3.-2.*t)
            target = rail.sample(self.target_s)[0]
            # 松开、向工作区内收起、伸向新抓点；拐角不沿屏幕外侧抄近路
            inward = normalized(rail.normal(self.grip_s).lerp(rail.normal(self.target_s), t))
            lift = min(12., 4.+(target-self.transfer_start).length()*.12)
            tip = self.transfer_start.lerp(target, eased)+inward*(sin(pi*t)*lift)
            if self.length_limit is not None and (target-root).length() > self.length_limit*.98:
                self.detach()
            elif not self.transferring:
                self.grip_s, self.grip = self.target_s, target
                self.attached = True
                self.cooldown = 12
                tip = target
        if self.reaching:
            target = rail.sample(self.target_s)[0]
            if self.length_limit is not None and (target-root).length() > self.length_limit*.98:
                self.detach()
        free_tip = self.free
        extension = strength = 0.
        if free_tip:
            if self.reaching:
                self.reach_weight += (1.-self.reach_weight)*self.REGRIP_RESPONSE
                goal = self.reach_from.lerp(target-rail.normal(self.target_s)*self.REGRIP_PRESS,
                                            self.reach_weight)
                extension = self.wall_probe.weight+(1.-self.wall_probe.weight)*self.reach_weight
                strength = self.wall_probe.value.strength+(
                    self.REGRIP_STRENGTH-self.wall_probe.value.strength)*self.reach_weight
                length = max(self.reference_length,
                             (target-root).length()+self.reference_length*self.REGRIP_SLACK)
                if self.length_limit is not None:
                    length = min(length, self.length_limit)
            else:
                if self.passive:
                    # 自主移动时只保留惯性、重力及根部出发方向，不运行朝墙探寻时钟
                    goal = root
                else:
                    goal = self.free_target(root, outward, rail)
                    extension, strength = self.wall_probe.weight, self.wall_probe.value.strength
                length = self.reference_length
            # 回抓的拉伸余量逐步展开，不能在进入可达范围的一帧突然增长
            rate = self.reference_length*self.FREE_LENGTH_RETURN
            self.free_length += max(-rate, min(rate, length-self.free_length))
            tip = self.nodes[-1].position
        elif not self.attached and self.length_limit is not None:
            tip = root+limited(tip-root, self.length_limit*.98)
        inputs = (root, outward, goal if free_tip else tip)
        if self.sleeping and self.last_inputs is not None and all(
                (a-b).length() < .0001 for a, b in zip(inputs, self.last_inputs)):
            return False
        movement = 0.
        if self.last_inputs is not None:
            old_root, old_outward, old_tip = self.last_inputs
            movement = max((root-old_root).length(), (inputs[2]-old_tip).length(),
                           (outward-old_outward).length()*self.reference_length*.25)
        activity = 1. if was_moving or free_tip else min(1., movement/.8)
        self.motion += (activity-self.motion)*(.25 if activity > self.motion else .08)
        self.last_inputs = inputs
        self.sleeping = False
        last = len(self.nodes)-1
        direction = self.preferred_direction(outward, root, tip)
        positions = [node.position for node in self.nodes]
        retention = self.REST_VELOCITY_RETENTION+(
            self.MOVING_VELOCITY_RETENTION-self.REST_VELOCITY_RETENTION)*self.motion
        root_strength = 1.-extension*(1.-self.EXTEND_ROOT_RETENTION)
        for i, node in enumerate(self.nodes):
            node.previous_position = node.position
            if i == 0 or i == last and not free_tip:
                node.position = root if i == 0 else tip
            else:
                weight = max(0., 1.-i/last/self.ROOT_DIRECTION_SPAN)**2
                bend = (positions[i-1].lerp(positions[i+1], .5)-node.position if i < last else Vec2())
                force = Vec2(0, self.GRAVITY)+direction*(self.ROOT_DIRECTION_FORCE*weight*root_strength)
                force += limited(bend, 2.)*self.BEND_STIFFNESS
                if free_tip:
                    # 远端逐渐增强追踪力，末端同样保留惯性、重力和约束修正
                    tracking = max(0., (i/last-.45)/.55)**2
                    # 探查与回抓时让前中段一起伸展，避免余量全部耗在下垂折返上
                    spread = min(1., i/last/self.EXTEND_TRACK_RAMP)*(
                        self.EXTEND_TRACK_BASE+(1.-self.EXTEND_TRACK_BASE)*i/last)
                    tracking += (spread-tracking)*extension
                    force += limited((goal-node.position)*self.FREE_TRACK_STIFFNESS,
                                     self.FREE_TRACK_FORCE)*(tracking*strength)
                node.position += limited(node.velocity*retention+force, 6.)
        error = self.solve_chain(root, tip, rail)
        if self.reaching:
            contact_s = rail.bounded(rail.project(self.nodes[-1].position, self.target_s))
            contact = rail.sample(contact_s)[0]
            if ((self.nodes[-1].position-contact).length() <= self.REGRIP_CONTACT_DISTANCE
                    and abs(rail.delta(self.target_s, contact_s)) <= self.REGRIP_CONTACT_SPAN
                    and (self.length_limit is None or (contact-root).length() <= self.length_limit)):
                # 在附近实际触墙的位置落脚，避免重力造成沿墙偏移后悬在目标旁
                self.grip_s, self.grip = contact_s, contact
                self.target_s = contact_s
                self.contact_length = self.free_length
                self.attached, self.reaching = True, False
                self.cooldown = 12
                tip = contact
                error = self.solve_chain(root, tip, rail)
        speed = 0.
        for node in self.nodes:
            node.velocity = node.position-node.previous_position
            speed = max(speed, node.velocity.length())
        tolerance = self.shape_length_limit(root, tip)/last*self.SEGMENT_TOLERANCE
        quiet = (speed < self.SETTLE_SPEED and error < tolerance and movement < .0001
                 and not was_moving and (not free_tip or self.passive))
        self.quiet_ticks = self.quiet_ticks+1 if quiet else 0
        if self.quiet_ticks >= self.SETTLE_TICKS:
            # 在当前受力姿态休眠，不吸回参考图或另一条目标曲线
            for node in self.nodes:
                node.previous_position = node.position
                node.velocity = Vec2()
            self.sleeping = True
            self.motion = 0.
        return True

    def path(self, alpha):
        # 线性细分物理链，不再过度样条平滑，避免越过保守绘制边界
        points, distances = [self.nodes[0].sample(alpha)], [0.]
        for node in self.nodes[1:]:
            p = node.sample(alpha)
            length = (p-points[-1]).length()
            if length > 1e-8:
                points.append(p)
                distances.append(distances[-1]+length)
        if len(points) == 1:
            points.append(points[0]+Vec2(.001, 0))
            distances.append(.001)
        return TubePath(tuple(points), tuple(distances))


class PrinceTentacles:
    # 换点阈值、提前量、两次换点之间的停顿，均为常规支撑参数
    REPLANT_DISTANCE = 26.
    LEAD_DISTANCE = 16.
    REST_TICKS = 5
    BACK_OUTSET = 0.  # 正面直立时保持在背部中轴，不随停靠边向外偏移
    BACK_DOWN = 4.
    MAX_DRAG_STRETCH = 1.20
    DRAG_ROOT_MARGIN = 12.  # 为下一帧胸部弯曲、惯性与根部转动留余量
    DRAG_TARGET_ROOT_FOLLOW = .10  # 目标边界缓随胸部，避免柔性身体与限位互相激振
    AUTO_REACH = .90  # 常规移动至少保留 10% 自然长度，不使用拖拽拉伸余量
    AUTO_REGRIP = .82  # 回抓比松开更早留余量，避免在临界距离反复抓放
    AUTO_ROOT_MARGIN = 12.

    @classmethod
    def navigation_reach(cls, study):
        definitions = tuple(d for d in study.tentacles if d.enabled) or study.tentacles
        lengths = [d.length if d.length is not None else make_path(d).length
                   for d in definitions]
        return max(1., max(lengths, default=1.)*cls.AUTO_REACH-cls.AUTO_ROOT_MARGIN)

    def __init__(self, scene, study=None):
        self.rail = GripRail(scene.world)
        self.study = study or getattr(scene, 'prince_study', None) or default_study()
        self.location = self.rail.project(scene.appearance.upper, self.rail.project(scene.base))
        self.outward = self.rail.normal(self.location)*-1.
        self.root = self.attachment(scene)
        self.body_position = (scene.body.chunks[0].position if hasattr(scene, 'body') else scene.appearance.upper)
        self.parts = []
        backend = getattr(getattr(scene, 'config', None), 'physics_backend', 'python')
        for definition in self.study.tentacles:
            if not definition.enabled:
                continue
            root = self.part_root(definition)
            s = self.ideal_grip(definition, root)
            self.parts.append(SupportTentacle(definition, root, self.outward, s, self.rail, backend=backend))
        # 初始离边距离较大时也要先选择舒适抓点，不能第一帧就把所有短链拉直
        primary = max(self.parts, key=lambda p: p.reference_length, default=None)
        for part in self.parts:
            root = self.part_root(part.definition)
            reach = (part.reference_length*self.AUTO_REACH-self.AUTO_ROOT_MARGIN if part is primary
                     else part.reference_length*self.AUTO_REGRIP)
            target = self.reachable_target(part, part.grip_s, reach=max(1., reach))
            part.passive = True
            part.length_limit = part.reference_length
            if target is None:
                if part is not primary:
                    part.detach(passive=True)
                    part.solve_chain(root, part.grip, self.rail)
            elif abs(self.rail.delta(part.grip_s, target)) > .0001:
                part.grip_s = part.target_s = target
                part.grip = self.rail.sample(target)[0]
                points = part.initial_points(root, self.outward, part.grip, len(part.nodes)-1)
                for node, point in zip(part.nodes, points):
                    node.position = node.previous_position = point
            for node in part.nodes:
                node.previous_position = node.position
        self.revision = 0
        self.cooldown = 0
        self.travel = 0.
        self.guard = None
        self.drag_limited = False
        self.drag_root_offset = self.root-self.body_position

    def attachment(self, scene):
        frame = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction)
        return frame.chest+self.outward*self.BACK_OUTSET-frame.chest_direction*self.BACK_DOWN

    def part_root(self, definition):
        p = definition.points[0]
        return self.root+self.outward*p.x+perpendicular(self.outward)*p.y

    def ideal_grip(self, definition, root, length=None):
        if definition.grip_directions is None:
            return self.rail.bounded(self.location+definition.points[-1].y)
        if length is None:
            length = definition.length if definition.length is not None else make_path(definition).length
        reach = definition.grip_reach
        if isinstance(reach, tuple):
            # 先分别计算每条边的偏好位移，再跨角混合，方向和距离共用同一缓动
            directions = tuple(d*r for d, r in zip(definition.grip_directions, reach))
            offset = edge_direction(directions, self.outward)*length
        else:
            offset = edge_direction(definition.grip_directions, self.outward)*(length*reach)
        preferred = root+offset
        return self.rail.bounded(self.rail.project(preferred, self.location))

    @property
    def settled(self):
        return all(p.sleeping and (p.attached or p.passive) and not p.transferring for p in self.parts)

    @property
    def visual_key(self):
        return self, self.revision

    def begin_drag(self):
        self.drag_limited = True
        self.drag_root_offset = self.root-self.body_position
        for part in self.parts:
            if part.passive and part.free:
                part.detach(passive=False)
            part.passive = False
            part.length_limit = part.reference_length*self.MAX_DRAG_STRETCH
            part.sleeping = False
            part.quiet_ticks = 0

    def project_drag(self, scene, point, *, choose=False, for_target=False):
        """只由仍抓住的触手限制人偶，不受较短、已经松开的触手牵制"""
        if not self.parts:
            return point
        if not self.drag_limited:
            self.begin_drag()
        attached = [p for p in self.parts if p.attached]
        if choose or self.guard not in attached:
            if not attached:
                return point
            shift = point-self.body_position
            self.guard = max(attached, key=lambda p: p.length_limit-(
                self.part_root(p.definition)+shift-p.grip).length())
        # 根部与身体必须来自同一次物理步，不能用上一帧根部减去本帧已积分的身体
        # 同一帧多次投影共用此偏移，避免限位本身跟着校正来回移动
        offset = self.part_root(self.guard.definition)-self.body_position
        if for_target:
            # 鼠标目标不逐帧追逐胸部回摆；身体的即时限长仍使用上面的真实根部
            offset = self.part_root(self.guard.definition)-self.root+self.drag_root_offset
        center = self.guard.grip-offset
        return center+limited(point-center, max(1., self.guard.length_limit-self.DRAG_ROOT_MARGIN))

    def reachable_target(self, part, ideal, *, root=None, reach=None):
        if reach is None and part.length_limit is None:
            return self.rail.bounded(ideal)
        root = self.part_root(part.definition) if root is None else root
        nearest = self.rail.project(root, part.grip_s)
        reach = part.length_limit*.92 if reach is None else reach
        if (self.rail.sample(nearest)[0]-root).length() > reach:
            return None
        distance = self.rail.delta(nearest, self.rail.bounded(ideal))
        if (self.rail.sample(nearest+distance)[0]-root).length() <= reach:
            return self.rail.bounded(nearest+distance)
        lo, hi = 0., 1.
        for _ in range(16):
            t = (lo+hi)*.5
            if (self.rail.sample(nearest+distance*t)[0]-root).length() <= reach:
                lo = t
            else:
                hi = t
        return self.rail.bounded(nearest+distance*lo)

    def project_motion(self, scene, point):
        """最长触手换点时身体等待，其他时间保持它的自然松弛余量"""
        if not self.parts:
            return point
        guard = max(self.parts, key=lambda p: p.reference_length)
        if not guard.attached:
            return self.body_position
        offset = self.part_root(guard.definition)-self.body_position
        center = guard.grip-offset
        return center+limited(point-center, max(1., guard.reference_length*self.AUTO_REACH-self.AUTO_ROOT_MARGIN))

    def project_destination(self, scene, point):
        """只有长触手够得着的深处，终点必须仍在当前支撑点的松弛范围内"""
        if not self.parts:
            return point
        longest = max(self.parts, key=lambda p: p.reference_length)
        shift = point-scene.body.chunks[0].position
        alternatives = [p for p in self.parts if p is not longest]
        can_support = any(self.reachable_target(p, p.grip_s,
            root=self.part_root(p.definition)+shift, reach=p.reference_length*self.AUTO_REGRIP) is not None
            for p in alternatives)
        if longest.attached and not can_support:
            return self.project_motion(scene, point)
        return point

    def step(self, scene):
        drag = getattr(scene, 'drag', None)
        controlling = drag is not None and drag.controlling
        if controlling and not self.drag_limited:
            self.begin_drag()
        elif not controlling and self.drag_limited:
            self.drag_limited = False
            self.guard = None
            for part in self.parts:
                part.length_limit = part.reference_length
        for part in self.parts:
            if not controlling:
                if not part.passive and part.free:
                    part.wall_probe.begin()
                part.passive = True
                part.length_limit = part.reference_length
        previous_s = self.location
        # 由身体的边缘投影决定换点，不能跟随隐藏底座；固定底座模式也能行走
        self.location = self.rail.project(scene.appearance.upper, previous_s)
        self.travel = self.travel*.8+(self.location-previous_s)*.2
        target_outward = self.rail.normal(self.location)*-1.
        dot = self.outward.x*target_outward.x+self.outward.y*target_outward.y
        if dot < -.95:
            # 正好反向时单位向量线性插值无法转过去，先转开再沿用普通跨角的缓动
            turn = atan2(self.outward.x*target_outward.y-self.outward.y*target_outward.x, dot)*.16
            self.outward = Vec2(self.outward.x*cos(turn)-self.outward.y*sin(turn),
                                self.outward.x*sin(turn)+self.outward.y*cos(turn))
        else:
            self.outward = normalized(self.outward.lerp(target_outward, .16), target_outward)
        if (self.outward-target_outward).length() < .0001:
            self.outward = target_outward
        self.root = self.attachment(scene)
        self.body_position = (scene.body.chunks[0].position if hasattr(scene, 'body') else scene.appearance.upper)
        offset = self.root-self.body_position
        self.drag_root_offset = (self.drag_root_offset.lerp(offset, self.DRAG_TARGET_ROOT_FOLLOW)
                                 if controlling else offset)
        self.cooldown = max(0, self.cooldown-1)
        active_before = [p for p in self.parts if p.transferring]
        budget = min(len(self.parts)-1, 2)
        lead = max(-self.LEAD_DISTANCE, min(self.LEAD_DISTANCE, self.travel*18.))
        # 松手后仍按一次一条重新抓回，不在同一帧把两条悬空触手直接贴回边缘
        transfers = 2 if drag is not None and drag.active else 1
        primary = max(self.parts, key=lambda p: p.reference_length, default=None)
        for part in self.parts:
            if part.attached or part.transferring or sum(p.transferring for p in self.parts) >= transfers:
                continue
            ideal = self.ideal_grip(part.definition, self.part_root(part.definition), part.reference_length)+lead
            target = self.reachable_target(part, ideal, reach=(
                None if controlling else part.reference_length*self.AUTO_REGRIP))
            if target is not None:
                part.release(target, self.rail)
        while sum(not p.attached for p in self.parts) < budget:
            candidates = []
            for i, part in enumerate(self.parts):
                if not part.attached or controlling and part is self.guard:
                    continue
                ideal = self.ideal_grip(part.definition, self.part_root(part.definition), part.reference_length)
                offset = self.rail.delta(part.grip_s, ideal)
                distance = (part.grip-self.part_root(part.definition)).length()
                if not controlling and any(p.transferring for p in self.parts):
                    if part is not primary and distance > part.reference_length*self.AUTO_REACH:
                        candidates.append((True, distance, -i, part, None))
                    continue
                strained = (distance > part.length_limit*.94 if controlling else
                            distance > part.reference_length*self.AUTO_REGRIP)
                if strained or (abs(offset) > self.REPLANT_DISTANCE and part.cooldown == 0
                                and self.cooldown == 0):
                    target = self.reachable_target(part, ideal+lead, reach=(
                        None if controlling else part.reference_length*self.AUTO_REGRIP))
                    if not controlling and part is primary:
                        # 长触手不可悬空等待；换点前必须已有另一条保持舒适支撑
                        alternate = any(p is not part and p.attached and
                            (p.grip-self.part_root(p.definition)).length() < p.reference_length*self.AUTO_REACH
                            for p in self.parts)
                        if target is None or not alternate:
                            continue
                    if (not controlling and target is not None and strained
                            and distance <= part.reference_length*self.AUTO_REACH
                            and (self.rail.sample(target)[0]-self.part_root(part.definition)).length() >= distance-2.):
                        # 已处于回抓后的舒适位置，不因浮点误差反复松开同一个点
                        continue
                    # 偏好可能超出长度限制；已抓住裁剪后的落点时，不反复松开原地抓取
                    if (not strained and target is not None
                            and abs(self.rail.delta(part.grip_s, target)) <= self.REPLANT_DISTANCE):
                        continue
                    candidates.append((strained, abs(offset), -i, part, target))
            if not candidates:
                break
            strained, _, _, part, target = max(candidates, key=lambda v: v[:3])
            if target is None:
                part.detach()
            elif sum(p.transferring for p in self.parts) < transfers:
                part.release(target, self.rail)
            elif strained:
                # 恢复期间仍可先松开过紧的一条，再等待另一条完成回抓
                part.detach()
            else:
                break
        changed = False
        for part in self.parts:
            changed |= part.step(self.part_root(part.definition), self.outward, self.rail)
        if any(not p.transferring for p in active_before):
            self.cooldown = self.REST_TICKS
        if changed:
            self.revision += 1

    def paths(self, alpha=1.):
        return tuple((p.definition, p.path(alpha)) for p in self.parts)
