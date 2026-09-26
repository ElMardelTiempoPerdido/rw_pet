"""Bell 日常活动：停留、同边移动、反重力漫游、低概率邻边移动及珍珠观察。"""
from enum import Enum
from math import cos, pi, sin
from random import Random

from ..shared.geometry import Vec2


class Activity(str, Enum):
    IDLE = '停留'
    ROAM = '短途漂浮'
    CROSS_EDGE = '移到相邻边'
    DRIFT = '反重力漫游'
    DRIFT_CROSS_EDGE = '漫游至相邻边'
    MEDITATE = '冥想'
    NOTICE = '注意珍珠'
    APPROACH = '靠近观察'
    RECALL = '将珍珠召近'
    ORBIT = '绕珠观察'
    OBSERVE = '保持观察'
    RETURN = '送回悬浮点'


class OracleBehavior:
    IDLE_TICKS = (120, 240)
    LONG_IDLE_TICKS = (300, 720)
    CROSS_EDGE_COOLDOWN = 2400  # 到达邻边后至少 60 秒，防止连续绕行。
    DRIFT_COOLDOWN = 4800  # 退出漫游后至少 120 秒才允许再次自主触发。
    DRIFT_OBSERVE_TICKS = (800, 1600)  # 失重期间，每轮观察结束后再等 20～40 秒。
    DRIFT_CROSS_CHECK_TICKS = 800  # 只在选下一段路线时抽取，至少间隔 20 秒。
    DRIFT_ENTRY_TICKS = (100, 200)  # 初次失重后等待 2.5～5 秒。
    DRIFT_RESUME_TICKS = (20, 120)  # 观察/跨边之后等待 0.5～3 秒。
    # 短暂犹豫、普通停留、偶尔长歇；长歇后下一次从前两档选择。
    DRIFT_PAUSE_BANDS = ((14, 48), (72, 220), (280, 560))
    DRIFT_PAUSE_WEIGHTS = (.50, .35, .15)
    DRIFT_BOUT_BANDS = ((160, 400), (480, 960))  # 一轮连续漂浮约 4～10 / 12～24 秒。
    NOTICE_TICKS = (36, 60)
    OBSERVE_TICKS = (140, 240)
    MATRIX_OBSERVATION_SHARE = .5  # 矩阵开启时，观察活动的一半从矩阵抽取一颗。
    OBSERVE_DISTANCE = 50.
    RECALL_DISTANCE = 38.
    ROAM_DISTANCE = (60., 160.)
    MAX_LOCAL_APPROACH = 200.
    MEDITATE_SHARE = .12  # 排除跨边、反重力分支后，从停留份额中分配。
    MEDITATE_TICKS = (1200, 2400)  # 身体和视线停稳后，闭眼停留 30～60 秒。

    def __init__(self, seed=620):
        self.random = Random(seed)
        self.pace_random = Random(seed+1)  # 调整速度不消耗活动选择的随机流。
        self.detail_random = Random(seed+2)
        self.timing_random = Random(seed+3)  # 停走节奏独立于路线、速度、观察与跨边抽样。
        self.pearl_random = Random(seed+4)
        self.fixed_random = Random(seed+5)  # 固定珠选择不改变矩阵槽位的随机序列。
        self.observation_pearl = None
        self.matrix_observation = False
        self.last_matrix_slot = None
        self.last_fixed_index = None
        self.enabled = False
        self.state = Activity.IDLE
        self.state_ticks = 0
        self.duration = self.random.randint(*self.IDLE_TICKS)
        self.mode = None
        self.completed_cycles = 0
        self.edge = None
        self.destination_edge = None
        self.cross_cooldown = 0
        self.drift_cooldown = 0
        self.drift_active = False
        self.drift_ticks = self.drift_duration = 0
        self.drift_recovering = False
        self.drift_next_move = 0
        self.drift_next_observation = 0
        self.drift_next_cross_check = 0
        self.drift_edge = 0
        self.drift_join_checked = False
        self.drift_pause_ticks = 0
        self.drift_last_pause = 0
        self.drift_bout_until = 0
        self.orbit_sign = 1
        self.meditation_ticks = 0

    @property
    def active(self):
        return self.enabled or self.state != Activity.IDLE

    @property
    def looking(self):
        return self.state in (Activity.NOTICE, Activity.APPROACH, Activity.RECALL,
                              Activity.ORBIT, Activity.OBSERVE, Activity.RETURN)

    @property
    def controls_pearl(self):
        return self.state in (Activity.NOTICE, Activity.APPROACH, Activity.RECALL, Activity.ORBIT, Activity.OBSERVE)

    def enter(self, state, duration=0):
        self.state, self.state_ticks, self.duration = state, 0, duration

    def end_drift(self, scene):
        if self.drift_active:
            self.finish_drift_crossing(scene)
            if not self.drift_recovering:
                scene.pose.recover_upright(scene)
            self.drift_active = False
            self.drift_recovering = False
            self.drift_cooldown = self.DRIFT_COOLDOWN

    def cancel(self, scene, *, stop_body=True):
        if not self.active:
            return
        self.enabled = False
        self.end_drift(scene)
        self.enter(Activity.IDLE)
        scene.eyes.end_observation()
        scene.look_target = None
        self.release_observation()
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

    def release_observation(self):
        """离队珠子的归队由矩阵继续推进，不依赖当前行为仍在观察。"""
        if self.observation_pearl is not None:
            self.observation_pearl.return_home()
        self.observation_pearl = None
        self.matrix_observation = False

    def notice(self, scene, mode=None, *, matrix=False, slot=None):
        if mode not in (None, 'approach', 'recall', 'orbit'):
            raise ValueError('观察方式必须为 approach、recall 或 orbit')
        group = scene.pearl_matrix
        fixed = scene.fixed_pearls.roots
        if matrix and group is None:
            return False
        if slot is not None and (group is None or not any(p.slot == slot for p in group.pearls)):
            raise ValueError(f'不存在的矩阵槽位：{slot}')
        if mode is None and group is not None and group.extracted is None:
            matrix = matrix or self.pearl_random.random() < self.MATRIX_OBSERVATION_SHARE
        if not fixed:
            matrix = group is not None
        if not matrix and not fixed:
            self.release_observation()
            scene.eyes.end_observation()
            self.resume_or_idle(scene)  # 无可观察目标时正常继续活动，不逐帧重试。
            return False
        manual = mode is not None
        self.release_observation()
        if matrix:
            if group.extracted is None:
                choices = [p.slot for p in group.pearls if p.slot != self.last_matrix_slot]
                if not choices:  # 只有一颗时允许再次选中。
                    choices = [p.slot for p in group.pearls]
                slot = slot if slot is not None else self.pearl_random.choice(choices)
                pearl = group.extract(slot)
            else:
                pearl = group.extracted
            self.last_matrix_slot = group.extracted_member.slot
            # 重复点击/重新观察正在归队的珠子时，先在当前位置柔和减速。
            pearl.move_to(pearl.position)
            self.observation_pearl = pearl
            self.matrix_observation = True
            mode = 'recall'
        else:
            if manual:
                index = min(range(len(fixed)), key=lambda i: (fixed[i].position-scene.body.chunks[0].position).length())
            else:
                choices = [i for i in range(len(fixed)) if i != self.last_fixed_index] or [0]
                index = self.fixed_random.choice(choices)
            self.last_fixed_index = index
            self.observation_pearl = fixed[index]
        self.finish_drift_crossing(scene)
        self.mode = mode or self.detail_random.choices(('approach', 'recall', 'orbit'), (.35, .35, .30))[0]
        self.orbit_sign = self.detail_random.choice((-1, 1))
        self.drift_pause_ticks = 0
        scene._move_to(scene.body.chunks[0].position)
        scene.look_target = scene.observed_pearl.position
        scene.eyes.begin_observation(restart=True)
        self.enter(Activity.NOTICE, self.random.randint(*self.NOTICE_TICKS))
        return True

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
        drift = scene.config.antigravity_probability
        if value < drift:
            return Activity.DRIFT if self.drift_cooldown == 0 else Activity.IDLE
        value = (value-drift)/max(1e-9, 1-drift)
        if value < self.MEDITATE_SHARE:
            return Activity.MEDITATE
        if value < .40:
            return Activity.IDLE
        return Activity.ROAM if value < .75 else Activity.NOTICE

    def short_point(self, scene, distance_range=None):
        edge = self.current_edge(scene)
        region = scene.navigator.region if scene.navigator else scene.body_region
        box, start = region.boxes[edge], scene.body.chunks[0].position
        for _ in range(16):
            angle = self.random.uniform(0, 2*pi)
            distance = self.random.uniform(*(distance_range or self.ROAM_DISTANCE))
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
            scene._move_to(point, route=route, speed=self.travel_speed(scene, Activity.CROSS_EDGE, route.length))
            self.destination_edge = edge
        else:
            point = self.short_point(scene)
            if point is None:
                return False
            distance = (point-scene.body.chunks[0].position).length()
            scene._move_to(point, speed=self.travel_speed(scene, Activity.ROAM, distance))
            self.destination_edge = self.edge
        scene.look_target = None
        scene.eyes.end_observation()
        self.enter(Activity.CROSS_EDGE if adjacent else Activity.ROAM, self.movement_budget(scene))
        return True

    def travel_speed(self, scene, activity, distance=0.):
        """每段行动只选一次节奏；导航负责平滑加减速、过角和支撑限速。"""
        if activity == Activity.DRIFT:
            return scene.config.drift_speed*self.pace_random.uniform(.8, 1.2)
        if activity == Activity.ORBIT:
            return scene.config.float_speed*.53*self.pace_random.uniform(.9, 1.1)
        if activity == Activity.APPROACH:
            factor = 1.15
        else:
            # 远距离换位置更积极；短途保留从容节奏。
            factor = .85+.4*max(0., min(1., (distance-60.)/240.))
        return min(2.2, scene.config.float_speed*factor*self.pace_random.uniform(.95, 1.05))

    def start_drift(self, scene):
        """先减速并逐渐失重；通常同边漂浮，偶尔经共用角移到邻边。"""
        scene._move_to(scene.body.chunks[0].position)
        scene.look_target = None
        scene.eyes.end_observation()
        self.release_observation()
        self.drift_edge = self.current_edge(scene)
        self.drift_active = True
        self.drift_ticks = 0
        self.drift_recovering = False
        self.drift_next_move = self.timing_random.randint(*self.DRIFT_ENTRY_TICKS)
        self.drift_next_cross_check = self.DRIFT_CROSS_CHECK_TICKS
        self.drift_join_checked = False
        self.drift_pause_ticks = 0
        self.drift_last_pause = 0
        self.drift_bout_until = 0
        self.drift_cooldown = self.DRIFT_COOLDOWN
        ticks = scene.config.antigravity_duration_seconds*scene.TICK_RATE
        self.drift_duration = self.random.randint(round(ticks*.9), round(ticks*1.1))
        self.drift_next_observation = self.random.randint(480, 960)
        self.enter(Activity.DRIFT)

    def start_drift_crossing(self, scene, target_edge=None):
        """共用普通邻边的安全路径，但保留漫游速度、失重和整段计时。"""
        if not self.drift_active or self.drift_recovering:
            return False
        result = self.adjacent_route(scene, target_edge)
        if result is None:
            return False
        edge, point, route = result
        scene._move_to(point, route=route, speed=self.travel_speed(scene, Activity.DRIFT))
        self.destination_edge = edge
        self.drift_pause_ticks = 0
        self.enter(Activity.DRIFT_CROSS_EDGE, self.movement_budget(scene))
        return True

    def try_drift_crossing(self, scene):
        if (not scene.navigator or self.cross_cooldown or scene.config.cross_edge_probability == 0
                or self.drift_ticks < self.drift_next_cross_check
                or self.drift_duration-self.drift_ticks < 160):
            return False
        self.drift_next_cross_check = self.drift_ticks+self.DRIFT_CROSS_CHECK_TICKS
        return (self.detail_random.random() < scene.config.cross_edge_probability
                and self.start_drift_crossing(scene))

    def finish_drift_crossing(self, scene):
        if self.state != Activity.DRIFT_CROSS_EDGE:
            return
        # 手动观察/冥想也能中断过角；以实际位置接续，不能拉回旧边。
        self.drift_edge = self.current_edge(scene)
        self.destination_edge = None
        self.cross_cooldown = self.CROSS_EDGE_COOLDOWN
        self.drift_next_cross_check = self.drift_ticks+self.DRIFT_CROSS_CHECK_TICKS

    def step_drift_crossing(self, scene):
        # 到期或自动观察都等本次过角结束，避免半途撤销相邻走廊约束。
        if scene.arrived or self.state_ticks > self.duration:
            if scene.arrived:
                self.edge = self.destination_edge
            self.finish_drift_crossing(scene)
            scene._move_to(scene.body.chunks[0].position)
            self.drift_next_move = self.drift_ticks+self.timing_random.randint(*self.DRIFT_RESUME_TICKS)
            self.enter(Activity.DRIFT)

    def sample_drift_pause(self):
        weights = list(self.DRIFT_PAUSE_WEIGHTS)
        if self.drift_last_pause >= self.DRIFT_PAUSE_BANDS[-1][0]:
            weights[-1] = 0.  # 避免连续两次长歇，让偶尔停久一些更明显。
        band = self.timing_random.choices(self.DRIFT_PAUSE_BANDS, weights)[0]
        self.drift_last_pause = self.timing_random.randint(*band)
        return self.drift_last_pause

    def drift_move_to(self, scene, point, *, observing=False):
        route = None
        if scene.navigator:
            upper = scene.body.chunks[0]
            route = scene.navigator.planner.round_polyline(
                [upper.position, point], upper.velocity,
                box=scene.navigator.region.boxes[self.drift_edge])
        scene._move_to(point, route=route, speed=self.travel_speed(
            scene, Activity.APPROACH if observing else Activity.DRIFT))
        self.drift_join_checked = False
        if not observing:
            band = self.timing_random.choices(self.DRIFT_BOUT_BANDS, (.65, .35))[0]
            self.drift_bout_until = self.drift_ticks+self.timing_random.randint(*band)
            # 固定底座无法接续曲线，也应在每段到达后有一次随机停留。
            if not scene.navigator:
                self.drift_pause_ticks = self.sample_drift_pause()

    def drift_point(self, scene, start, forward=None):
        """沿当前边漫游并改变深度；目标离走廊外沿留余量，便于继续转弯。"""
        region = scene.navigator.region if scene.navigator else scene.body_region
        box = region.boxes[self.drift_edge]
        vertical = self.drift_edge % 2
        component = (forward.y if vertical else forward.x) if forward is not None else self.random.choice((-1, 1))
        sign = 1 if component >= 0 else -1
        for attempt in range(16):
            direction = sign if forward is not None or attempt < 8 else -sign
            distance = self.random.uniform(60., 100.)
            depth = self.random.uniform(.25, .75)
            candidate = (Vec2(box.left+(box.right-box.left)*depth, start.y+direction*distance) if vertical else
                         Vec2(start.x+direction*distance, box.top+(box.bottom-box.top)*depth))
            point = scene.project_target(box.clamp(candidate))
            if box.contains(point) and (point-start).length() >= 30:
                return point
        return None

    def continue_drift(self, scene):
        navigator = scene.navigator
        if (not navigator or navigator.done or self.drift_join_checked
                or self.drift_ticks < self.drift_next_move):
            return
        remaining = navigator.route.length-navigator.distance
        # 在进入终点刹车区之前作一次决定，失败后不逐帧重新抽取。
        if remaining > max(32., navigator.speed**2/.09+navigator.speed*16):
            return
        self.drift_join_checked = True
        deadline = min(self.drift_next_observation, self.drift_duration)
        if deadline-self.drift_ticks < remaining/max(.3, navigator.speed)+160:
            self.drift_next_move = deadline  # 到点后等待观察/结束，不再发起短途。
            return
        # 每轮出发时选一次持续时长；在安全的途经点接续，接近该时长
        # 才准备停下。时间不够走完当前段时也只在终点刹车，不半途硬停。
        if self.drift_ticks+remaining/max(.3, navigator.speed) < self.drift_bout_until:
            end = navigator.route.curves[-1]
            point = self.drift_point(scene, end.d, end.d-end.c)
            if point is not None and navigator.extend_to(point, navigator.region.boxes[self.drift_edge]):
                scene.requested_target = scene.target = point
                scene.travel_speed = self.travel_speed(scene, Activity.DRIFT)
                self.drift_join_checked = False
                return
        self.drift_pause_ticks = self.sample_drift_pause()

    def step_drift(self, scene):
        if not self.drift_recovering and self.drift_ticks >= self.drift_duration:
            self.drift_recovering = True
            self.drift_cooldown = self.DRIFT_COOLDOWN
            scene._move_to(scene.body.chunks[0].position)
            scene.pose.recover_upright(scene)
        if self.drift_recovering:
            if scene.arrived and scene.pose.settled and scene.pose.weightlessness == 0.:
                self.end_drift(scene)
                self.enter(Activity.IDLE, self.random.randint(*self.LONG_IDLE_TICKS))
            return
        self.continue_drift(scene)
        # 旋转期间质点仍有小幅运动，不能用完全静止作为下一段的前提。
        route_done = scene.navigator is None or scene.navigator.done
        near = (scene.body.chunks[0].position-scene.target).length() < 2.
        if route_done and near and self.drift_ticks >= self.drift_next_observation:
            self.notice(scene)  # 观察活动可以改变，失重模式及总计时保持。
            return
        if route_done and near and self.drift_ticks >= self.drift_next_move:
            if self.drift_pause_ticks:
                self.drift_next_move = self.drift_ticks+self.drift_pause_ticks
                self.drift_pause_ticks = 0
                return
            if self.try_drift_crossing(scene):
                return
            point = self.drift_point(scene, scene.body.chunks[0].position)
            if point is not None:
                self.drift_move_to(scene, point)
            self.drift_next_move = self.drift_ticks+(0 if point is not None else self.timing_random.randint(40, 160))

    def approach_point(self, scene):
        pearl, body = scene.observed_pearl.position, scene.body.chunks[0].position
        region = scene.navigator.region if scene.navigator else scene.body_region
        local = (region.boxes[self.drift_edge] if self.drift_active else
                 region.boxes[self.current_edge(scene)] if self.enabled or self.mode == 'orbit' else None)
        candidates = []
        for i in range(16):
            angle = i*pi/8
            p = scene.project_target(pearl+Vec2(cos(angle), sin(angle))*self.OBSERVE_DISTANCE)
            # 自主观察不能绕过低概率跨边规则；珠子较远时改为召近。
            if local and (not local.contains(p) or (p-body).length() > self.MAX_LOCAL_APPROACH):
                continue
            separation = (p-pearl).length()
            if 32 <= separation <= 65 and scene.arm_region.segment_safe(p, pearl):
                # 倾向当前位置附近，给头部留出独立观察距离，不反复绕珠改道。
                score = (p-body).length()+abs(separation-self.OBSERVE_DISTANCE)*3
                candidates.append((score, p))
        if self.mode == 'orbit' and scene.navigator:
            # 在几个就近观察点中优先选能留出弧线空间的一个；只在入场时规划。
            available = []
            for score, point in sorted(candidates, key=lambda item: item[0])[:5]:
                route = scene.navigator.planner.local_arc(point, pearl, local, self.orbit_sign)
                if route is not None:
                    available.append((score-min(70., route.length)*.6, point))
            if available:
                return min(available, key=lambda item: item[0])[1]
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    def start_orbit(self, scene):
        if not scene.navigator:
            return False  # 固定底座调试保留原地观察，不用直线冒充圆弧。
        edge = self.drift_edge if self.drift_active else self.current_edge(scene)
        box = scene.navigator.region.boxes[edge]
        route = scene.navigator.planner.local_arc(scene.body.chunks[0].position,
                                                  scene.observed_pearl.position, box, self.orbit_sign)
        if route is None:
            return False
        scene._move_to(route.curves[-1].d, route=route, speed=self.travel_speed(scene, Activity.ORBIT))
        self.enter(Activity.ORBIT, self.movement_budget(scene))
        return True

    def resume_or_idle(self, scene):
        self.observation_pearl = None
        self.matrix_observation = False
        scene.look_target = None
        if self.drift_active:
            self.drift_pause_ticks = 0
            self.drift_next_move = self.drift_ticks+self.timing_random.randint(*self.DRIFT_RESUME_TICKS)
            self.drift_next_observation = self.drift_ticks+self.random.randint(*self.DRIFT_OBSERVE_TICKS)
            self.enter(Activity.DRIFT)
        else:
            self.enter(Activity.IDLE, self.random.randint(*self.IDLE_TICKS))

    def start_meditation(self, scene):
        self.release_observation()
        self.finish_drift_crossing(scene)
        edge = self.drift_edge if self.drift_active else self.current_edge(scene)
        region = scene.navigator.region if scene.navigator else scene.body_region
        box, start = region.boxes[edge], scene.body.chunks[0].position
        # 只稍微向当前走廊中间收拢，不去屏幕中央，也不跨边找固定房间坐标。
        offset = ((box.left+box.right)/2-start.x if edge % 2 else
                  (box.top+box.bottom)/2-start.y)
        offset = max(-24., min(24., offset))
        point = scene.project_target(start+(Vec2(offset, 0) if edge % 2 else Vec2(0, offset)))
        route = scene.navigator.planner.round_polyline([start, point], scene.body.chunks[0].velocity,
                                                       box=box) if scene.navigator else None
        scene._move_to(point, route=route, speed=scene.config.drift_speed*.75)
        scene.eyes.end_observation()
        # 固定一次低头目标，避免停留时每帧重设姿态、唤醒次级外观。
        scene.look_target = point-scene.body.direction*40
        self.meditation_ticks = 0
        self.enter(Activity.MEDITATE, self.random.randint(*self.MEDITATE_TICKS))

    def step_meditation(self, scene):
        resting = (scene.arrived and scene.pose.settled and scene.observation_pearls_settled and not scene.eyes.moving
                   and scene.head.velocity.length() < .001
                   and (scene.look_direction-scene.previous_look_direction).length() < .00001)
        self.meditation_ticks = self.meditation_ticks+1 if resting else 0
        if self.meditation_ticks >= self.duration:
            self.resume_or_idle(scene)

    def recall_point(self, scene):
        body, pearl = scene.body.chunks[0].position, scene.observed_pearl.position
        candidates = []
        for i in range(16):
            angle = i*pi/8
            p = scene.observed_pearl.region.clamp(body+Vec2(cos(angle), sin(angle))*self.RECALL_DISTANCE)
            if (p-body).length() >= 30 and scene.arm_region.segment_safe(body, p):
                # 珠子停在脸旁，避免藏进衣袍；优先从原位置一侧召近。
                score = (p-pearl).length()+abs(p.y-(body.y-12))*.8
                candidates.append((score, p))
        return min(candidates, key=lambda item: item[0])[1] if candidates else scene.observed_pearl.home

    def movement_budget(self, scene):
        route = scene.navigator.route if scene.navigator else None
        length = route.length if route else (scene.target-scene.body.chunks[0].position).length()
        # 包括机械臂底座等待与最终收敛；超时只结束本次接近，仍平滑送回。
        pearl_length = scene.observed_pearl.route.length if scene.observed_pearl is not None else 0.
        return int(max(length, pearl_length)/min(.2, scene.config.float_speed*.5))+400

    def step(self, scene):
        self.cross_cooldown = max(0, self.cross_cooldown-1)
        self.drift_cooldown = max(0, self.drift_cooldown-1)
        if self.drift_active:
            self.drift_ticks += 1
        if not self.active:
            return
        self.state_ticks += 1
        if self.state == Activity.IDLE:
            if not scene.arrived or not scene.pose.settled:
                self.state_ticks = 0  # 停留时间从身体真正停稳、姿态收敛后开始。
                return
            if not scene.observation_pearls_settled or self.state_ticks < self.duration:
                return
            activity = self.choose_activity(scene)
            if activity == Activity.NOTICE:
                self.notice(scene)
            elif activity == Activity.MEDITATE:
                self.start_meditation(scene)
            elif activity == Activity.DRIFT:
                self.start_drift(scene)
            elif activity == Activity.IDLE or not self.start_roam(scene, adjacent=activity == Activity.CROSS_EDGE):
                self.enter(Activity.IDLE, self.random.randint(*self.LONG_IDLE_TICKS))
        elif self.state == Activity.DRIFT:
            self.step_drift(scene)
        elif self.state == Activity.DRIFT_CROSS_EDGE:
            self.step_drift_crossing(scene)
        elif self.state == Activity.MEDITATE:
            self.step_meditation(scene)
        elif self.state in (Activity.ROAM, Activity.CROSS_EDGE):
            if scene.arrived or self.state_ticks > self.duration:
                if self.state == Activity.CROSS_EDGE:
                    self.cross_cooldown = self.CROSS_EDGE_COOLDOWN
                if scene.arrived:
                    self.edge = self.destination_edge
                scene._move_to(scene.body.chunks[0].position)
                self.enter(Activity.IDLE, self.random.randint(*self.IDLE_TICKS))
        elif (self.state == Activity.NOTICE and self.state_ticks >= self.duration
              and (self.mode == 'recall' or scene.observed_pearl.settled)):
            point = self.approach_point(scene) if self.mode in ('approach', 'orbit') else None
            if point is not None:
                if self.drift_active:
                    self.drift_move_to(scene, point, observing=True)
                else:
                    scene._move_to(point, speed=self.travel_speed(scene, Activity.APPROACH))
                self.enter(Activity.APPROACH, self.movement_budget(scene))
            else:
                self.mode = 'recall'
                scene.observed_pearl.move_to(self.recall_point(scene))
                self.enter(Activity.RECALL, self.movement_budget(scene))
        elif self.state in (Activity.APPROACH, Activity.RECALL):
            if scene.arrived and scene.observed_pearl.settled:
                if self.mode != 'orbit' or not self.start_orbit(scene):
                    self.enter(Activity.OBSERVE, self.random.randint(*self.OBSERVE_TICKS))
            elif self.state_ticks > self.duration:
                scene._move_to(scene.body.chunks[0].position)
                scene.observed_pearl.return_home()
                self.enter(Activity.RETURN)
                scene.eyes.end_observation()
        elif self.state == Activity.ORBIT:
            if scene.arrived:
                self.enter(Activity.OBSERVE, self.random.randint(*self.OBSERVE_TICKS))
            elif self.state_ticks > self.duration:
                scene._move_to(scene.body.chunks[0].position)
                self.enter(Activity.OBSERVE, self.random.randint(*self.OBSERVE_TICKS))
        elif self.state == Activity.OBSERVE and self.state_ticks >= self.duration:
            scene.observed_pearl.return_home()
            self.enter(Activity.RETURN)
            scene.eyes.end_observation()
        elif (self.state == Activity.RETURN and scene.observation_returned and self.state_ticks >= 24
              and scene.arrived and (self.drift_active or scene.pose.settled)):
            self.completed_cycles += 1
            self.resume_or_idle(scene)
