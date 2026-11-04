"""独立拖动表情通道，不消费手势、睁眼、语音或投影的随机数"""
from collections import deque
from math import hypot
from random import Random

from ..drag_expression_config import EXPRESSION_KINDS


class OracleDragExpressions:
    FIRST_DELAY = (.3, 1.2)
    INTERVAL = (1.5, 4.)
    DURATION = (2., 5.)
    RELEASE_DELAY = (0., 5.)
    LARGE_WINDOW = .6
    LARGE_DISTANCE = 48.  # 逻辑像素，约一个人偶身高，不受桌宠显示倍率影响
    LARGE_HOLD = 1.

    def __init__(self, config, seed=937):
        self.config = config
        self.random, self.timing_random = Random(seed), Random(seed+1)
        self.held = False
        self.kind = None
        self.remaining = self.wait = self.time = self.large_remaining = 0.
        self.release_remaining = None
        self.samples = deque()

    def available(self, scene):
        shape = scene.config.active_custom_appearance
        return (scene.config.character.has_eyes and self.config.available
                and (shape is None or shape.eye_1.visible or shape.eye_2.visible))

    def clear(self, scene):
        self.kind = None
        self.remaining = 0.
        self.release_remaining = None
        scene.eyes.set_expression(None)

    def cancel(self, scene):
        self.clear(scene)
        self.held = False
        self.wait = self.time = self.large_remaining = 0.
        self.samples.clear()

    def begin(self, scene):
        if self.config != scene.config.drag_expressions:
            self.cancel(scene)
            self.config = scene.config.drag_expressions
        if not self.available(scene):
            self.cancel(scene)
            return
        self.held = True
        # 再次抓起只撤销上次松手的提前结束期限，原表情的自然时长仍继续
        self.release_remaining = None
        self.wait = self.timing_random.uniform(*self.FIRST_DELAY) if self.kind is None else 0.
        self.time = self.large_remaining = 0.
        self.samples.clear()
        self.samples.append((0., scene.drag.controller.pointer))

    def release(self, scene, *, cancel=False):
        if cancel:
            self.cancel(scene)
            return
        if not self.held:
            return  # 重复松手不能重抽结束时间
        self.held = False
        self.wait = self.large_remaining = 0.
        self.samples.clear()
        if self.kind is not None:
            self.release_remaining = self.timing_random.uniform(*self.RELEASE_DELAY)
            if self.release_remaining <= 0:
                self.clear(scene)

    def sample_motion(self, pointer, dt):
        self.time += dt
        self.large_remaining = max(0., self.large_remaining-dt)
        self.samples.append((self.time, pointer))
        while self.samples and self.samples[0][0] < self.time-self.LARGE_WINDOW:
            self.samples.popleft()
        xs, ys = [p.x for _, p in self.samples], [p.y for _, p in self.samples]
        if hypot(max(xs)-min(xs), max(ys)-min(ys)) >= self.LARGE_DISTANCE:
            self.large_remaining = self.LARGE_HOLD

    def candidates(self):
        return [(kind, getattr(self.config, kind).weight) for kind in EXPRESSION_KINDS
                if getattr(self.config, kind).enabled and getattr(self.config, kind).weight > 0
                and (not getattr(self.config, kind).large_only or self.large_remaining > 0)]

    def step(self, scene):
        if self.config != scene.config.drag_expressions:
            self.cancel(scene)
            self.config = scene.config.drag_expressions
            if scene.drag.active:
                self.begin(scene)
        if not self.available(scene) or scene.mouse_reaction.petting.active:
            self.cancel(scene)
            return
        dt = 1/scene.TICK_RATE
        if self.held:
            self.sample_motion(scene.drag.controller.pointer, dt)
        if self.kind is not None:
            self.remaining = max(0., self.remaining-dt)
            if self.release_remaining is not None:
                self.release_remaining = max(0., self.release_remaining-dt)
            if self.remaining <= 1e-9 or (self.release_remaining is not None and self.release_remaining <= 1e-9):
                self.clear(scene)
                if self.held:
                    self.wait = self.timing_random.uniform(*self.INTERVAL)
            return
        if not self.held:
            return
        self.wait -= dt
        if self.wait > 1e-9:
            return
        choices = self.candidates()
        if choices and self.random.random() < self.config.probability:
            kinds, weights = zip(*choices)
            self.kind = self.random.choices(kinds, weights)[0]
            self.remaining = self.timing_random.uniform(*self.DURATION)
            scene.eyes.set_expression(self.kind)
        else:
            self.wait = self.timing_random.uniform(*self.INTERVAL)
