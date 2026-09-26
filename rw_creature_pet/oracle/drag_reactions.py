"""40 Hz 拖动反应：手势、眼睛、语音各自抽签，不修改身体或机械臂约束。"""
from math import cos, pi, sin
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
    LABELS = {'flutter': '悬空扑腾', 'protest': '短暂抗议'}

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
        self._try_gesture(scene)
        self._try_eyes(scene)
        # 语音与手势不共用随机流；每次抓起先随机等 0～3 秒，再独立抽签。
        # 沿用反应计时，松手/取消不会留下窗口定时回调或延迟补播。
        self.voice_wait = self.voice_random.uniform(0., 3.)

    def end(self, scene, *, cancel=False):
        self.active = False
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
        upper, direction = scene.body.chunks[0].position, scene.body.direction
        side = Vec2(-direction.y, direction.x)
        delta = scene.drag.controller.pointer-upper
        self.hand_index = 1 if delta.x*side.x+delta.y*side.y >= 0 else 0

    def _try_gesture(self, scene):
        if self.random.random() < self.config.gesture_probability:
            self.start_gesture('flutter' if self.random.random() < self.config.flutter_probability
                               else 'protest', scene)
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

    def hand_forces(self, appearance, pointer):
        if not self.gesturing or self.weight == 0:
            return (Vec2(), Vec2())
        direction = appearance.direction
        side = Vec2(-direction.y, direction.x)
        result = []
        for i, hand in enumerate(appearance.hands):
            sign = -1 if i == 0 else 1
            if self.gesture == 'flutter':
                phase = self.phase+i*2.1
                force = (direction*(.9+1.35*cos(phase))
                         + side*(sign*(.65+.45*sin(phase))))*(1+.35*self.motion)
            elif i == self.hand_index:
                delta = pointer-hand.position
                aim = delta*(1/delta.length()) if delta.length() > 1e-6 else direction
                force = aim*1.1+direction*(1.1+.5*cos(self.phase))+side*(1.3*sin(self.phase))
            else:
                force = direction*.25+side*(sign*.2)
            result.append(limited(force, 3.)*self.weight)
        return result
