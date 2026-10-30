"""40 Hz 拖动反应：手势、眼睛、语音各自抽签，不修改身体或机械臂约束。"""
from math import atan2, cos, pi, sin
from random import Random

from ...interaction.drag import limited
from ...interaction.voice import VoiceCue, VoiceCueChannel
from ...shared.geometry import Vec2
from ..audio.voice import VOICE_CLIPS
from ..effects.projection import OracleProjection


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
        self.eye_timing_random = Random(seed+4)
        self.voice_random = Random(seed+2)
        self.voice = VoiceCueChannel()
        self.projection = OracleProjection(seed+3)
        self.active = False
        self.gesture = None
        self.weight = self.elapsed = self.duration = self.phase = 0.
        self.gesture_wait = self.eye_wait = self.voice_wait = 0.
        self.projection_wait = 0.
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
        if self.projection.busy:
            return '展示扫描投影'
        return self.LABELS.get(self.gesture, '放松')

    def begin(self, scene):
        character = scene.config.character
        if not self.config.enabled or not (character.has_hands or character.has_eyes or scene.config.voice != 'none'):
            return
        self.active = True
        self.gesture = None
        self.weight = 0.
        # 先保留被牵拉时的自然惯性，再尝试主动反应；与语音延迟独立抽签。
        self.gesture_wait = self.sample(self.random, 'gesture_delay')
        self.eye_wait = self.sample(self.eye_timing_random, 'eye_delay')
        if self.eye_wait == 0:
            self._try_eyes(scene)
        self.projection_wait = self.sample(self.projection.random, 'projection_delay')
        # 语音与手势不共用随机流；每次抓起按配置等待后再独立抽签
        # 沿用反应计时，松手/取消不会留下窗口定时回调或延迟补播。
        self.voice_wait = self.sample(self.voice_random, 'voice_delay')

    def sample(self, random, name):
        return random.uniform(getattr(self.config, name+'_min_seconds'),
                              getattr(self.config, name+'_max_seconds'))

    def end(self, scene, *, cancel=False):
        self.active = False
        self.gesture_wait = self.eye_wait = self.voice_wait = self.projection_wait = 0.
        self.eye_remaining = 0.
        scene.eyes.end_observation()
        self.voice.cancel()
        self.projection.stop(cancel=cancel)
        if cancel:
            self.gesture = None
            self.weight = 0.
        # 正常松手逐渐撤去驱动力，不重置手的位置或积分速度。

    def start_gesture(self, kind, scene):
        """显式调试入口；日常运行通过独立的间歇抽签调用。"""
        if kind not in self.LABELS:
            raise ValueError('未知拖动手势')
        if not scene.config.character.has_hands or self.projection.busy:
            return
        self.gesture = kind
        self.weight = self.elapsed = 0.
        self.duration = self.sample(self.random, 'gesture_duration')
        self.phase = self.random.uniform(0., 2*pi)
        self.frequency = self.random.uniform(1.15, 1.65)*self.config.gesture_speed
        # 每组手势保留一个偏低的抬手上限；小段节奏变化不再把轻摆逐渐推成高举。
        # 比例映射到原目标扇形的下沿～上沿，双手围绕同一次动作意图略有差异。
        low, high = self.config.gesture_min_amplitude, self.config.gesture_max_amplitude
        lift = low+(high-low)*self.random.random()**1.6
        jitter = min(.08, (high-low)*.5)
        self.hand_lifts = [max(max(0., low-.05), min(high, lift+self.random.uniform(-jitter, jitter))) for _ in range(2)]
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
        self.flutter_shared_target = 1. if self.random.random() < self.config.flutter_sync_probability else 0.

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
            self.flutter_phases[i] += 2*pi*self.flutter_rates[i]*self.config.gesture_speed*self.DT

    def _try_gesture(self, scene):
        if not scene.config.character.has_hands:
            return
        if self.random.random() < self.config.gesture_probability:
            kind = 'protest'
            if self.random.random() < self.config.flutter_probability:
                kind = 'alternating' if self.random.random() < self.config.alternating_probability else 'flutter'
            self.start_gesture(kind, scene)
        self.gesture_wait = self.sample(self.random, 'gesture_interval')

    def _try_eyes(self, scene):
        if not scene.config.character.has_eyes:
            return
        opened = self.eye_random.random() < self.config.eye_open_probability
        scene.eyes.begin_reaction(opened)
        self.eye_remaining = self.sample(self.eye_random, 'eye_duration') if opened else 0.
        self.eye_wait = self.eye_remaining+self.sample(self.eye_random, 'eye_interval')

    def _try_voice(self, source):
        clips = VOICE_CLIPS[source]
        if not clips or self.voice.remaining > 0:
            return
        if self.voice_random.random() < self.config.voice_probability:
            pool = [clip for clip in clips if clip.clip_id != self.last_clip] or clips
            clip = self.voice_random.choice(pool)
            if self.voice.request(VoiceCue(clip.clip_id, clip.duration, 'drag')):
                self.last_clip = clip.clip_id
        self.voice_wait = self.voice.remaining+self.sample(self.voice_random, 'voice_interval')

    def sync_capabilities(self, scene):
        character = scene.config.character
        if scene.config.voice == 'none':
            self.voice.cancel()
        if not character.has_hands:
            self.gesture = None
            self.weight = 0.
            if self.projection.busy:
                self.projection.stop(cancel=True)
            if not character.has_eyes and scene.config.voice == 'none' and self.active:
                self.end(scene, cancel=True)

    def step(self, scene):
        if not self.config.enabled and self.active:
            self.end(scene, cancel=True)
        self.sync_capabilities(scene)
        self.voice.step(self.DT)
        self.projection.step(scene)
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
        if scene.config.character.has_hands and not self.gesturing and not self.projection.busy:
            # 投影独立计时，但仅在双手空闲时尝试；等待期间不积攒多次播放请求
            self.projection_wait -= self.DT
            if self.projection_wait <= 1e-9:
                self.projection.try_start(scene)
                self.projection_wait = self.sample(self.projection.random, 'projection_interval')
            self.gesture_wait -= self.DT
            if self.gesture_wait <= 1e-9 and not self.projection.busy:
                self._try_gesture(scene)
        if self.eye_remaining > 0:
            self.eye_remaining -= self.DT
            if self.eye_remaining <= 0:
                scene.eyes.end_observation()
        self.eye_wait -= self.DT
        if self.eye_wait <= 1e-9:
            self._try_eyes(scene)
        self.voice_wait -= self.DT
        if self.voice_wait <= 1e-9:
            self._try_voice(scene.config.voice)

    def hand_weight(self, index):
        if self.projection.busy:
            return self.projection.hand_weight(index)
        return self.weight if self.gesture in ('flutter', 'alternating') or (self.gesture == 'protest' and index == self.hand_index) else 0.

    def hand_targets(self, appearance, pointer):
        """目标只在各自肩外的扇形内往返，不把两个正交正弦合成为旋转力。"""
        if self.projection.busy:
            return self.projection.hand_targets(appearance)
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
        if not self.projection.busy and (not self.gesturing or self.weight == 0):
            return (Vec2(), Vec2())
        result = []
        targets = self.hand_targets(appearance, pointer)
        for i, (hand, target, natural) in enumerate(zip(appearance.hands, targets, appearance.hand_forces())):
            if target is None or self.hand_weight(i) == 0:
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
            result.append(limited(force, 3.)*self.hand_weight(i))
        return result
