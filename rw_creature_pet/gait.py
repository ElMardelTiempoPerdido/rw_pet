"""四足平地步态：世界坐标抓点、独立换步、抓地反馈。

参考 LizardLimb 的抓地/释放及 LizardGraphics 的 gripCounter 反馈结构。
这里的支撑弹簧与最低支撑保障是平地适配，不是原版 AI/Room 移植。
"""
from dataclasses import dataclass
from enum import Enum
from math import cos, isfinite, pi, radians, sin, sqrt

from .geometry import Vec2
from .physics import GRAVITY


class FootPhase(Enum):
    AIR = "悬空"
    STANCE = "支撑"
    SWING = "迈步"


@dataclass(slots=True)
class Foot:
    chunk_index: int
    side: int
    position: Vec2
    previous_position: Vec2
    phase: FootPhase = FootPhase.AIR
    start: Vec2 = Vec2()
    target: Vec2 = Vec2()
    swing_tick: int = 0
    swing_progress: float = 0.0
    swing_speed: float = 0.0
    grip_ticks: int = 0
    steps: int = 0


class FlatGait:
    REACH = 25.0  # 原版 LizardLimb.jointDist，当前 bodySize=1
    HEIGHT = 18.0
    LIFT = 6.0
    MAX_SPEED = 1.6  # 桌宠目标速度上限，不等同于原版 baseSpeed 驱动力。
    SLOW_INTENT = .55
    TRACK_INTENT = .9
    LIMB_SPEED = 8.0  # WhiteLizard.limbSpeed
    LIMB_QUICKNESS = .8
    TURN_TICKS = 48

    def __init__(self, body):
        self.posture = "relaxed"
        self.chest_blend = 0.0
        self.chest_rise = 0.0
        self.rest_blend = 0.0
        self.walk_blend = 0.0
        self.chest_angle = 16.0
        self.enabled = False
        self.speed = 0.0
        self.move_intent = 0.0
        self.effective_speed = 0.0
        self.blocked = False
        self.no_grip_ticks = 0
        self.facing = 1
        self.turn_target = 1
        self.turn_tick = 0
        self.turning = False
        self.turn_center = Vec2()
        self.feet = []
        for chunk_index in (0, 2):
            for side in (-1, 1):
                point = body.chunks[chunk_index].position + Vec2(side * 4, self.HEIGHT)
                self.feet.append(Foot(chunk_index, side, point, point))

    @property
    def grip_count(self):
        return sum(f.phase == FootPhase.STANCE for f in self.feet)

    @property
    def grip_factor(self):
        return .1 + .9 * self.grip_count / 4

    def set_speed(self, speed):
        if not isfinite(speed) or abs(speed) > self.MAX_SPEED:
            raise ValueError(f"步行速度必须在 {-self.MAX_SPEED}～{self.MAX_SPEED} 之间")
        self.speed = speed

    def set_chest_angle(self, angle):
        """平地前后身连线的目标仰角；上限保留前脚的抓地余量。"""
        if not isfinite(angle) or not 0 <= angle <= 22:
            raise ValueError("抬胸角度必须在 0～22 度之间")
        self.chest_angle = angle

    def _target(self, foot, body, world, lead=0.0):
        hip = body.chunks[foot.chunk_index].position
        # 左右腿在侧视平面共享前后坐标，不能用 side 制造固定长短步。
        return world.floor_projection(hip + Vec2(lead, 0))

    def _floor_reach(self, foot, body, world):
        height = world.floor_y - body.chunks[foot.chunk_index].position.y
        return sqrt(max(0.0, (self.REACH - 1) ** 2 - height ** 2))

    def _release(self, foot):
        foot.phase = FootPhase.AIR
        foot.grip_ticks = 0

    def _swing(self, foot, target):
        foot.phase = FootPhase.SWING
        foot.grip_ticks = 0
        foot.swing_tick = 0
        foot.swing_progress = 0.0
        foot.swing_speed = 0.0
        foot.start = foot.position
        foot.target = target

    def _advance_swing(self, foot, body):
        """沿离地弧线按距离追赶；帧数由步长与腿根速度共同决定。"""
        hip = body.chunks[foot.chunk_index]
        foot.swing_tick += 1
        hunt_speed = self.LIMB_SPEED + hip.velocity.length()
        foot.swing_speed += (hunt_speed - foot.swing_speed) * self.LIMB_QUICKNESS
        span = (foot.target - foot.start).length()
        lift = min(self.LIFT, span * .25)
        # 弧线切线长度把本帧路程转换为进度，不固定动画时长。
        tangent = sqrt(span ** 2 + (lift * pi * cos(pi * foot.swing_progress)) ** 2)
        foot.swing_progress = min(1.0, foot.swing_progress + foot.swing_speed / max(1.0, tangent))
        t = foot.swing_progress
        foot.position = foot.start.lerp(foot.target, t) + Vec2(0, -lift * sin(pi * t))
        if t == 1:
            foot.position = foot.target
            if (foot.position - hip.position).length() <= self.REACH:
                foot.phase = FootPhase.STANCE
                foot.grip_ticks = 1
                foot.steps += 1
            else:
                self._release(foot)

    def _turn_positions(self, body):
        t = min(1.0, self.turn_tick / self.TURN_TICKS)
        blend = t * t * (3 - 2 * t)
        angle = pi * (blend if self.turn_target == -1 else 1 - blend)
        distance = body.connections[0].distance
        # 在侧视平面抬起前身转过后身；后身维持支撑高度。
        center = self.turn_center + Vec2(0, -distance * sin(angle))
        axis = Vec2(cos(angle), -sin(angle)) * distance
        return (center + axis, center, center - axis)

    def update(self, body, world):
        """在身体积分前更新脚；支撑点固定，只有迈步时移动。"""
        self.blocked = ((self.speed > 0 and max(c.position.x for c in body.chunks) > world.width - 32)
                        or (self.speed < 0 and min(c.position.x for c in body.chunks) < 32))
        desired = 1 if self.speed > 0 else -1 if self.speed < 0 else self.facing
        needs_turn = desired != self.facing
        if not self.enabled:
            self.turning = False
            # 关闭支撑后保留实际身体朝向；再开启时可继续转到指令方向。
            self.facing = 1 if body.chunks[0].position.x >= body.chunks[2].position.x else -1
        can_move = self.enabled and not self.blocked and not needs_turn and not self.turning
        desired_intent = abs(self.speed) / self.MAX_SPEED if can_move else 0.0
        self.move_intent += (desired_intent - self.move_intent) * .1
        if not desired_intent and self.move_intent < 1e-6:
            self.move_intent = 0.0
        # 停止或待转立即撤去推进；剩余速度通过身体阻尼收敛。
        self.effective_speed = (desired * self.MAX_SPEED * self.move_intent
                                if can_move and self.speed else 0.0)
        for foot in self.feet:
            foot.previous_position = foot.position
            hip = body.chunks[foot.chunk_index].position
            if not self.enabled:
                self._release(foot)
            if foot.phase == FootPhase.STANCE:
                if (foot.position - hip).length() > self.REACH:
                    self._release(foot)
                else:
                    foot.grip_ticks += 1
            if foot.phase == FootPhase.AIR:
                target = self._target(foot, body, world)
                if self.enabled and (target - hip).length() <= self.REACH - 1:
                    foot.position = target
                    foot.phase = FootPhase.STANCE
                    foot.grip_ticks = 1
                else:
                    foot.position = hip + Vec2(foot.side * 4, self.HEIGHT)
            elif foot.phase == FootPhase.SWING:
                self._advance_swing(foot, body)

        if (self.enabled and needs_turn and not self.turning and self.grip_count >= 2
                and not any(f.phase == FootPhase.SWING for f in self.feet)
                and max(abs(c.velocity.x) for c in body.chunks) < 0.08):
            self.turning = True
            self.turn_target = desired
            self.turn_tick = 0
            self.turn_center = Vec2(body.chunks[1].position.x, world.floor_y - self.HEIGHT)

        if self.turning:
            if self.grip_count:
                self.turn_tick = min(self.TURN_TICKS, self.turn_tick + 1)
            # 转身时逐只挪脚；仍在够得到的范围内的支撑足保持世界位置。
            if not any(f.phase == FootPhase.SWING for f in self.feet) and self.grip_count >= 2:
                candidates = [f for f in self.feet if f.phase == FootPhase.STANCE]
                foot = max(candidates, key=lambda f: abs(body.chunks[f.chunk_index].position.x - f.position.x))
                target = self._target(foot, body, world)
                if abs(target.x - foot.position.x) > 4:
                    self._swing(foot, self._target(foot, body, world,
                                body.chunks[foot.chunk_index].velocity.x * 4))
            targets = self._turn_positions(body)
            if (self.turn_tick == self.TURN_TICKS and self.grip_count >= 2
                    and max((c.position - p).length() for c, p in zip(body.chunks, targets)) < 0.5
                    and max(c.velocity.length() for c in body.chunks) < 0.15):
                self.facing = self.turn_target
                self.turning = False
        elif self.enabled and self.effective_speed and self.grip_count > 2:
            # 每条腿按自身伸展决定是否换步；每 tick 至多释放一足，保留至少两足。
            direction = 1 if self.effective_speed > 0 else -1
            candidates = []
            for foot in self.feet:
                if foot.phase != FootPhase.STANCE or foot.grip_ticks <= 1:
                    continue
                hip = body.chunks[foot.chunk_index]
                reach = self._floor_reach(foot, body, world)
                lag = (hip.position.x - foot.position.x) * direction
                # 接近伸展极限再换步；为逐足调度及身体惯性预留数帧余量。
                reserve = max(2.0, max(abs(hip.velocity.x), abs(self.effective_speed)) * 7)
                urgency = lag - max(0.0, reach - reserve)
                if urgency >= 0:
                    candidates.append((urgency, foot, reach))
            if candidates:
                _, foot, reach = max(candidates, key=lambda item: item[0])
                self._swing(foot, self._target(foot, body, world, direction * reach * .9))
        elif self.enabled and not self.turning and (not self.speed or self.blocked) and self.grip_count > 2:
            # 大步停下后仅按需收脚，为站立及后续抬胸留出腿长；不是周期性换步。
            # 先恢复前足余量，避免抬胸过程中由超长释放造成脚突然重置。
            candidates = [(abs(body.chunks[f.chunk_index].position.x-f.position.x), f)
                          for f in self.feet if f.phase == FootPhase.STANCE and f.grip_ticks > 1]
            candidates = [(distance, f) for distance, f in candidates if distance > 8]
            if candidates:
                _, foot = max(candidates, key=lambda item: (item[1].chunk_index == 0, item[0]))
                self._swing(foot, self._target(foot, body, world))
        # 使用本帧换步后的支撑反馈，承重仍由至少两足保障。
        self.effective_speed *= self.grip_factor
        self.no_grip_ticks = self.no_grip_ticks + 1 if not self.grip_count else 0

    def drive(self, body):
        """抓地提供支撑和切向牵引；悬空时只由身体求解器处理重力。"""
        resting = (self.enabled and self.grip_count >= 2 and not self.turning
                   and abs(self.effective_speed) < .01)
        desired = 1.0 if self.posture == 'raised' and resting else 0.0
        self.chest_blend += (desired-self.chest_blend)*.04
        self.chest_rise += (sin(radians(self.chest_angle))*desired-self.chest_rise)*.04
        desired_rest = 1.0 if self.posture in ('low', 'raised') and resting else 0.0
        self.rest_blend += (desired_rest-self.rest_blend)*.08
        walking = self.enabled and abs(self.effective_speed) >= .01 and not self.turning
        self.walk_blend += ((1.0 if walking else 0.0)-self.walk_blend)*.1
        if not self.enabled or not self.grip_count:
            return
        if self.turning:
            # 仍通过速度反馈和原有约束求解，不直接改位置或交换头尾身份。
            for chunk, target in zip(body.chunks, self._turn_positions(body)):
                acceleration = (target - chunk.position) * 0.22 - chunk.velocity * 0.65
                chunk.velocity = chunk.velocity + Vec2(
                    max(-2.5, min(2.5, acceleration.x)),
                    max(-3.5, min(2.5, acceleration.y - GRAVITY)))
            return
        supports = [f for f in self.feet if f.phase == FootPhase.STANCE]
        # 支撑腿倾斜时身体略降低，随真实抓点产生起伏，不给身体播放正弦动画。
        support_y = sum(f.position.y - sqrt(max(100.0, self.HEIGHT ** 2
                        - 0.8 * (body.chunks[f.chunk_index].position.x - f.position.x) ** 2))
                        for f in supports) / len(supports)
        strength = min(1.0, len(supports) / 2)
        floor_y = sum(f.position.y for f in supports) / len(supports)
        # 低伏留 1.5 单位腹部间隙；抬胸从低伏后身支撑出发。
        # 中间质点沿同一倾角分配高度，避免旧版三段固定偏移形成腹部折角。
        rear_y = floor_y - max(c.radius for c in body.chunks) - 1.5
        distances = [body.connections[i].distance for i in range(2)]
        rise = self.chest_rise
        extension = sum(abs(body.chunks[f.chunk_index].position.x-f.position.x)
                        for f in supports)/len(supports)
        clearance = max(0.0, 1.2-(4-len(supports))*.45-extension*.08)
        for index, chunk in enumerate(body.chunks):
            target_y = support_y + (rear_y - support_y) * self.rest_blend
            target_y -= sum(distances[index:]) * rise
            # 行走时腹部低伏；抓地少、脚落后较多时可更贴近地面。
            crawl_y = floor_y-chunk.radius-clearance-(2.5, 0., .5)[index]
            target_y += (crawl_y-target_y)*self.walk_blend
            # 两只支撑脚足以承重；沿身体传递支撑，避免中间质点拖地。
            ax = (self.effective_speed - chunk.velocity.x) * 0.22 * strength
            ay = (-GRAVITY + (target_y - chunk.position.y) * 0.12
                  - chunk.velocity.y * 0.5) * strength
            chunk.velocity = chunk.velocity + Vec2(ax, max(-2.5, min(2.5, ay)))

    def validate_contacts(self, body):
        # 身体受到外力后及时释放够不到的抓点，画面与下一 tick 的反馈一致。
        for foot in self.feet:
            if foot.phase == FootPhase.STANCE and (foot.position - body.chunks[foot.chunk_index].position).length() > self.REACH:
                self._release(foot)
