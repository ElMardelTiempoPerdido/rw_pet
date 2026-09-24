"""背景抓附与前身引导；中后身通过实际运动、连接和阻尼跟随。"""
from math import atan2, cos, isfinite, pi, sin, sqrt
from .appearance import unit
from .gait import Foot, FootPhase
from .geometry import Vec2


class BackgroundGrip:
    REACH = 25.0
    MAX_SPEED = 1.6  # 导航参考点的速度上限；不是原版 baseSpeed 驱动力。
    SLOW_INTENT = .55
    TRACK_INTENT = .9
    TURN_RATE = .045
    LIMB_SPEED = 8.0
    LIMB_QUICKNESS = .8

    def __init__(self, body):
        self.enabled = False
        self.feet = []
        self.targets = [c.position for c in body.chunks]
        self.pose_targets = self.targets.copy()
        self.look_bend = 0.0
        self.direction = Vec2()
        self.move_intent = 0.0
        self.foot_velocities = [Vec2() for _ in range(4)]
        self.blocked = False
        self.goal = None
        self.arrived = False
        self.continuous = False
        self.has_moved = False
        self.was_moving = False
        self.heading = atan2(body.chunks[0].position.y - body.chunks[2].position.y,
                             body.chunks[0].position.x - body.chunks[2].position.x)
        self.rear_heading = self.heading
        for index in (0, 2):
            for side in (-1, 1):
                point = body.chunks[index].position
                self.feet.append(Foot(index, side, point, point))

    @property
    def grip_count(self):
        return sum(f.phase == FootPhase.STANCE for f in self.feet)

    @property
    def attached(self):
        return self.enabled and self.grip_count >= 2

    def set_enabled(self, enabled, body, world):
        self.enabled = enabled
        self.move_intent = 0.0
        self.foot_velocities = [Vec2() for _ in range(4)]
        self.targets = [c.position for c in body.chunks]
        self.pose_targets = self.targets.copy()
        self.look_bend = 0.0
        self.direction = Vec2()
        self.goal = None
        self.arrived = False
        self.continuous = False
        self.has_moved = False
        self.was_moving = False
        self.heading = atan2(body.chunks[0].position.y - body.chunks[2].position.y,
                             body.chunks[0].position.x - body.chunks[2].position.x)
        self.rear_heading = self.heading
        self.blocked = False
        axis = unit(body.chunks[0].position - body.chunks[2].position)
        normal = Vec2(-axis.y, axis.x)
        for foot in self.feet:
            foot.phase = FootPhase.AIR
        for foot in self.feet:
            hip = body.chunks[foot.chunk_index].position
            goal = hip + normal * (foot.side * 14) + axis * (4 if foot.chunk_index == 0 else -4)
            point = self._find_grip(foot, hip, goal, normal, world, self.REACH-4) if enabled else None
            foot.phase = FootPhase.STANCE if point is not None else FootPhase.AIR
            foot.grip_ticks = 1 if point is not None else 0
            foot.position = point if point is not None else world.background_position(goal, 3)
            foot.previous_position = foot.position

    def _find_grip(self, foot, hip, desired, normal, world, reach):
        # 已抓住的点和正在追赶的点都占位；不让后启动的脚抢同一个抓点。
        occupied = [other.target if other.phase == FootPhase.SWING else other.position
                    for other in self.feet if other is not foot and other.phase != FootPhase.AIR]
        candidates = []
        for point in world.background_candidates(hip, reach):
            offset = point-hip
            lateral = (offset.x*normal.x + offset.y*normal.y)*foot.side
            if lateral < 2 or any((point-other).length() < 7.5 for other in occupied):
                continue
            if foot.phase == FootPhase.STANCE and (point-foot.position).length() <= 2:
                continue
            candidates.append(point)
        return min(candidates, key=lambda point: (point-desired).length(), default=None)

    def set_direction(self, direction):
        if not isfinite(direction.x) or not isfinite(direction.y) or not isfinite(direction.length()):
            raise ValueError('移动方向必须为有限数值')
        self.direction = unit(direction) if direction.length() else Vec2()
        self.goal = None
        self.arrived = False
        self.continuous = self.has_moved and bool(direction.length())
        self.blocked = False

    def set_goal(self, point, body, world):
        if not isfinite(point.x) or not isfinite(point.y):
            raise ValueError('目标点必须为有限坐标')
        margin = body.connections[0].distance + max(c.radius for c in body.chunks) + 12
        self.goal = Vec2(max(margin, min(world.width - margin, point.x)),
                         max(margin, min(world.floor_y - margin, point.y)))
        self.arrived = False
        self.continuous = True
        self.blocked = False

    def update(self, body, world, look_target=None):
        axis = unit(body.chunks[0].position - body.chunks[2].position)
        normal = Vec2(-axis.y, axis.x)
        for index, foot in enumerate(self.feet):
            foot.previous_position = foot.position
            hip = body.chunks[foot.chunk_index].position
            if not self.enabled or (foot.phase == FootPhase.STANCE and (foot.position - hip).length() > self.REACH):
                foot.phase = FootPhase.AIR
                foot.grip_ticks = 0
            if foot.phase == FootPhase.STANCE:
                foot.grip_ticks += 1
            elif foot.phase == FootPhase.SWING:
                foot.swing_tick += 1
                delta = foot.target - foot.position
                hunt_speed = self.LIMB_SPEED + body.chunks[foot.chunk_index].velocity.length()
                velocity = self.foot_velocities[index].lerp(unit(delta) * hunt_speed, self.LIMB_QUICKNESS)
                reached = delta.length() <= hunt_speed
                if reached:
                    foot.position = foot.target
                else:
                    foot.position = foot.position + velocity
                self.foot_velocities[index] = velocity
                if reached:
                    point = world.background_grip(hip, foot.target, self.REACH)
                    if point is not None:
                        foot.position = point
                        foot.phase = FootPhase.STANCE
                        foot.grip_ticks = 1
                        foot.steps += 1
                    else:
                        foot.phase = FootPhase.AIR
            else:
                goal = world.background_position(hip + normal * (foot.side * 14), 3)
                foot.position = goal

        remaining = None
        was_arrived = self.arrived
        if self.goal is not None:
            delta = self.goal - self.targets[1]
            remaining = delta.length()
            self.arrived = self.arrived or ((self.goal - body.chunks[1].position).length() < .6
                                           and max(c.velocity.length() for c in body.chunks) < .03)
            # 导航点先到达时仍让身体跟进；不能提前切回整身定姿而拉直/卡住后身。
            self.direction = Vec2() if self.arrived else (unit(delta) if remaining > .3
                                                         else Vec2(cos(self.heading), sin(self.heading)))
        moving = self.direction.length() > 0 and self.attached
        desired_intent = (self.TRACK_INTENT if self.goal is not None else self.SLOW_INTENT) if moving else 0.0
        self.move_intent += (desired_intent - self.move_intent) * .1
        if not moving and self.move_intent < 1e-6:
            self.move_intent = 0.0
        if moving:
            angle = atan2(self.direction.y, self.direction.x)
            difference = (angle - self.heading + pi) % (2 * pi) - pi
            # 保持抓地的有限角速度；后身滞后于前身方向，避免整身瞬间翻转。
            turning_step = max(-self.TURN_RATE, min(self.TURN_RATE, difference))
            heading = self.heading + turning_step
            forward = Vec2(cos(heading), sin(heading))
            grip_factor = .1 + .9 * self.grip_count / 4
            speed = self.MAX_SPEED * self.move_intent * grip_factor
            if self.continuous:
                speed *= max(0, cos(difference)) ** 2
                if remaining is not None:
                    speed *= min(1, remaining / 12)
                    if remaining < 12 and abs(difference) > .25:
                        speed = 0
                step = forward * speed
            else:
                step = self.direction * (speed if abs(difference) < .2 else 0)
            center = self.targets[1] + step
            # 抓点限制身体时，导航参考不能持续跑远并积累过大的牵引力。
            lead = center-body.chunks[1].position
            if lead.length() > 6:
                center = body.chunks[1].position + unit(lead)*6
            length = body.connections[0].distance
            targets, rear_heading = self._navigation_targets(center, heading, body)
            # 留出脚部和头部的安全余量，整条指令停步，不沿边界自动滑行。
            margin = length + max(c.radius for c in body.chunks) + 12
            self.blocked = ((step.x < 0 and center.x < margin) or
                            (step.x > 0 and center.x > world.width - margin) or
                            (step.y < 0 and center.y < margin) or
                            (step.y > 0 and center.y > world.floor_y - margin))
            if not self.blocked:
                self.heading = heading
                self.rear_heading = rear_heading
                self.targets = targets
                if step.length() > .01:
                    self.has_moved = True
            elif self.continuous:
                # 边界禁止越界平移，但允许原地转向以重新朝向可达区域。
                center = self.targets[1]
                self.heading = heading
                self.targets, self.rear_heading = self._navigation_targets(center, heading, body)

        # 停止后仍完成已经迈出的脚；静止时不再启动周期性迈步。
        if moving and (not self.blocked or self.continuous) and self.grip_count > 2:
            candidates = []
            for i, foot in enumerate(self.feet):
                if foot.phase != FootPhase.STANCE or foot.grip_ticks <= 1:
                    continue
                hip = body.chunks[foot.chunk_index].position
                local = (hip-body.chunks[1].position if foot.chunk_index == 0
                         else body.chunks[1].position-hip)
                # 原版先混合该身体段方向与移动目标方向，再确定每条腿的落点。
                forward = unit(unit(local).lerp(self.direction, .4))
                normal = Vec2(-forward.y, forward.x)
                local_axis = unit(local)
                aligned = local_axis.x*self.direction.x + local_axis.y*self.direction.y > cos(.2)
                if aligned:
                    offset = foot.position-hip
                    lateral = offset.x*normal.x + offset.y*normal.y
                    lag = -(offset.x*forward.x + offset.y*forward.y)
                    # 抓点接近腿长极限再释放。为逐足调度预留追赶期间的身体位移。
                    reach = sqrt(max(0.0, (self.REACH-1)**2 - lateral**2))
                    reserve = max(2.0, body.chunks[foot.chunk_index].velocity.length()*5)
                    urgency = lag-max(0.0, reach-reserve)
                    # 原版 a + Perpendicular(a) * ±1.2，再限于 FindGrip 的 24 半径。
                    # 使用身体局部坐标，避免朝上/朝下或前后腿出现固定短步。
                    desired = hip + unit(forward + normal*(foot.side*1.2))*(self.REACH-1.5)
                else:
                    # 转弯时缩短换抓点距离，给髋部旋转及弯曲后身留出空间。
                    desired = hip + normal*(foot.side*12) + forward*(4 if foot.chunk_index == 0 else -4)
                    urgency = (desired-foot.position).length()-5
                if urgency < 0:
                    continue
                goal = self._find_grip(foot, hip, desired, normal, world, self.REACH-1)
                if goal is not None:
                    candidates.append((urgency, i, goal))
            if candidates:
                _, i, goal = max(candidates, key=lambda item: item[0])
                foot = self.feet[i]
                foot.phase = FootPhase.SWING
                foot.grip_ticks = 0
                foot.swing_tick = 0
                self.foot_velocities[i] = Vec2()
                foot.start = foot.position
                foot.target = goal

        if self.attached and ((self.was_moving and not moving and self.goal is None)
                              or (self.arrived and not was_arrived)):
            # 只在停止事件记录一次真实骨架；不能每 tick 追着位置更新，否则会漂移。
            self.targets = [c.position for c in body.chunks]
            # 观察偏转仍是独立叠加层，避免停止时重复计入已有偏转。
            delta = self.targets[0]-self.targets[1]
            self.targets[0] = self.targets[1] + self._rotate(delta, -self.look_bend)
            axis = self.targets[0]-self.targets[1]
            rear = self.targets[1]-self.targets[2]
            self.heading = atan2(axis.y, axis.x)
            self.rear_heading = atan2(rear.y, rear.x)
        self.was_moving = moving
        self._update_observation(body, world, look_target, moving)

    @staticmethod
    def _rotate(delta, angle):
        return Vec2(delta.x*cos(angle)-delta.y*sin(angle),
                    delta.x*sin(angle)+delta.y*cos(angle))

    def _navigation_targets(self, center, heading, body):
        forward = Vec2(cos(heading), sin(heading))
        # 后身没有导航姿态目标；方向来自真实身体，仅记录用于停留/诊断。
        rear = body.chunks[1].position-body.chunks[2].position
        rear_heading = atan2(rear.y, rear.x)
        targets = [center+forward*body.connections[0].distance, center,
                   body.chunks[2].position]
        return targets, rear_heading

    def _update_observation(self, body, world, look_target, moving):
        # targets 只属于移动控制；观察偏转不能累积到路线中心和行进朝向。
        desired = 0.0
        if look_target is not None and self.attached and not moving:
            axis = unit(self.targets[0]-self.targets[1])
            delta = look_target-self.targets[0]
            if delta.length() > 1e-6:
                angle = (atan2(delta.y, delta.x)-atan2(axis.y, axis.x)+pi) % (2*pi)-pi
                desired = max(-.18, min(.18, angle*.2))
        bend = self.look_bend + (desired-self.look_bend)*.06

        def candidate(amount):
            center = self.targets[1]
            delta = self.targets[0]-center
            front = center + Vec2(delta.x*cos(amount)-delta.y*sin(amount),
                                  delta.x*sin(amount)+delta.y*cos(amount))
            return [front, center, self.targets[2]]

        # 在姿态目标层收窄弯曲，不挪动抓点，也不把质点瞬移到可行区域。
        for _ in range(10):
            posed = candidate(bend)
            safe = all(world.background_contains(p, c.radius+1) for p,c in zip(posed, body.chunks))
            safe &= all((f.position-posed[f.chunk_index]).length() < self.REACH-1
                        for f in self.feet if f.phase == FootPhase.STANCE)
            if safe or abs(bend) < 1e-6:
                break
            bend *= .5
        self.look_bend = bend
        self.pose_targets = candidate(bend)

    def drive(self, body):
        if self.attached:
            for i, (chunk, target) in enumerate(zip(body.chunks, self.pose_targets)):
                # 前身主要牵引；中身仅作弱导航位置校正，确保最终到点。
                # 后身不追逐坐标，靠连接传递运动；静止时仍保持已捕获的实际姿态。
                strength = (.30, .03, 0)[i] if self.was_moving else .15
                chunk.velocity = chunk.velocity + (target - chunk.position) * strength

    def reach_limits(self):
        """支撑抓点与摆腿已预约落点共同约束髋部；不移动脚来迁就身体。"""
        limits = []
        for foot in self.feet:
            if foot.phase == FootPhase.STANCE:
                limits.append((foot.chunk_index, foot.position, self.REACH-.05))
            elif foot.phase == FootPhase.SWING:
                limits.append((foot.chunk_index, foot.position, self.REACH-.05))
                limits.append((foot.chunk_index, foot.target, self.REACH-.05))
        return limits

    def validate_contacts(self, body):
        for foot in self.feet:
            if (foot.position - body.chunks[foot.chunk_index].position).length() > self.REACH:
                foot.phase = FootPhase.AIR
                foot.grip_ticks = 0
