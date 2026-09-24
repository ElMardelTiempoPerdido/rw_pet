"""生物共用的固定步长时钟，不依赖 Qt 或具体场景。"""
from math import isfinite


class FixedStepper:
    """实际计时独立于画面重绘；暂停丢弃积压，慢帧限制追赶量。"""
    def __init__(self, tick_rate: int, max_steps: int = 4):
        self.dt = 1.0 / tick_rate
        self.max_steps = max_steps
        self.paused = False
        self.accumulator = 0.0
        self.dropped_seconds = 0.0

    @property
    def alpha(self) -> float:
        return 1.0 if self.paused else self.accumulator / self.dt

    def set_paused(self, paused: bool):
        self.paused = paused
        self.accumulator = 0.0

    def advance(self, elapsed: float, step) -> int:
        if not isfinite(elapsed) or elapsed < 0:
            raise ValueError("elapsed 必须为非负有限数值")
        if self.paused:
            return 0
        self.accumulator += elapsed
        count = int((self.accumulator + 1e-12) / self.dt)
        if count > self.max_steps:
            dropped = (count - self.max_steps) * self.dt
            self.dropped_seconds += dropped
            self.accumulator -= dropped
            count = self.max_steps
        for _ in range(count):
            step()
        self.accumulator = max(0.0, self.accumulator - count * self.dt)
        return count

    def single_step(self, step):
        self.set_paused(True)
        step()
