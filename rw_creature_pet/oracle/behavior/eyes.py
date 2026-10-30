"""Bell 默认闭眼；每次观察只抽取一次开眼意愿，绘制不推进随机流。"""
from random import Random


class OracleEyes:
    OPEN_PROBABILITY = .10
    OPEN_TICKS = 10  # 40 Hz：0.25 秒
    CLOSE_TICKS = 8
    PETTING_CLOSE_TICKS = 32  # 40 Hz：摸摸时用 0.8 秒缓慢闭眼，不改变普通闭眼

    def __init__(self, seed=621, *, enabled=True):
        self.random = Random(seed)
        self.enabled = enabled
        self.observing = False
        self.target = 0.
        self.attention_target = None  # 临时窗口注视覆盖；基础观察继续维护自己的目标。
        self.openness = self.previous_openness = 0.
        self.forced_closed = False
        self.closure = self.previous_closure = 0.
        self.revision = 0

    def begin_observation(self, *, restart=False, probability=None):
        if not self.enabled:
            return
        if self.observing and not restart:
            return
        self.observing = True
        self.target = float(self.random.random() < (self.OPEN_PROBABILITY if probability is None else probability))

    def end_observation(self):
        self.observing = False
        self.target = 0.

    def begin_reaction(self, opened):
        """交互使用自己的抽签结果，不改变自主观察的低概率随机流。"""
        if not self.enabled:
            return
        self.observing = True
        self.target = float(opened)

    @property
    def effective_target(self):
        if not self.enabled or self.forced_closed:
            return 0.
        return self.target if self.attention_target is None else self.attention_target

    def set_enabled(self, enabled):
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self.observing = False
        self.target = self.openness = self.previous_openness = 0.
        self.attention_target = None
        self.forced_closed = False
        self.closure = self.previous_closure = 0.
        self.revision += 1

    @property
    def moving(self):
        return (self.openness != self.effective_target or self.previous_openness != self.openness
                or self.closure != float(self.forced_closed) or self.previous_closure != self.closure)

    def step(self):
        if not self.enabled:
            return
        before = self.previous_closure
        self.previous_closure = self.closure
        close_ticks = self.PETTING_CLOSE_TICKS if self.forced_closed else self.CLOSE_TICKS
        self.closure = (min(1., self.closure+1/close_ticks) if self.forced_closed
                        else max(0., self.closure-1/self.OPEN_TICKS))
        if abs(self.closure-float(self.forced_closed)) < 1e-9:
            self.closure = float(self.forced_closed)
        previous = self.previous_openness
        self.previous_openness = self.openness
        target = self.effective_target
        if target > self.openness:
            self.openness = min(target, self.openness+1/self.OPEN_TICKS)
        else:
            self.openness = max(target, self.openness-1/close_ticks)
        if abs(self.openness-target) < 1e-9:
            self.openness = target
        # 包括插值终帧，防止窗口停在尚未完全开/合的画面。
        if (previous != self.previous_openness or self.previous_openness != self.openness
                or before != self.previous_closure or self.previous_closure != self.closure):
            self.revision += 1

    def sample(self, alpha):
        return self.previous_openness+(self.openness-self.previous_openness)*alpha

    def sample_closure(self, alpha):
        return self.previous_closure+(self.closure-self.previous_closure)*alpha
