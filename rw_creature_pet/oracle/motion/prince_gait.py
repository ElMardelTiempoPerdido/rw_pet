"""Prince 沿前方路线安排抓点，只预测支撑，不推进身体或修改导航"""
from math import ceil, sqrt

from ...shared.geometry import Vec2


class PrinceGait:
    LOOKAHEAD_TICKS = 56.
    MIN_LOOKAHEAD = 40.
    MAX_LOOKAHEAD = 80.
    MIN_STEP = 36.
    MIN_GAIN = 12.
    URGENT_GAIN = 8.

    def __init__(self, support):
        self.support = support

    def preview(self, scene):
        """即使身体暂时等待，前方路线仍提供稳定提前量；不越过当前终点"""
        nav = getattr(scene, 'navigator', None)
        body = self.support.body_position
        if nav is not None and not nav.done:
            speed = getattr(scene, 'travel_speed', None) or nav.max_speed
            distance = min(self.MAX_LOOKAHEAD, max(self.MIN_LOOKAHEAD, speed*self.LOOKAHEAD_TICKS))
            offset = nav.route.sample(nav.distance+distance)-body
        else:
            offset = getattr(scene, 'target', body)-body
        return offset*min(1., self.MAX_LOOKAHEAD/max(offset.length(), 1e-9))

    def reach(self, part):
        s = self.support
        return max(1., part.reference_length*s.AUTO_REACH-s.AUTO_ROOT_MARGIN)

    def carries(self, part, shift=Vec2()):
        root = self.support.part_root(part.definition)
        return (part.attached and (root-part.grip).length() <= self.reach(part)
                and (root+shift-part.grip).length() <= self.reach(part))

    def can_handoff(self, part, target, shift):
        s = self.support
        distance = (s.rail.sample(target)[0]-part.nodes[-1].position).length()
        duration = max(18, min(48, ceil(distance/2.5)))
        # 除当前位置外，还检查换点期间的预计位移，避免刚松开就顶到接替者的边界
        shift = shift*min(1., (duration+8)/self.LOOKAHEAD_TICKS)
        alternatives = [p for p in s.parts if p is not part and self.carries(p)]
        if any(self.carries(p, shift) for p in alternatives):
            return True
        # 接近当前支撑边界时允许先由另一条稳住，再完成换点
        # 不能要求接替者独自走完整段，否则跨角处会互相等待
        root = s.part_root(part.definition)
        return bool(alternatives) and (root-part.grip).length() >= self.reach(part)-4.

    def runway(self, part, grip, shift):
        """从当前根部沿前进方向，在该抓点的松弛范围内还能移动多远"""
        delta = grip-self.support.part_root(part.definition)
        direction = shift*(1./max(shift.length(), 1e-9))
        along = delta.x*direction.x+delta.y*direction.y
        cross2 = max(0., delta.x*delta.x+delta.y*delta.y-along*along)
        reach = self.reach(part)
        return along+sqrt(max(0., reach*reach-cross2)) if cross2 <= reach*reach else 0.

    def target(self, part, shift):
        s, rail = self.support, self.support.rail
        root = s.part_root(part.definition)
        ideal = s.ideal_grip(part.definition, root+shift, part.reference_length)
        if part.definition.grip_directions is None:
            ideal += rail.delta(rail.project(root, part.grip_s), rail.project(root+shift, part.grip_s))
        # 当前必须够得着；在偏好抓点附近比较前方落点，保留各触手配置的方向差异
        candidates = []
        for preferred in (ideal, rail.project(root+shift, part.grip_s),
                          rail.project(root+shift*.5, part.grip_s)):
            target = s.reachable_target(part, preferred, reach=part.reference_length*s.AUTO_REGRIP)
            if target is not None:
                grip = rail.sample(target)[0]
                gain = self.runway(part, grip, shift)-self.runway(part, part.grip, shift)
                score = abs(rail.delta(ideal, target))-.35*min(self.MAX_LOOKAHEAD*2, gain)
                candidates.append((score, target))
        return min(candidates)[1] if candidates else None

    def needs_step(self, part, shift, offset):
        s, rail = self.support, self.support.rail
        root = s.part_root(part.definition)
        along = rail.delta(rail.project(root, part.grip_s), rail.project(root+shift, part.grip_s))
        # 已经提前落在前方的抓点可以继续使用，不为追逐当前偏好而后退一步
        behind = abs(offset) > s.REPLANT_DISTANCE and (abs(along) < 1. or offset*along > 0.)
        return behind or (root+shift-part.grip).length() > self.reach(part)

    def worthwhile(self, part, target, shift):
        s, rail = self.support, self.support.rail
        distance = abs(rail.delta(part.grip_s, target))
        grip = rail.sample(target)[0]
        gain = self.runway(part, grip, shift)-self.runway(part, part.grip, shift)
        root = s.part_root(part.definition)
        urgent = (root-part.grip).length() >= self.reach(part)-4.
        minimum = min(self.MIN_STEP, part.reference_length*.22)
        if urgent:
            # 临近支撑边界时允许较小的一步，但必须实际增加可前进余量
            return distance >= self.URGENT_GAIN and gain >= self.URGENT_GAIN
        return distance >= minimum and gain >= self.MIN_GAIN
