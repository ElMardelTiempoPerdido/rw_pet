"""近距离持续躲避：脚端支点、滞后侧倾、离开宽限和不耐烦后的短途移动"""
from math import exp, radians, sin, cos
from random import Random

from ...shared.geometry import Bounds, Vec2
from .controller import Activity
from ..motion.navigation import approach


class OracleMouseAvoidance:
    DELAY = (1., 6.)
    PROBABILITY = .95
    DISTANCE = (18., 32.)
    SPEED = (1.8, 3.6)  # 每段独立抽取导航速度上限，单位为逻辑像素/tick
    LEAN_MOVE_DISTANCE = (16., 80.)
    LEAN_MOVE_PROBABILITY = .95
    LEAN_MOVE_ANGLE = 14.  # 倾角明显改变才产生一次伴随移动机会
    LEAN_MOVE_POINTER_DISTANCE = 5.  # 排除人偶自身平移造成的倾角变化
    MOVE_ANGLE_JITTER = 22.  # 远离鼠标方向两侧的随机偏角，单位为度
    MATRIX_AVOID_RADIUS = 32.  # 鼠标躲避的独立间距，不复用常规自主移动的矩阵避让半径
    MOVE_DISTANCE_FACTORS = (1., .55, .25)  # 每档最多尝试三个方向，共九个候选
    LEAN = (30., 60.)
    LEAN_SAMPLE_POWER = 2.  # 1 为均匀分布，大于 1 时更偏向小倾角
    LEAN_SPEED = 90  # 度/秒，身体另有平滑转速和加速度限制
    ENTER_DISTANCE = 55.  # 距简化身体轮廓的逻辑像素
    EXIT_DISTANCE = 85.
    LEAVE_GRACE = 1.5
    POINTER_LAG = .35
    RETRY = (.1, .3)
    IMPATIENCE_TIME = (1., 1.5)
    MOVE_PROBABILITY = .85
    MOVE_TIMEOUT = 8.
    PIVOT_LENGTH = 17.5  # 上身质点到双脚中间的虚拟支点，不读取摆动的衣摆
    HEAD_LENGTH = 14.
    BODY_RADIUS = 7.

    def __init__(self):
        self.random = Random(8429)
        self.elapsed = 0.
        self.delay = None
        self.engaged = self.leaning = self.drifting = False
        self.lean = self.lean_goal = self.amplitude = 0.
        self.filtered_pointer = self.gaze_target = None
        self.away_elapsed = self.impatience = self.retry_seconds = 0.
        self.impatience_threshold = 3.
        self.lean_move_angle = self.lean_move_pointer = None
        self.pivot_axis = None
        self.pivot_weight = 0.
        self.offset = self.offset_velocity = Vec2()
        self.move_target = self.move_route = None
        self.move_elapsed = 0.

    @property
    def moving(self):
        return self.move_target is not None

    @property
    def busy(self):
        return self.engaged or self.moving or self.lean != 0. or self.pivot_weight > 0. or self.offset != Vec2()

    def neutral_position(self, scene):
        """导航基准不包含绕脚端旋转产生的临时位移"""
        return scene.body.chunks[0].position-self.offset

    def neutral_velocity(self, scene):
        return scene.body.chunks[0].velocity-self.offset_velocity

    @classmethod
    def clearance(cls, pointer, upper, axis):
        if pointer is None:
            return float('inf')
        relative = pointer-upper
        along = max(-cls.PIVOT_LENGTH, min(cls.HEAD_LENGTH, relative.x*axis.x+relative.y*axis.y))
        return max(0., (relative-axis*along).length()-cls.BODY_RADIUS)

    def owns_move(self, scene):
        return (self.moving and scene.target == self.move_target
                and (scene.navigator is None or scene.navigator.route is self.move_route))

    def stop_move(self, scene, *, brake=True):
        if self.owns_move(scene):
            if brake and not scene.drag.controlling:
                scene._move_to(self.neutral_position(scene), speed=scene.travel_speed)
            scene.behavior.state_ticks = 0
            if self.drifting and scene.behavior.state == Activity.DRIFT:
                behavior = scene.behavior
                # 从躲开后的位置继续本轮漫游，不接回被打断的旧路线
                behavior.drift_next_move = max(behavior.drift_next_move, behavior.drift_ticks+
                                               behavior.timing_random.randint(*behavior.DRIFT_RESUME_TICKS))
                behavior.drift_join_checked = True
                behavior.drift_pause_ticks = 0
        self.move_target = self.move_route = None
        self.move_elapsed = 0.

    def cancel(self, scene, *, immediate=False):
        self.stop_move(scene)
        self.engaged = self.leaning = self.drifting = False
        self.lean_goal = self.elapsed = self.impatience = self.away_elapsed = 0.
        self.delay = self.filtered_pointer = self.gaze_target = None
        self.lean_move_angle = self.lean_move_pointer = None
        if immediate or scene.drag.controlling:
            self.lean = self.pivot_weight = 0.
            self.pivot_axis = None
            self.offset = self.offset_velocity = Vec2()

    def start_move(self, scene, pointer, *, small=False):
        behavior = scene.behavior
        start = self.neutral_position(scene)
        drifting = behavior.drift_active
        if pointer is None or self.moving or not behavior.movement_enabled:
            return False
        if drifting:
            if (behavior.state != Activity.DRIFT or behavior.drift_recovering
                    or behavior.drift_ticks >= behavior.drift_duration):
                return False
        elif (not behavior.enabled or behavior.state != Activity.IDLE or (start-scene.target).length() > 1.
              or (scene.navigator is not None and not scene.navigator.done)):
            return False
        # 转动期间也能挪开，不要求身体先回正或所有旋转速度归零
        away = scene.body.chunks[0].position-pointer
        if away.length() < 1e-6:
            return False
        away = away*(1/away.length())
        distance_range = self.LEAN_MOVE_DISTANCE if small else self.DISTANCE
        destination = self.move_destination(scene, start, away, distance_range, small=small)
        if destination is None:
            return False
        target, box = destination
        velocity = self.neutral_velocity(scene) if drifting else Vec2()
        route = (scene.navigator.planner.round_polyline([start, target], velocity, box=box)
                 if scene.navigator else None)
        # 整段沿用同一次速度抽样，起步与刹车继续由导航平滑处理
        scene._move_to(target, route=route, speed=self.random.uniform(*self.SPEED))
        self.move_target = scene.target
        self.move_route = scene.navigator.route if scene.navigator else None
        self.move_elapsed = 0.
        self.impatience *= .25
        return True

    def move_destination(self, scene, start, away, distance_range, *, small):
        """在本次机会内有限次选点，不增加触发抽签或移动中的重规划"""
        angle = radians(self.random.uniform(-self.MOVE_ANGLE_JITTER, self.MOVE_ANGLE_JITTER))
        region = scene.navigator.region if scene.navigator else scene.body_region
        behavior = scene.behavior
        candidates = (region.edge_boxes[behavior.drift_edge],) if behavior.drift_active else region.boxes
        boxes = [box for box in candidates if box.contains(start) and box.contains(start+self.offset)]
        if not boxes:
            return None
        distance = self.random.uniform(*distance_range)
        minimum = 3. if small else 6.
        side_angle = radians(self.MOVE_ANGLE_JITTER)*(1. if angle < 0 else -1.)
        angles = (angle, side_angle, -side_angle)
        for factor in self.MOVE_DISTANCE_FACTORS:
            for candidate_angle in angles:
                direction = Vec2(away.x*cos(candidate_angle)-away.y*sin(candidate_angle),
                                 away.x*sin(candidate_angle)+away.y*cos(candidate_angle))
                far = start+direction*distance_range[1]
                box = min(boxes, key=lambda b: (b.clamp(far)-far).length())
                # 基准路径和侧倾后的身体同时留在同一走廊内，给刹车留出余量
                left, right = max(box.left, box.left-self.offset.x), min(box.right, box.right-self.offset.x)
                top, bottom = max(box.top, box.top-self.offset.y), min(box.bottom, box.bottom-self.offset.y)
                if right-left < 4 or bottom-top < 4:
                    continue
                inset = Bounds(left+2, top+2, right-2, bottom-2)
                target = scene.project_target(inset.clamp(start+direction*max(minimum, distance*factor)))
                delta = target-start
                if (inset.contains(target) and minimum <= delta.length() <= distance_range[1]+1e-6
                        and delta.x*away.x+delta.y*away.y > 0
                        and behavior.matrix_clear(scene, target+self.offset, radius=self.MATRIX_AVOID_RADIUS)):
                    return target, box
        return None

    def begin(self, scene, pointer):
        self.engaged = True
        self.away_elapsed = self.impatience = 0.
        self.filtered_pointer = self.gaze_target = pointer
        self.drifting = scene.behavior.drift_active
        if self.drifting:
            self.lean = self.lean_goal = self.amplitude = 0.
        else:
            low, high = self.LEAN
            self.amplitude = low+(high-low)*self.random.random()**self.LEAN_SAMPLE_POWER
        self.impatience_threshold = self.random.uniform(*self.IMPATIENCE_TIME)
        self.retry_seconds = 0.
        self.lean_move_angle = self.lean_move_pointer = None
        self.pivot_axis = None if self.drifting else scene.body.direction
        self.pivot_weight = 0. if self.drifting else 1.
        relative = pointer-scene.body.chunks[0].position
        self.leaning = (not self.drifting and
                       relative.x*self.pivot_axis.x+relative.y*self.pivot_axis.y >= -6.)
        if not self.leaning:
            self.start_move(scene, pointer)  # 漫游及普通下半身分支直接尝试短距离漂开
            self.retry_seconds = self.random.uniform(*self.RETRY)

    def step_lean_move(self, scene, pointer, *, near):
        """把连续改倾角分成有限的伴随机会，不因静止抖动逐帧抽签或补播旧动作"""
        if not self.leaning:
            return
        if not near or self.moving:
            self.lean_move_angle, self.lean_move_pointer = self.lean_goal, self.filtered_pointer
            return
        changed = (abs(self.lean_goal) >= self.LEAN_MOVE_ANGLE if self.lean_move_angle is None else
                   abs(self.lean_goal-self.lean_move_angle) >= self.LEAN_MOVE_ANGLE
                   and (self.filtered_pointer-self.lean_move_pointer).length() >= self.LEAN_MOVE_POINTER_DISTANCE)
        if not changed:
            return
        self.lean_move_angle, self.lean_move_pointer = self.lean_goal, self.filtered_pointer
        if self.retry_seconds > 0.:
            return
        self.retry_seconds = self.random.uniform(*self.RETRY)
        if self.random.random() < self.LEAN_MOVE_PROBABILITY:
            self.start_move(scene, pointer, small=True)

    def safe_lean(self, scene, desired):
        """仅按空间和臂长缩小侧倾，不套用普通姿态的 ±25° 限制"""
        if self.pivot_axis is None:
            return desired
        origin = self.neutral_position(scene)
        guide = scene.navigator.guide if scene.navigator else scene.target
        region = scene.navigator.region if scene.navigator else scene.world.corridor(scene.anchor.side)

        def fits(lean):
            angle = radians(scene.tilt_degrees+scene.pose.base_angle+lean)
            offset = (Vec2(sin(angle), -cos(angle))-self.pivot_axis)*self.PIVOT_LENGTH
            return all(region.contains(p+offset) and (p+offset-scene.base).length() <= scene.arm.maximum_reach
                       for p in (origin, guide))

        if fits(desired):
            return desired
        if not fits(0.):
            return 0.
        low, high = 0., 1.
        for _ in range(9):
            mid = (low+high)*.5
            if fits(desired*mid):
                low = mid
            else:
                high = mid
        return desired*low

    def advance_pivot(self, axis):
        """随真实身体轴更新位置补偿，旋转不再把脚端反向扫向鼠标"""
        offset = ((axis-self.pivot_axis)*(self.PIVOT_LENGTH*self.pivot_weight)
                  if self.pivot_axis is not None else Vec2())
        self.offset_velocity = offset-self.offset
        self.offset = offset
        return self.offset_velocity

    def relax(self, dt):
        self.lean = approach(self.lean, self.lean_goal, self.LEAN_SPEED*dt)
        if not self.engaged:
            self.pivot_weight = approach(self.pivot_weight, 0., dt*.5)

    def step(self, scene, *, active, pointer, enabled):
        dt = 1/scene.TICK_RATE
        behavior = scene.behavior
        drifting = behavior.drift_active
        if (not enabled or scene.drag.controlling or
                (drifting and (behavior.state != Activity.DRIFT or behavior.drift_recovering
                               or behavior.drift_ticks >= behavior.drift_duration))):
            self.cancel(scene, immediate=drifting)
            self.relax(dt)
            return
        if self.engaged and self.drifting != drifting:
            self.cancel(scene, immediate=drifting)
            self.relax(dt)
            return
        if self.moving:
            self.move_elapsed += dt
            if not self.owns_move(scene):
                self.cancel(scene)  # 不覆盖手动目标或其他行为新建立的路线
            elif (not behavior.movement_enabled or (not drifting and not behavior.enabled)
                  or behavior.state != (Activity.DRIFT if drifting else Activity.IDLE)
                  or self.move_elapsed >= self.MOVE_TIMEOUT):
                self.stop_move(scene)
                self.retry_seconds = self.random.uniform(*self.RETRY)
            elif ((scene.navigator is None or scene.navigator.done)
                  and (self.neutral_position(scene)-scene.target).length() < (2. if drifting else .3)
                  and (drifting or self.neutral_velocity(scene).length() < .03)):
                self.stop_move(scene, brake=False)
                self.retry_seconds = self.random.uniform(*self.RETRY)

        upper, axis = scene.body.chunks[0].position, scene.body.direction
        distance = self.clearance(pointer, upper, axis)
        # 自定义注视半径很小时，躲避进入范围也随之缩小
        enter = min(self.ENTER_DISTANCE, scene.mouse_reaction.config.hover_radius*.5)
        if not self.engaged:
            if self.busy:  # 正在回正时不重新建立支点
                self.relax(dt)
                return
            if not active or pointer is None or distance > enter:
                self.elapsed = 0.
                self.delay = None
                return
            if self.delay is None:
                self.delay = self.random.uniform(*self.DELAY)
            self.elapsed += dt
            if self.elapsed+1e-9 < self.delay:
                return
            self.elapsed = 0.
            self.delay = self.random.uniform(*self.RETRY)
            if self.random.random() >= self.PROBABILITY:
                return
            self.begin(scene, pointer)

        # 既看当前身体，也看回正后的身体，防止自己侧倾躲远后立刻触发回正
        neutral_distance = self.clearance(pointer, self.neutral_position(scene), self.pivot_axis or axis)
        outside = min(distance, neutral_distance) > max(enter+20., self.EXIT_DISTANCE)
        self.away_elapsed = self.away_elapsed+dt if outside else 0.
        if self.away_elapsed >= self.LEAVE_GRACE:
            self.cancel(scene)
            self.relax(dt)
            return
        if pointer is not None:
            self.gaze_target = pointer
            self.filtered_pointer = self.filtered_pointer.lerp(pointer, 1-exp(-dt/self.POINTER_LAG))
            if (self.filtered_pointer-pointer).length() < .002:
                self.filtered_pointer = pointer
        if self.leaning:
            away = self.neutral_position(scene)-self.filtered_pointer
            side = Vec2(-self.pivot_axis.y, self.pivot_axis.x)
            across = away.x*side.x+away.y*side.y
            desired = self.amplitude*max(-1., min(1., across/24.))
            self.lean_goal = self.safe_lean(scene, desired)
        self.relax(dt)

        self.retry_seconds = max(0., self.retry_seconds-dt)
        self.step_lean_move(scene, pointer, near=distance <= enter)
        if distance <= enter:
            self.impatience = min(self.impatience_threshold*1.5,
                                  self.impatience+dt*(1.+.5*(1.-distance/max(1., enter))))
        else:
            self.impatience = max(0., self.impatience-dt*.5)
        if (distance <= enter and self.impatience >= self.impatience_threshold
                and not self.moving and self.retry_seconds == 0.):
            self.retry_seconds = self.random.uniform(*self.RETRY)
            if self.random.random() < self.MOVE_PROBABILITY:
                self.start_move(scene, pointer)
