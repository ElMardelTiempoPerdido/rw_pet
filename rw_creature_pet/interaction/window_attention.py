"""可复用的窗口观察事件：切换抽签、移动追踪、随机持续时间，无冷却。"""
from random import Random


class WindowAttention:
    def __init__(self, probability, open_probability, duration, seed=1827):
        self.probability, self.open_probability, self.duration = probability, open_probability, duration
        self.random = Random(seed)
        self.remaining = 0.
        self.identity = self.target = None
        self.opened = False

    @property
    def active(self):
        return self.remaining > 0

    def cancel(self):
        self.remaining = 0.
        self.identity = self.target = None

    def notice(self, identity, target, *, changed, enabled=True):
        if not enabled or identity is None or target is None:
            self.cancel()
            return False
        if changed:
            self.cancel()
            if self.random.random() < self.probability:
                self.identity, self.target = identity, target
                self.remaining = self.random.uniform(*self.duration)
                self.opened = self.random.random() < self.open_probability
                return True
        elif self.active and identity == self.identity:
            self.target = target  # 同一窗口移动不重新抽签，不延长持续时间。
        return False

    def step(self, dt):
        self.remaining = max(0., self.remaining-dt)
