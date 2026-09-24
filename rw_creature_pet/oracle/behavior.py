"""Bell 日常活动：停留、同边短途、低概率邻边移动及珍珠观察。"""
from enum import Enum
from math import cos, pi, sin
from random import Random

from ..shared.geometry import Vec2


class Activity(str, Enum):
    IDLE = '停留'
    ROAM = '短途漂浮'
    CROSS_EDGE = '移到相邻边'
    NOTICE = '注意珍珠'
    APPROACH = '靠近观察'
    RECALL = '将珍珠召近'
    OBSERVE = '保持观察'
    RETURN = '送回悬浮点'


class OracleBehavior:
    IDLE_TICKS = (120, 240)
    LONG_IDLE_TICKS = (300, 720)
    CROSS_EDGE_COOLDOWN = 2400  # 到达邻边后至少 60 秒，防止连续绕行。
    NOTICE_TICKS = (36, 60)
    OBSERVE_TICKS = (140, 240)
    OBSERVE_DISTANCE = 50.
    RECALL_DISTANCE = 38.
    ROAM_DISTANCE = (60., 160.)
    MAX_LOCAL_APPROACH = 200.

    def __init__(self, seed=620):
        self.random = Random(seed)
        self.enabled = False
        self.state = Activity.IDLE
        self.state_ticks = 0
        self.duration = self.random.randint(*self.IDLE_TICKS)
        self.mode = None
        self.completed_cycles = 0
        self.edge = None
        self.destination_edge = None
        self.cross_cooldown = 0

    @property
    def active(self):
        return self.enabled or self.state != Activity.IDLE

    @property
    def looking(self):
        return self.state in (Activity.NOTICE, Activity.APPROACH, Activity.RECALL,
                              Activity.OBSERVE, Activity.RETURN)

    @property
    def controls_pearl(self):
        return self.state in (Activity.NOTICE, Activity.APPROACH, Activity.RECALL, Activity.OBSERVE)

    def enter(self, state, duration=0):
        self.state, self.state_ticks, self.duration = state, 0, duration

    def cancel(self, scene, *, stop_body=True):
        if not self.active:
            return
        self.enabled = False
        self.enter(Activity.IDLE)
        scene.eyes.end_observation()
        scene.look_target = None
        scene.pearl.return_home()
        if stop_body:
            scene._move_to(scene.body.chunks[0].position)

    def set_enabled(self, scene, enabled):
        if not enabled:
            self.cancel(scene)
            return
        if self.enabled:
            return
        self.enabled = True
        if self.state == Activity.IDLE:
            scene._move_to(scene.body.chunks[0].position)
            scene.look_target = None
            scene.eyes.end_observation()
            self.enter(Activity.IDLE, self.random.randint(*self.IDLE_TICKS))

    def notice(self, scene, mode=None):
        if mode not in (None, 'approach', 'recall'):
            raise ValueError('观察方式必须为 approach 或 recall')
        self.mode = mode or self.random.choice(('approach', 'recall'))
        scene._move_to(scene.body.chunks[0].position)
        scene.look_target = scene.pearl.position
        scene.eyes.begin_observation(restart=True)
        self.enter(Activity.NOTICE, self.random.randint(*self.NOTICE_TICKS))

    def current_edge(self, scene):
        """按人偶所在走廊判定；角落重叠时保留上一条边，不跟着底座抖动。"""
        if not scene.navigator:
            self.edge = ('top', 'right', 'bottom', 'left').index(scene.anchor.side.value)
            return self.edge
        p = scene.body.chunks[0].position
        boxes = scene.navigator.region.boxes
        if self.edge is None or not boxes[self.edge].contains(p):
            distances = (p.y, scene.world.width-p.x, scene.world.height-p.y, p.x)
            self.edge = min((i for i, box in enumerate(boxes) if box.contains(p)), key=lambda i: distances[i])
        return self.edge

    def choose_activity(self, scene):
        """每个停留周期只抽一次。固定底座/冷却中的跨边分支退回停留。"""
        value = self.random.random()
        cross = scene.config.cross_edge_probability
        if value < cross:
            return Activity.CROSS_EDGE if scene.navigator and self.cross_cooldown == 0 else Activity.IDLE
        value = (value-cross)/max(1e-9, 1-cross)
        if value < .40:
            return Activity.IDLE
        return Activity.ROAM if value < .75 else Activity.NOTICE

    def short_point(self, scene):
        edge = self.current_edge(scene)
        region = scene.navigator.region if scene.navigator else scene.body_region
        box, start = region.boxes[edge], scene.body.chunks[0].position
        for _ in range(16):
            angle = self.random.uniform(0, 2*pi)
            distance = self.random.uniform(*self.ROAM_DISTANCE)
            point = scene.project_target(box.clamp(start+Vec2(cos(angle), sin(angle))*distance))
            if box.contains(point) and (point-start).length() >= 30:
                return point
        return None

    def adjacent_route(self, scene, target_edge=None):
        if not scene.navigator:
            return None
        source = self.current_edge(scene)
        neighbors = ((source-1) % 4, (source+1) % 4)
        if target_edge is not None and target_edge not in neighbors:
            raise ValueError('只能自主移动到当前边的两条相邻边')
        planner, start = scene.navigator.planner, scene.body.chunks[0].position
        source_box = planner.region.boxes[source]
        candidates = []
        for edge in neighbors if target_edge is None else (target_edge,):
            clockwise = (edge-source) % 4 == 1
            joint = edge if clockwise else source
            other = (edge+1) % 4 if clockwise else edge
            box = planner.region.boxes[edge]
            for _ in range(12):
                point = planner.corners[joint].lerp(planner.corners[other], self.random.uniform(.18, .38))
                depth = self.random.uniform(.35, .65)
                point = (Vec2(box.left+(box.right-box.left)*depth, point.y) if edge % 2 else
                         Vec2(point.x, box.top+(box.bottom-box.top)*depth))
                if not source_box.contains(point):
                    route = planner.adjacent(start, point, source, edge, scene.body.chunks[0].velocity)
                    candidates.append((edge, point, route))
                    break
        if not candidates:
            return None
        # 两个方向都允许，但更偏向较近的共用角，避免从一个角出发横穿整条长边。
        return self.random.choices(candidates, weights=[1/(80+item[2].length)**2 for item in candidates], k=1)[0]

    def start_roam(self, scene, *, adjacent=False, target_edge=None):
        if adjacent:
            result = self.adjacent_route(scene, target_edge)
            if result is None:
                return False
            edge, point, route = result
            scene._move_to(point, route=route)
            self.destination_edge = edge
        else:
            point = self.short_point(scene)
            if point is None:
                return False
            scene._move_to(point)
            self.destination_edge = self.edge
        scene.look_target = None
        scene.eyes.end_observation()
        self.enter(Activity.CROSS_EDGE if adjacent else Activity.ROAM, self.movement_budget(scene))
        return True

    def approach_point(self, scene):
        pearl, body = scene.pearl.position, scene.body.chunks[0].position
        region = scene.navigator.region if scene.navigator else scene.body_region
        local = region.boxes[self.current_edge(scene)] if self.enabled else None
        candidates = []
        for i in range(16):
            angle = i*pi/8
            p = scene.project_target(pearl+Vec2(cos(angle), sin(angle))*self.OBSERVE_DISTANCE)
            # 自主观察不能绕过低概率跨边规则；珠子较远时改为召近。
            if local and (not local.contains(p) or (p-body).length() > self.MAX_LOCAL_APPROACH):
                continue
            separation = (p-pearl).length()
            if 32 <= separation <= 65 and scene.pearl.region.segment_safe(p, pearl):
                # 倾向当前位置附近，给头部留出独立观察距离，不反复绕珠改道。
                score = (p-body).length()+abs(separation-self.OBSERVE_DISTANCE)*3
                candidates.append((score, p))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def recall_point(self, scene):
        body, pearl = scene.body.chunks[0].position, scene.pearl.position
        candidates = []
        for i in range(16):
            angle = i*pi/8
            p = scene.pearl.region.clamp(body+Vec2(cos(angle), sin(angle))*self.RECALL_DISTANCE)
            if (p-body).length() >= 30 and scene.pearl.region.segment_safe(body, p):
                # 珠子停在脸旁，避免藏进衣袍；优先从原位置一侧召近。
                score = (p-pearl).length()+abs(p.y-(body.y-12))*.8
                candidates.append((score, p))
        return min(candidates, key=lambda item: item[0])[1] if candidates else scene.pearl.home

    def movement_budget(self, scene):
        route = scene.navigator.route if scene.navigator else None
        length = route.length if route else (scene.target-scene.body.chunks[0].position).length()
        # 包括机械臂底座等待与最终收敛；超时只结束本次接近，仍平滑送回。
        return int(max(length, scene.pearl.route.length)/min(.2, scene.config.float_speed*.5))+400

    def step(self, scene):
        self.cross_cooldown = max(0, self.cross_cooldown-1)
        if not self.active:
            return
        self.state_ticks += 1
        if self.state == Activity.IDLE:
            if not scene.arrived or not scene.pose.settled:
                self.state_ticks = 0  # 停留时间从身体真正停稳、姿态收敛后开始。
                return
            if not scene.pearl.settled or self.state_ticks < self.duration:
                return
            activity = self.choose_activity(scene)
            if activity == Activity.NOTICE:
                self.notice(scene)
            elif activity == Activity.IDLE or not self.start_roam(scene, adjacent=activity == Activity.CROSS_EDGE):
                self.enter(Activity.IDLE, self.random.randint(*self.LONG_IDLE_TICKS))
        elif self.state in (Activity.ROAM, Activity.CROSS_EDGE):
            if scene.arrived or self.state_ticks > self.duration:
                if self.state == Activity.CROSS_EDGE:
                    self.cross_cooldown = self.CROSS_EDGE_COOLDOWN
                if scene.arrived:
                    self.edge = self.destination_edge
                scene._move_to(scene.body.chunks[0].position)
                self.enter(Activity.IDLE, self.random.randint(*self.IDLE_TICKS))
        elif (self.state == Activity.NOTICE and self.state_ticks >= self.duration
              and (self.mode == 'recall' or scene.pearl.settled)):
            point = self.approach_point(scene) if self.mode == 'approach' else None
            if point is not None:
                scene._move_to(point)
                self.enter(Activity.APPROACH, self.movement_budget(scene))
            else:
                self.mode = 'recall'
                scene.pearl.move_to(self.recall_point(scene))
                self.enter(Activity.RECALL, self.movement_budget(scene))
        elif self.state in (Activity.APPROACH, Activity.RECALL):
            if scene.arrived and scene.pearl.settled:
                self.enter(Activity.OBSERVE, self.random.randint(*self.OBSERVE_TICKS))
            elif self.state_ticks > self.duration:
                scene._move_to(scene.body.chunks[0].position)
                scene.pearl.return_home()
                self.enter(Activity.RETURN)
                scene.eyes.end_observation()
        elif self.state == Activity.OBSERVE and self.state_ticks >= self.duration:
            scene.pearl.return_home()
            self.enter(Activity.RETURN)
            scene.eyes.end_observation()
        elif (self.state == Activity.RETURN and scene.pearl.settled and self.state_ticks >= 24
              and scene.arrived and scene.pose.settled):
            self.completed_cycles += 1
            scene.look_target = None
            self.enter(Activity.IDLE, self.random.randint(*self.IDLE_TICKS))
