"""Bell 默认闭眼；每次观察只抽取一次开眼意愿，绘制不推进随机流。"""
from random import Random


class OracleEyes:
    OPEN_PROBABILITY = .10
    OPEN_TICKS = 10  # 40 Hz：0.25 秒
    CLOSE_TICKS = 8

    def __init__(self, seed=621):
        self.random = Random(seed)
        self.observing = False
        self.target = 0.
        self.openness = self.previous_openness = 0.
        self.revision = 0

    def begin_observation(self, *, restart=False):
        if self.observing and not restart:
            return
        self.observing = True
        self.target = float(self.random.random() < self.OPEN_PROBABILITY)

    def end_observation(self):
        self.observing = False
        self.target = 0.

    def begin_reaction(self, opened):
        """交互使用自己的抽签结果，不改变自主观察的低概率随机流。"""
        self.observing = True
        self.target = float(opened)

    @property
    def moving(self):
        return self.openness != self.target or self.previous_openness != self.openness

    def step(self):
        previous = self.previous_openness
        self.previous_openness = self.openness
        if self.target > self.openness:
            self.openness = min(self.target, self.openness+1/self.OPEN_TICKS)
        else:
            self.openness = max(self.target, self.openness-1/self.CLOSE_TICKS)
        if abs(self.openness-self.target) < 1e-9:
            self.openness = self.target
        # 包括插值终帧，防止窗口停在尚未完全开/合的画面。
        if previous != self.previous_openness or self.previous_openness != self.openness:
            self.revision += 1

    def sample(self, alpha):
        return self.previous_openness+(self.openness-self.previous_openness)*alpha
