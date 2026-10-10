"""鼠标邻近停留：一轮停留只抽签一次；不依赖窗口、Qt 或生物实现。"""
from random import Random


class HoverAttention:
    def __init__(self, radius, dwell_seconds, probability, open_probability, seed=1937):
        self.random = Random(seed)
        self.radius, self.dwell_seconds = radius, dwell_seconds
        self.probability, self.open_probability = probability, open_probability
        self.cancel()

    def cancel(self):
        self.elapsed = 0.
        self.attempted = self.active = self.opened = False
        self.target = None

    def step(self, dt, pointer, center, *, enabled=True):
        if (not enabled or self.probability <= 0 or pointer is None
                or (pointer-center).length() > self.radius):
            self.cancel()
            return False
        started = False
        if not self.attempted:
            self.elapsed = min(self.dwell_seconds, self.elapsed+max(0., dt))
            if self.elapsed+1e-9 >= self.dwell_seconds:
                self.attempted = True
                self.active = self.random.random() < self.probability
                self.opened = self.active and self.random.random() < self.open_probability
                started = self.active
        self.target = pointer if self.active else None
        return started
