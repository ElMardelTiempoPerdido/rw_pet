"""自主躯干朝向，与移动目标、独立头部视线分开；固定 tick 平滑回正。"""
from .behavior import Activity
from .navigation import approach


class OraclePose:
    MOVE_LEAN = 20.
    LOOK_LEAN = 16.
    MAX_SPEED = .6  # 度 / tick；40 Hz 下最多 24 度 / 秒。
    ACCELERATION = .06

    def __init__(self):
        self.angle = self.velocity = self.target = 0.

    @property
    def settled(self):
        return abs(self.angle-self.target) < 1e-5 and abs(self.velocity) < 1e-5

    def step(self, scene):
        behavior = scene.behavior
        target = 0.
        if behavior.active:
            if behavior.state in (Activity.ROAM, Activity.CROSS_EDGE, Activity.APPROACH):
                velocity = scene.navigator.velocity if scene.navigator else scene.body.chunks[0].velocity
                if velocity.length() > .02:
                    target = max(-1., min(1., velocity.x/scene.config.float_speed))*self.MOVE_LEAN
            if behavior.state in (Activity.NOTICE, Activity.APPROACH, Activity.RECALL, Activity.OBSERVE):
                gaze = scene.pearl.position-scene.body.chunks[0].position
                lean = gaze.x/max(1., gaze.length())*self.LOOK_LEAN
                # 观察初期稍侧身，随后缓慢放松；不加永久振荡，结束后仍能休眠。
                if behavior.state == Activity.OBSERVE:
                    lean *= 1-.4*min(1., behavior.state_ticks/max(1, behavior.duration))
                target = target*.35+lean
        # 与手动倾角叠加后仍保留已验证的目标角范围；头、躯干身份不互换。
        self.target = max(-25., min(25., scene.tilt_degrees+target))-scene.tilt_degrees
        error = self.target-self.angle
        desired = max(-self.MAX_SPEED, min(self.MAX_SPEED, error*.10))
        self.velocity = approach(self.velocity, desired, self.ACCELERATION)
        if abs(error) < 1e-5 and abs(self.velocity) < 1e-5:
            self.angle, self.velocity = self.target, 0.
        else:
            self.angle += self.velocity
