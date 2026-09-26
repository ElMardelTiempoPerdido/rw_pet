"""40 Hz 拖动反应：手势、眼睛、语音各自抽签，不修改身体或机械臂约束。"""
from math import atan2, cos, pi, sin
from random import Random

from ..interaction.drag import limited
from ..interaction.voice import VoiceCue, VoiceCueChannel
from ..shared.geometry import Vec2
from .voice import BELL_VOICE_CLIPS


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


class OracleDragReactions:
    DT = 1/40
    LABELS = {'flutter': '悬空扑腾', 'alternating': '交替划动', 'protest': '短暂抗议'}

    def __init__(self, config, seed=925):
        self.config = config
        self.random = Random(seed)
        self.eye_random = Random(seed+1)
        self.voice_random = Random(seed+2)
        self.voice = VoiceCueChannel()
        self.active = False
        self.gesture = None
        self.weight = self.elapsed = self.duration = self.phase = 0.
        self.gesture_wait = self.eye_wait = self.voice_wait = 0.
        self.eye_remaining = self.motion = 0.
        self.frequency = 1.
        self.flutter_phases = [0., 0.]
        self.flutter_rates = [1., 1.]
        self.flutter_rate_targets = [1., 1.]
        self.flutter_strengths = [1., 1.]
        self.flutter_strength_targets = [1., 1.]
        self.flutter_shared = self.flutter_shared_target = self.flutter_wait = 0.
        self.hand_lifts = [1., 1.]
        self.hand_index = 0
        self.last_clip = None

    @property
    def gesturing(self):
        return self.gesture is not None

    @property
    def label(self):
        return self.LABELS.get(self.gesture, '放松')

    def begin(self, scene):
        if not self.config.enabled:
            return
        self.active = True
        self.gesture = None
        self.weight = 0.
        # 先保留被牵拉时的自然惯性，再尝试主动反应；与语音延迟独立抽签。
        self.gesture_wait = self.random.uniform(.15, 1.5)
        self._try_eyes(scene)
        # 语音与手势不共用随机流；每次抓起先随机等 0～3 秒，再独立抽签。
        # 沿用反应计时，松手/取消不会留下窗口定时回调或延迟补播。
        self.voice_wait = self.voice_random.uniform(0., 3.)

    def end(self, scene, *, cancel=False):
        self.active = False
        self.gesture_wait = 0.
        self.voice_wait = 0.
        self.eye_remaining = 0.
        scene.eyes.end_observation()
        self.voice.cancel()
        if cancel:
            self.gesture = None
            self.weight = 0.
        # 正常松手逐渐撤去驱动力，不重置手的位置或积分速度。

    def start_gesture(self, kind, scene):
        """显式调试入口；日常运行通过独立的间歇抽签调用。"""
        if kind not in self.LABELS:
            raise ValueError('未知拖动手势')
        self.gesture = kind
        self.weight = self.elapsed = 0.
        self.duration = self.random.uniform(1.4, 2.6)
        self.phase = self.random.uniform(0., 2*pi)
        self.frequency = self.random.uniform(1.15, 1.65)
        # 每组手势保留一个偏低的抬手上限；小段节奏变化不再把轻摆逐渐推成高举。
        # 比例映射到原目标扇形的下沿～上沿，双手围绕同一次动作意图略有差异。
        lift = .25+.75*self.random.random()**1.6
        self.hand_lifts = [max(.2, min(1., lift+self.random.uniform(-.08, .08))) for _ in range(2)]
        if kind == 'flutter':
            self.flutter_phases = [self.random.uniform(0., 2*pi) for _ in range(2)]
            self.flutter_rates = [self.random.uniform(.8, 1.9) for _ in range(2)]
            self.flutter_strengths = [1., 1.]
            self.flutter_shared = 0.
            self._choose_flutter_rhythm()
        upper, direction = scene.body.chunks[0].position, scene.body.direction
        side = Vec2(-direction.y, direction.x)
        delta = scene.drag.controller.pointer-upper
        self.hand_index = 1 if delta.x*side.x+delta.y*side.y >= 0 else 0

    def _choose_flutter_rhythm(self):
        # 一小段动作内保持意图，避免逐帧随机力造成抖动。下一段再改变快慢、力度和协调方式。
        self.flutter_wait = self.random.uniform(.35, .9)
        self.flutter_rate_targets = [self.random.uniform(.8, 1.9) for _ in range(2)]
        self.flutter_strength_targets = [self.random.uniform(.7, 1.25) for _ in range(2)]
        self.flutter_shared_target = 1. if self.random.random() < .35 else 0.

    def _step_flutter(self):
        if self.active:
            self.flutter_wait -= self.DT
            if self.flutter_wait <= 0:
                self._choose_flutter_rhythm()
        # 混合摆角节奏，允许两手一起抬起/放下，不把手的位置或相位瞬间拉到一起。
        self.flutter_shared += (self.flutter_shared_target-self.flutter_shared)*.18
        for i in range(2):
            self.flutter_rates[i] += (self.flutter_rate_targets[i]-self.flutter_rates[i])*.12
            self.flutter_strengths[i] += (self.flutter_strength_targets[i]-self.flutter_strengths[i])*.12
            self.flutter_phases[i] += 2*pi*self.flutter_rates[i]*self.DT

    def _try_gesture(self, scene):
        if self.random.random() < self.config.gesture_probability:
            kind = 'protest'
            if self.random.random() < self.config.flutter_probability:
                kind = 'alternating' if self.random.random() < self.config.alternating_probability else 'flutter'
            self.start_gesture(kind, scene)
        self.gesture_wait = self.random.uniform(.45, 1.35)

    def _try_eyes(self, scene):
        opened = self.eye_random.random() < self.config.eye_open_probability
        scene.eyes.begin_reaction(opened)
        self.eye_remaining = self.eye_random.uniform(1.5, 3.) if opened else 0.
        self.eye_wait = self.eye_remaining+self.eye_random.uniform(.9, 2.)

    def _try_voice(self):
        if self.voice.remaining > 0:
            return
        if self.voice_random.random() < self.config.voice_probability:
            pool = [clip for clip in BELL_VOICE_CLIPS if clip.clip_id != self.last_clip]
            clip = self.voice_random.choice(pool)
            if self.voice.request(VoiceCue(clip.clip_id, clip.duration, 'drag')):
                self.last_clip = clip.clip_id
        self.voice_wait = self.voice.remaining+self.voice_random.uniform(1.8, 3.8)

    def step(self, scene):
        self.voice.step(self.DT)
        if not self.active and not self.gesturing:
            return
        self.motion += (min(1., scene.body.chunks[0].velocity.length()/5.)-self.motion)*.15
        if self.gesturing:
            self.phase += 2*pi*self.frequency*self.DT
            if self.gesture == 'flutter':
                self._step_flutter()
            if self.active:
                self.elapsed += self.DT
                self.weight = smooth(self.elapsed/.18)*smooth((self.duration-self.elapsed)/.3)
            else:
                self.weight = max(0., self.weight-self.DT/.25)
            if (self.active and self.elapsed >= self.duration) or (not self.active and self.weight == 0):
                self.gesture = None
                self.weight = 0.
        if not self.active:
            return
        if not self.gesturing:
            self.gesture_wait -= self.DT
            if self.gesture_wait <= 0:
                self._try_gesture(scene)
        if self.eye_remaining > 0:
            self.eye_remaining -= self.DT
            if self.eye_remaining <= 0:
                scene.eyes.end_observation()
        self.eye_wait -= self.DT
        if self.eye_wait <= 0:
            self._try_eyes(scene)
        self.voice_wait -= self.DT
        if self.voice_wait <= 0:
            self._try_voice()

    def hand_weight(self, index):
        return self.weight if self.gesture in ('flutter', 'alternating') or (self.gesture == 'protest' and index == self.hand_index) else 0.

    def hand_targets(self, appearance, pointer):
        """目标只在各自肩外的扇形内往返，不把两个正交正弦合成为旋转力。"""
        direction = appearance.direction
        side = Vec2(-direction.y, direction.x)
        targets = []
        for i, hand in enumerate(appearance.hands):
            if not self.hand_weight(i):
                targets.append(None)
                continue
            outward = side*(-1 if i == 0 else 1)
            shoulder = hand.shoulder(appearance.upper, direction, i)
            # 目标比物理限位内收 7 度，为物理惯性留下缓冲。
            low, high = hand.SWING_MIN+7*pi/180, hand.SWING_MAX-7*pi/180
            high = low+(high-low)*self.hand_lifts[i]
            if self.gesture in ('flutter', 'alternating'):
                if self.gesture == 'alternating':
                    # 整组保持半周期相差，不混入随机扑腾的同步意图或独立变速。
                    swing = sin(self.phase)*(1 if i == 0 else -1)
                else:
                    swing = sin(self.flutter_phases[i])*(1-self.flutter_shared)+sin(self.phase)*self.flutter_shared
                    swing = max(-1., min(1., swing*self.flutter_strengths[i]))
                angle = (low+high)*.5+(high-low)*.5*swing
            else:
                delta = pointer-shoulder
                aim = atan2(delta.x*direction.x+delta.y*direction.y,
                            delta.x*outward.x+delta.y*outward.y)
                wobble = min(.2, (high-low)*.25)
                angle = max(low, min(high, max(low+wobble, min(high-wobble, aim))+wobble*sin(self.phase)))
            targets.append(shoulder+(outward*cos(angle)+direction*sin(angle))*hand.SWING_TARGET_REACH)
        return targets

    def hand_forces(self, appearance, pointer):
        if not self.gesturing or self.weight == 0:
            return (Vec2(), Vec2())
        result = []
        targets = self.hand_targets(appearance, pointer)
        for i, (hand, target, natural) in enumerate(zip(appearance.hands, targets, appearance.hand_forces())):
            if target is None:
                result.append(Vec2())
                continue
            relative_velocity = hand.drive_velocity-appearance.last_body_velocity
            shoulder = hand.shoulder(appearance.upper, appearance.direction, i)
            delta, goal = hand.position-shoulder, target-shoulder
            distance = delta.length()
            radial = delta*(1/distance) if distance > 1e-9 else goal*(1/hand.SWING_TARGET_REACH)
            tangent = Vec2(-radial.y, radial.x)
            angle = atan2(tangent.x*goal.x+tangent.y*goal.y, radial.x*goal.x+radial.y*goal.y)
            # 沿肩部圆弧追赶摆角，径向只修正伸屈；直接追逐平面目标会沿弦切入、缩短袖子。
            offset = (radial*(hand.SWING_TARGET_REACH-distance)
                      + tangent*(angle*min(distance, hand.SWING_TARGET_REACH)))
            force = offset*(.22+.05*self.motion)-relative_velocity*.5-natural
            result.append(limited(force, 3.)*self.weight)
        return result
