"""实体轮廓内的持续摸动识别，不依赖 Qt、随机数或具体生物"""
from collections import deque


class PettingMotion:
    MOTION_WINDOW = .15
    MIN_SPEED = 4.  # 逻辑像素 / 秒，滤掉静止指针的微小抖动

    def __init__(self, trigger_seconds=1.5, grace_seconds=.6):
        self.trigger_seconds, self.grace_seconds = trigger_seconds, grace_seconds
        self.cancel()

    @property
    def busy(self):
        return self.active or self.elapsed > 0.

    def cancel(self):
        self.elapsed = self.away_seconds = self.time = 0.
        self.active = self.previous_inside = False
        self.previous_pointer = None
        self.motion = deque()

    def step(self, dt, pointer, *, inside, enabled=True, pressed=False):
        if not enabled or pressed:
            self.cancel()
            return
        inside = inside and pointer is not None
        dt = max(0., dt)
        self.time += dt
        if inside and self.previous_inside and self.previous_pointer is not None:
            distance = (pointer-self.previous_pointer).length()
            if distance > 0:
                self.motion.append((self.time, distance))
        else:
            self.motion.clear()  # 从外部移入不把跨越桌面的路程计作抚摸
        self.previous_pointer, self.previous_inside = pointer, inside
        while self.motion and self.motion[0][0] <= self.time-self.MOTION_WINDOW:
            self.motion.popleft()
        moving = inside and sum(distance for _, distance in self.motion) >= self.MIN_SPEED*self.MOTION_WINDOW
        if moving:
            self.away_seconds = 0.
            self.elapsed = min(self.trigger_seconds, self.elapsed+dt)
            if self.elapsed+1e-9 >= self.trigger_seconds:
                self.active = True
        elif self.busy:
            self.away_seconds += dt
            if self.away_seconds+1e-9 >= self.grace_seconds:
                self.elapsed = self.away_seconds = 0.
                self.active = False
                self.motion.clear()
