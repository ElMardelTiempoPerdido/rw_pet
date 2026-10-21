"""Prince 的边缘支撑与逐条换抓点，固定 40 Hz，不包含声源试探状态"""
from dataclasses import dataclass
from math import ceil, pi, sin

from ...shared.geometry import Vec2
from ..config import EDGE_NAMES
from ..prince_tentacles import TubePath, default_study, make_path
from .navigation import RailPiece, RoundedRail, normalized


def limited(value, maximum):
    return value*min(1., maximum/max(value.length(), 1e-9))


def perpendicular(value):
    return Vec2(-value.y, value.x)


def path_length(points):
    return sum((b-a).length() for a, b in zip(points, points[1:]))


def fit_length(points, maximum):
    """固定两端，收拢多余弧度；同时约束目标曲线和惯性产生的实际弧长"""
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
    EDGE_INSET = 16.  # 逻辑像素，为末端管宽、偏心囊肿及像素化留出显示空间

    def __init__(self, world):
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
    """模板提供静态弧度，阻尼节点提供惯性；抓点固定期间末端不跟随身体平移"""
    STRAIGHTEN_START = .75 # 两端距离达到自然弧长的此比例时，开始逐渐展开参考轮廓
    REST_SHAPE_STIFFNESS = .2
    MOVING_SHAPE_STIFFNESS = .2
    REST_VELOCITY_RETENTION = .45
    MOVING_VELOCITY_RETENTION = .45

    def __init__(self, definition, root, outward, grip_s, rail):
        self.definition = definition
        path = make_path(definition)
        self.reference_length = path.length
        self.length_limit = None
        self.attached = True
        count = max(12, min(48, ceil(path.length/5)))
        self.reference = tuple(path.sample(i/count)[0] for i in range(count+1))
        self.grip_s = grip_s
        self.grip = rail.sample(grip_s)[0]
        self.target_s = grip_s
        self.transfer_start = self.grip
        self.transfer_tick = self.transfer_duration = 0
        self.cooldown = 0
        self.nodes = [Node(p, p) for p in self.goals(root, outward, self.grip)]
        self.sleeping = False
        self.quiet_ticks = 0
        self.last_inputs = None
        self.motion = 0.
        # 中心线包围盒的统一余量，囊肿即使偏心或旋转也不会被清除范围裁掉
        self.padding = max([w/2+2 for _, w in definition.widths] + [
            abs(b.offset)+max(b.width, b.height)/2+2
            for b in (*definition.bumps, *definition.cores) if b.enabled])

    @property
    def transferring(self):
        return self.transfer_tick < self.transfer_duration

    def bow_weight(self, root, tip):
        ratio = (tip-root).length()/max(self.reference_length, 1e-9)
        tension = max(0., min(1., (ratio-self.STRAIGHTEN_START)/(1.-self.STRAIGHTEN_START)))
        return 1.-tension*tension*(3.-2.*tension)

    def shape_length_limit(self, root, tip):
        # 先展开自然弧长，再允许绷直后的伸长；惯性也不能重新撑出多余弧长
        length = max(self.reference_length, (tip-root).length())
        return length if self.length_limit is None else min(length, self.length_limit)

    def goals(self, root, outward, tip):
        tangent = perpendicular(outward)
        start = self.reference[0]
        end = self.reference[-1]-start
        count = len(self.reference)-1
        # 拉到自然长度时参考弧度完全归零，不再留下固定比例的根部回弯
        bow_weight = self.bow_weight(root, tip)
        result = []
        for i, p in enumerate(self.reference):
            t = i/count
            bow = p-start-end*t
            result.append(root.lerp(tip, t)+(outward*bow.x+tangent*bow.y)*bow_weight)
        result[0], result[-1] = root, tip
        return fit_length(result, self.shape_length_limit(root, tip))

    def release(self, target_s, rail):
        self.attached = False
        self.target_s = rail.bounded(target_s)
        self.transfer_start = self.nodes[-1].position
        distance = (rail.sample(self.target_s)[0]-self.transfer_start).length()
        self.transfer_duration = max(18, min(48, ceil(distance/2.5)))
        self.transfer_tick = 0
        self.sleeping = False
        self.quiet_ticks = 0

    def detach(self):
        """不可达时保持松开，不把已经够不到的屏幕点继续当作固定端"""
        self.attached = False
        self.transfer_tick = self.transfer_duration = 0
        self.sleeping = False
        self.quiet_ticks = 0

    def step(self, root, outward, rail):
        was_moving = self.transferring
        self.cooldown = max(0, self.cooldown-1)
        tip = self.grip
        if was_moving:
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
                tip = root+limited(tip-root, self.length_limit*.98)
            elif not self.transferring:
                self.grip_s, self.grip = self.target_s, target
                self.attached = True
                self.cooldown = 12
                tip = target
        elif not self.attached:
            target = rail.sample(rail.project(root, self.grip_s))[0]
            reach = self.length_limit or self.reference_length
            goal = root+limited(target-root, reach*.86)
            node = self.nodes[-1]
            tip = node.position+limited(node.velocity*.65+(goal-node.position)*.15, 4.)
        if not self.attached and self.length_limit is not None:
            tip = root+limited(tip-root, self.length_limit*.98)
        inputs = (root, outward, tip)
        if self.sleeping and self.last_inputs is not None and all(
                (a-b).length() < .0001 for a, b in zip(inputs, self.last_inputs)):
            return False
        movement = 0.
        if self.last_inputs is not None:
            old_root, old_outward, old_tip = self.last_inputs
            movement = max((root-old_root).length(), (tip-old_tip).length(),
                           (outward-old_outward).length()*self.reference_length*.25)
        activity = 1. if was_moving else min(1., movement/.8)
        self.motion += (activity-self.motion)*(.25 if activity > self.motion else .08)
        self.last_inputs = inputs
        self.sleeping = False
        goals = self.goals(root, outward, tip)
        last = len(self.nodes)-1
        # 长触手的中段稍软，固定两端与绷紧状态仍稳定；停止移动后逐渐恢复静态约束
        softness = self.motion*min(1., self.reference_length/180.)*self.bow_weight(root, tip)
        for i, (node, goal) in enumerate(zip(self.nodes, goals)):
            node.previous_position = node.position
            if i in (0, last):
                node.position = goal
            else:
                envelope = sin(pi*i/last)
                blend = softness*envelope
                stiffness = self.REST_SHAPE_STIFFNESS+(
                    self.MOVING_SHAPE_STIFFNESS-self.REST_SHAPE_STIFFNESS)*blend
                retention = self.REST_VELOCITY_RETENTION+(
                    self.MOVING_VELOCITY_RETENTION-self.REST_VELOCITY_RETENTION)*blend
                force = (goal-node.position)*stiffness
                node.position += limited(node.velocity*retention+force, 6.)
                # 极端拖拽时限制残留摆幅，避免整条链脱离支撑方向
                node.position = goal+limited(node.position-goal, (12.+4.*softness)*envelope)
        # 局部限长随展开后的目标更新，总弧长另行约束，避免惯性留下绷紧后的弯折
        rest = [(b-a).length()*1.08 for a, b in zip(goals, goals[1:])]
        for iteration in range(6):
            indices = range(last) if iteration % 2 == 0 else range(last-1, -1, -1)
            for i in indices:
                a, b = self.nodes[i:i+2]
                delta = b.position-a.position
                distance = delta.length()
                if distance <= rest[i]:
                    continue
                correction = delta*((distance-rest[i])/max(distance, 1e-9))
                if i == 0:
                    b.position -= correction
                elif i+1 == last:
                    a.position += correction
                else:
                    a.position += correction*.5
                    b.position -= correction*.5
        fitted = fit_length([p.position for p in self.nodes], self.shape_length_limit(root, tip))
        for node, position in zip(self.nodes, fitted):
            node.position = position
        speed = 0.
        error = 0.
        for node, goal in zip(self.nodes, goals):
            node.velocity = node.position-node.previous_position
            speed = max(speed, node.velocity.length())
            error = max(error, (node.position-goal).length())
        self.quiet_ticks = self.quiet_ticks+1 if speed < .004 and error < .015 and not was_moving else 0
        if self.quiet_ticks >= 12:
            for node, goal in zip(self.nodes, goals):
                node.position = node.previous_position = goal
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
    BACK_OUTSET = 5.
    BACK_DOWN = 4.
    MAX_DRAG_STRETCH = 1.20
    DRAG_ROOT_MARGIN = 12.  # 为下一帧胸部弯曲、惯性与根部转动留余量

    def __init__(self, scene, study=None):
        self.rail = GripRail(scene.world)
        self.study = study or default_study()
        self.location = self.rail.project(scene.appearance.upper, self.rail.project(scene.base))
        self.outward = self.rail.normal(self.location)*-1.
        self.root = self.attachment(scene)
        self.parts = []
        for definition in self.study.tentacles:
            if not definition.enabled:
                continue
            s = self.rail.bounded(self.location+definition.points[-1].y)
            root = self.part_root(definition)
            self.parts.append(SupportTentacle(definition, root, self.outward, s, self.rail))
        self.revision = 0
        self.cooldown = 0
        self.travel = 0.
        self.guard = None
        self.drag_limited = False

    def attachment(self, scene):
        frame = scene.prince_posture.frame(scene.appearance.upper, scene.appearance.direction)
        return frame.chest+self.outward*self.BACK_OUTSET-frame.chest_direction*self.BACK_DOWN

    def part_root(self, definition):
        p = definition.points[0]
        return self.root+self.outward*p.x+perpendicular(self.outward)*p.y

    @property
    def settled(self):
        return all(p.sleeping and p.attached and not p.transferring for p in self.parts)

    @property
    def visual_key(self):
        return self, self.revision

    def begin_drag(self):
        self.drag_limited = True
        for part in self.parts:
            part.length_limit = part.reference_length*self.MAX_DRAG_STRETCH
            part.sleeping = False
            part.quiet_ticks = 0

    def project_drag(self, scene, point, *, choose=False):
        """只由仍抓住的触手限制人偶，不受较短、已经松开的触手牵制"""
        if not self.parts:
            return point
        if not self.drag_limited:
            self.begin_drag()
        attached = [p for p in self.parts if p.attached]
        if choose or self.guard not in attached:
            if not attached:
                return point
            shift = point-scene.body.chunks[0].position
            self.guard = max(attached, key=lambda p: p.length_limit-(
                self.part_root(p.definition)+shift-p.grip).length())
        offset = self.part_root(self.guard.definition)-scene.body.chunks[0].position
        center = self.guard.grip-offset
        return center+limited(point-center, max(1., self.guard.length_limit-self.DRAG_ROOT_MARGIN))

    def reachable_target(self, part, ideal):
        if part.length_limit is None:
            return self.rail.bounded(ideal)
        root = self.part_root(part.definition)
        nearest = self.rail.project(root, part.grip_s)
        reach = part.length_limit*.92
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

    def step(self, scene):
        drag = getattr(scene, 'drag', None)
        controlling = drag is not None and drag.controlling
        if controlling and not self.drag_limited:
            self.begin_drag()
        elif not controlling and self.drag_limited:
            self.drag_limited = False
            self.guard = None
            for part in self.parts:
                part.length_limit = None
        previous_s = self.location
        # 由身体的边缘投影决定换点，不能跟随隐藏底座；固定底座模式也能行走
        self.location = self.rail.project(scene.appearance.upper, previous_s)
        self.travel = self.travel*.8+(self.location-previous_s)*.2
        target_outward = self.rail.normal(self.location)*-1.
        self.outward = normalized(self.outward.lerp(target_outward, .16), target_outward)
        if (self.outward-target_outward).length() < .0001:
            self.outward = target_outward
        self.root = self.attachment(scene)
        self.cooldown = max(0, self.cooldown-1)
        active_before = [p for p in self.parts if p.transferring]
        budget = min(len(self.parts)-1, 2 if controlling else 1)
        lead = max(-self.LEAD_DISTANCE, min(self.LEAD_DISTANCE, self.travel*18.))
        # 松手后仍按一次一条重新抓回，不在同一帧把两条悬空触手直接贴回边缘
        transfers = 2 if drag is not None and drag.active else 1
        for part in self.parts:
            if part.attached or part.transferring or sum(p.transferring for p in self.parts) >= transfers:
                continue
            ideal = self.location+part.definition.points[-1].y+lead
            target = self.reachable_target(part, ideal)
            if target is not None:
                part.release(target, self.rail)
        while sum(not p.attached for p in self.parts) < budget:
            candidates = []
            for i, part in enumerate(self.parts):
                if not part.attached or controlling and part is self.guard:
                    continue
                ideal = self.rail.bounded(self.location+part.definition.points[-1].y)
                offset = self.rail.delta(part.grip_s, ideal)
                strained = (part.length_limit is not None and (
                    part.grip-self.part_root(part.definition)).length() > part.length_limit*.94)
                if strained or (abs(offset) > self.REPLANT_DISTANCE and part.cooldown == 0
                                and self.cooldown == 0):
                    candidates.append((strained, abs(offset), -i, part, ideal))
            if not candidates:
                break
            strained, _, _, part, ideal = max(candidates, key=lambda v: v[:3])
            target = self.reachable_target(part, ideal+lead)
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
