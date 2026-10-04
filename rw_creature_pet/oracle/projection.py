"""拖动中的扫描投影：40 Hz 独立计时、选位和指图意图；不依赖 Qt。"""
from math import atan2, cos, pi, sin
from random import Random

from ..shared.geometry import Bounds, Vec2
from .projection_placement import ProjectionArmObstacles


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


class OracleProjection:
    DT = 1/40
    WIDTH, HEIGHT = 80., 120.
    DURATION = 330/40
    FRAME_TICKS = 15
    LIFT_DELAY = .35

    def __init__(self, seed=928):
        self.random = Random(seed)
        self.available = False  # 窗口在两张本机素材都加载成功后启用。
        self.state = 'idle'
        self.position = self.previous_position = self.target = Vec2()
        self.alpha = self.previous_alpha = self.weight = 0.
        self.elapsed_ticks = self.frame_index = self.revision = self.starts = 0
        self.cooldown = self.move_wait = self.switch_wait = 0.
        self.hand_index = self.desired_hand = 0
        self.arm_obstacles = ProjectionArmObstacles()

    @property
    def busy(self):
        return self.state != 'idle'

    @property
    def visible(self):
        return self.alpha > 0 or self.previous_alpha > 0

    def region(self, scene):
        return Bounds(self.WIDTH/2+8, self.HEIGHT/2+8,
                      scene.world.width-self.WIDTH/2-8, scene.world.height-self.HEIGHT/2-8)

    def clearance(self, center, body):
        box = Bounds(center.x-self.WIDTH/2, center.y-self.HEIGHT/2,
                     center.x+self.WIDTH/2, center.y+self.HEIGHT/2)
        return (body-box.clamp(body)).length()

    def choose_position(self, scene, obstacles=None):
        app = scene.appearance
        up, body = scene.body.direction, scene.body.chunks[0].position
        side = Vec2(-up.y, up.x)
        region, candidates = self.region(scene), []
        obstacles = obstacles or self.arm_obstacles.update(scene)
        # 常用近距离位置不够时，再向外扩大一点；不以重叠作为兜底。
        options = [(sign, degrees, self.random.uniform(105, 145))
                   for sign in (-1, 1) for degrees in (-25, 0, 25, 45)]
        options += [(sign, degrees, radius) for radius in (160, 185)
                    for sign in (-1, 1) for degrees in (-45, -20, 0, 25, 50)]
        for sign, degrees, radius in options:
            outward = side*sign
            angle = (degrees+self.random.uniform(-8, 8))*pi/180
            center = region.clamp(body+(outward*cos(angle)+up*sin(angle))*radius)
            if self.clearance(center, body) < 28 or not obstacles.clear(center, self.WIDTH, self.HEIGHT):
                continue
            nearest = min(range(2), key=lambda i: (app.hands[i].shoulder(body, up, i)-center).length())
            shoulder = app.hands[nearest].shoulder(body, up, nearest)
            ray = center-shoulder
            out = side*(-1 if nearest == 0 else 1)
            aim = atan2(ray.x*up.x+ray.y*up.y, ray.x*out.x+ray.y*out.y)
            hand = app.hands[nearest]
            angle_error = abs(aim-max(hand.SWING_MIN, min(hand.SWING_MAX, aim)))
            score = max(0., 32-self.clearance(center, body))*20+angle_error*100+max(0., radius-145)*.3
            candidates.append((score, center))
        if not candidates:
            return None
        # 同样空旷的左右两侧都可选，不固定在鼠标或人偶某一侧。
        best = min(score for score, _ in candidates)
        return self.random.choice([p for score, p in candidates if score <= best+4])

    def try_start(self, scene):
        reactions = scene.drag_reactions
        if (not self.available or self.busy or self.cooldown > 0 or not scene.drag.active
                or not reactions.active or reactions.gesturing or scene.config.projection_opacity <= 0
                or any(hand.reach_weight > .01 for hand in scene.appearance.hands)):
            return False
        if self.random.random() >= scene.config.drag_projection_probability:
            return False
        position = self.choose_position(scene)
        if position is None:
            return False
        self.position = self.previous_position = self.target = position
        self.hand_index = self.desired_hand = self.nearest_hand(scene)
        self.state = 'showing'
        self.elapsed_ticks = self.frame_index = 0
        self.alpha = self.previous_alpha = self.weight = 0.
        self.cooldown = scene.config.drag_projection_cooldown_seconds
        self.move_wait = self.random.uniform(.65, 1.6)
        self.switch_wait = 1.
        self.starts += 1
        self.revision += 1
        return True

    def nearest_hand(self, scene):
        body, up = scene.body.chunks[0].position, scene.body.direction
        return min(range(2), key=lambda i: (
            scene.appearance.hands[i].shoulder(body, up, i)-self.position).length())

    def stop(self, *, cancel=False):
        if cancel:
            self.state = 'idle'
            self.alpha = self.previous_alpha = self.weight = 0.
            self.revision += 1
        elif self.busy and self.state != 'ending':
            self.state = 'ending'
            # 画面立即撤去，连上一帧透明度一并清零，避免绘制插值产生淡出。
            # ending 只负责手臂平滑放下。
            self.alpha = self.previous_alpha = 0.
            self.revision += 1

    def inherit_cooldown(self, other):
        self.cooldown = other.cooldown
        self.random.setstate(other.random.getstate())

    def avoid_arm(self, scene):
        """机械臂本轮更新后检查；拖动中移入画面的杆件也会让投影重新选位。"""
        if self.state != 'showing':
            return
        if self.arm_obstacles.broadly_clear(scene, self.previous_position, self.position,
                                           self.target, self.WIDTH, self.HEIGHT):
            return
        obstacles = self.arm_obstacles.update(scene)
        if not obstacles.clear(self.position, self.WIDTH, self.HEIGHT) or not obstacles.clear(self.target, self.WIDTH, self.HEIGHT):
            target = self.choose_position(scene, obstacles)
            if target is None:
                self.stop()
                return
            self.target = target
        if (not obstacles.clear_path(self.previous_position, self.position, self.WIDTH, self.HEIGHT)
                or not obstacles.clear_path(self.position, self.target, self.WIDTH, self.HEIGHT)):
            # 跨越机械臂时直接重定位，不把图片平移穿过它；避免旧位置插值残留。
            self.position = self.previous_position = self.target
            self.move_wait = self.random.uniform(.65, 1.6)
            self.revision += 1

    def step(self, scene):
        self.cooldown = max(0., self.cooldown-self.DT)
        before = (self.position, self.alpha, self.frame_index, self.state)
        self.previous_position, self.previous_alpha = self.position, self.alpha
        if not self.busy:
            return
        if (not scene.drag.active or not self.available or not scene.drag_reactions.active
                or scene.config.drag_projection_probability <= 0 or scene.config.projection_opacity <= 0):
            self.stop()
        if self.state == 'showing':
            self.elapsed_ticks += 1
            elapsed = self.elapsed_ticks*self.DT
            self.frame_index = (self.elapsed_ticks//self.FRAME_TICKS) % 2
            self.alpha = smooth(elapsed/.2)
            if elapsed >= self.DURATION:
                self.stop()
            body = scene.body.chunks[0].position
            self.move_wait -= self.DT
            if self.move_wait <= 0:
                if (self.position-body).length() > 185 or self.clearance(self.position, body) < 28:
                    target = self.choose_position(scene)
                    if target is not None:
                        self.target = target
                else:
                    angle = self.random.random()*2*pi
                    candidate = self.region(scene).clamp(self.target+Vec2(cos(angle), sin(angle))*self.random.uniform(3, 9))
                    if (self.clearance(candidate, body) >= 28 and
                            self.arm_obstacles.clear_path(self.position, candidate, self.WIDTH, self.HEIGHT)):
                        self.target = candidate
                self.move_wait = self.random.uniform(.65, 1.6)
            delta = self.target-self.position
            self.position = self.region(scene).clamp(self.position+delta*min(.16, 6/max(delta.length(), 1e-9)))
            self.switch_wait = max(0., self.switch_wait-self.DT)
            nearest = self.nearest_hand(scene)
            # 小幅挪动不换手。大幅拖过投影或翻转身体时，先放下旧手再换侧。
            app = scene.appearance
            distances = [(hand.shoulder(body, scene.body.direction, i)-self.position).length()
                         for i, hand in enumerate(app.hands)]
            if self.switch_wait == 0 and distances[self.hand_index]-distances[nearest] > 5:
                self.desired_hand = nearest
            lift = (elapsed >= self.LIFT_DELAY and self.hand_index == self.desired_hand
                    and self.state == 'showing')
            self.weight += max(-self.DT/.3, min(self.DT/.4, float(lift)-self.weight))
            if self.hand_index != self.desired_hand and self.weight <= 1e-9:
                self.hand_index = self.desired_hand
                self.switch_wait = 1.
        if self.state == 'ending':
            self.weight = max(0., self.weight-self.DT/.35)
            if self.weight == 0:
                self.state = 'idle'
        if before != (self.position, self.alpha, self.frame_index, self.state):
            self.revision += 1

    def hand_weight(self, index):
        return smooth(self.weight) if index == self.hand_index else 0.

    def hand_targets(self, appearance):
        targets = [None, None]
        index, up = self.hand_index, appearance.direction
        hand = appearance.hands[index]
        shoulder = hand.shoulder(appearance.upper, up, index)
        out = Vec2(-up.y, up.x)*(-1 if index == 0 else 1)
        ray = self.position-shoulder
        angle = atan2(ray.x*up.x+ray.y*up.y, ray.x*out.x+ray.y*out.y)
        angle = max(hand.SWING_MIN+3*pi/180, min(hand.SWING_MAX-3*pi/180, angle))
        targets[index] = shoulder+(out*cos(angle)+up*sin(angle))*hand.SWING_TARGET_REACH
        return targets
