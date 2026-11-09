"""阅读专用的小范围选位；在入场时规划，静止阅读期间不重复搜索"""
from math import cos, pi, sin

from ...shared.geometry import Bounds, Vec2


class ReadingMotion:
    HALF_SIZE = 64.  # 关闭日常游走时的固定停驻范围，不随每轮阅读累积位移
    MAX_APPROACH = 200.

    def __init__(self):
        self.anchor = None
        self.clear()

    def clear(self, *, reset_anchor=False):
        if reset_anchor:
            self.anchor = None
        self.origin = self.box = self.approach = self.pearl_target = None
        self.prepared = False
        self.return_to = None

    def begin(self, scene, *, stationary=False):
        self.clear()
        b = scene.behavior
        body = scene.body.chunks[0].position
        region = scene.navigator.region if scene.navigator else scene.body_region
        edge = b.drift_edge if b.drift_active else b.current_edge(scene)
        box = region.edge_boxes[edge]
        self.origin = body
        if not b.movement_enabled:
            if self.anchor is None or not box.contains(self.anchor):
                # 临时侧倾的支点补偿不是新的停驻位置
                neutral = scene.mouse_reaction.avoidance.neutral_position(scene)
                self.anchor = box.clamp(scene.project_target(neutral))
            self.origin = self.anchor
            r = self.HALF_SIZE
            box = Bounds(max(box.left, self.anchor.x-r), max(box.top, self.anchor.y-r),
                         min(box.right, self.anchor.x+r), min(box.bottom, self.anchor.y+r))
            if not stationary:
                self.return_to = self.anchor
        self.box = box

    def route_to(self, scene, point):
        if scene.navigator is None or self.box is None:
            return None
        body = scene.body.chunks[0].position
        return scene.navigator.planner.round_polyline(
            [body, point], scene.body.chunks[0].velocity, box=self.box)

    def _body_clear(self, scene, point):
        return (self.box.contains(point)
                and (scene.project_target(point)-point).length() < .01
                and scene.behavior.matrix_clear(scene, point))

    def arc(self, scene, point, center):
        if scene.navigator is None:
            return None
        # 曲线凸包已限制在局部走廊内，再检查途中与矩阵和真实支撑范围的间距
        return scene.navigator.planner.local_arc(point, center, self.box, scene.behavior.orbit_sign,
            accept=lambda route: all(self._body_clear(scene, route.sample(route.length*i/8)) for i in range(9)))

    def _candidates(self, scene, center):
        b, body = scene.behavior, scene.body.chunks[0].position
        distance = b.OBSERVE_DISTANCE
        # 环绕的原有弧线半径上限为 72，先尝试配置距离，再用较小半径留出空间
        # 与实际弧线的 32～72 半径边界留 2px 余量，容纳失重时的轻微漂移
        radii = (distance,) if b.mode != 'orbit' else tuple(dict.fromkeys((max(34., min(70., distance)), 40., 34.)))
        candidates = []
        for radius in radii:
            for i in range(16):
                angle = i*pi/8
                point = self.box.clamp(center+Vec2(cos(angle), sin(angle))*radius)
                separation = (point-center).length()
                if b.mode == 'orbit' and not 34 <= separation <= 70:
                    continue
                if (not max(32., radius-18) <= separation <= radius+15
                        or (point-body).length() > self.MAX_APPROACH
                        or not self._body_clear(scene, point)
                        or not scene.arm_region.segment_safe(point, center)):
                    continue
                # 不跨越矩阵；出发点偶尔已有重叠时允许离开该位置
                if not all(b.matrix_clear(scene, body.lerp(point, j/4)) for j in (1, 2, 3)):
                    continue
                score = (point-body).length()+abs(separation-distance)*.5
                candidates.append((score, point))
        return sorted(candidates, key=lambda item: item[0])

    def _pearl_clear(self, scene, point):
        pearl = scene.observed_pearl
        if not pearl.region.contains(point):
            return False
        matrix = scene.pearl_matrix
        if matrix is not None:
            if any((point-(matrix.anchor.position+p.offset)).length() < 22.
                   for p in matrix.pearls if p is not matrix.extracted_member):
                return False
        diameter = pearl.radius*2
        return scene.behavior.recall_obstacles.clear(point, diameter, diameter)

    def prepare(self, scene):
        """原珠位、有限次挪珠、靠近兜底；成功后仅移动选中的珠子"""
        self.prepared = True
        b, pearl = scene.behavior, scene.observed_pearl
        b.recall_obstacles.update(scene)
        original = pearl.position
        # 原位置优先；矩阵珠需先脱离邻珠，远处固定珠也可移到停驻点附近
        centers = [original]
        for radius in (max(38., min(65., b.OBSERVE_DISTANCE)), 80.):
            for i in range(8):
                angle = i*pi/4
                centers.append(pearl.region.clamp(self.origin+Vec2(cos(angle), sin(angle))*radius))
        alternatives = sorted(set(centers[1:]), key=lambda p: (p-original).length())
        fallback = None
        for center in [original, *alternatives]:
            if not self._pearl_clear(scene, center):
                continue
            if b.matrix_observation and (center-pearl.home).length() < 8.:
                continue
            candidates = self._candidates(scene, center)
            if candidates and fallback is None:
                fallback = center, candidates[0][1]
            for _, point in candidates[:6]:
                if b.mode != 'orbit' or self.arc(scene, point, center) is not None:
                    self.pearl_target, self.approach = center, point
                    pearl.move_to(center)  # 锁住固定珠，避免人偶接近时珠子又跟随迁移
                    return True
        if fallback is not None:
            self.pearl_target, self.approach = fallback
            pearl.move_to(self.pearl_target)
            return True
        return False

    def return_body(self, scene):
        if self.return_to is not None:
            point = scene.project_target(self.return_to)
            self.return_to = self.anchor = point
            scene._move_to(point, route=self.route_to(scene, point), speed=scene.config.float_speed*.7)

    def returned(self, scene):
        return self.return_to is None or (scene.body.chunks[0].position-self.return_to).length() < .05
