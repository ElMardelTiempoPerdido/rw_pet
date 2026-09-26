"""普通活动的轻微侧倾，以及失重时由身体运动决定的自由朝向。"""
from math import atan2, degrees

from .behavior import Activity
from .navigation import approach


class OraclePose:
    MOVE_LEAN = 20.
    LOOK_LEAN = 16.
    MAX_SPEED = .6  # 度 / tick；40 Hz 下最多 24 度 / 秒。
    ACCELERATION = .06
    DRIFT_ANGULAR_LIMIT = .015  # 自由身体每 tick 的安全角位移上限（弧度）。

    def __init__(self):
        self.angle = self.velocity = self.target = 0.
        self.weightlessness = self._weightlessness_target = 0.

    def measured_angle(self, scene):
        axis = scene.body.direction
        angle = degrees(atan2(axis.x, -axis.y))-scene.tilt_degrees
        # 保持跨 ±180° 连续；这里读取实际姿态，不生成预设转向。
        return self.angle+(angle-self.angle+180.) % 360.-180.

    def recover_upright(self, scene):
        """从实际身体方向接回姿态控制，不挪动质点，也不保留倾斜基准。"""
        self.angle = self.measured_angle(scene)
        self.target = self.angle+(-self.angle+180.) % 360.-180.
        self.velocity = 0.
        self._weightlessness_target = 0.

    @property
    def gravity_scale(self):
        return 1.-.96*self.weightlessness

    @property
    def settled(self):
        return (abs(self.angle-self.target) < 1e-5 and abs(self.velocity) < 1e-5
                and self.weightlessness == self._weightlessness_target)

    def step(self, scene):
        behavior = scene.behavior
        drifting = behavior.drift_active and not behavior.drift_recovering
        self._weightlessness_target = float(drifting)
        self.weightlessness = approach(self.weightlessness, self._weightlessness_target, 1/120)
        if drifting:
            angle = self.measured_angle(scene)
            self.velocity = angle-self.angle
            self.angle = self.target = angle
            return
        target = 0.
        if behavior.active:
            if behavior.state in (Activity.ROAM, Activity.CROSS_EDGE, Activity.APPROACH, Activity.ORBIT):
                velocity = scene.navigator.velocity if scene.navigator else scene.body.chunks[0].velocity
                if velocity.length() > .02:
                    target = max(-1., min(1., velocity.x/scene.config.float_speed))*self.MOVE_LEAN
            if behavior.state in (Activity.NOTICE, Activity.APPROACH, Activity.RECALL, Activity.ORBIT, Activity.OBSERVE):
                gaze = scene.observed_pearl.position-scene.body.chunks[0].position
                lean = gaze.x/max(1., gaze.length())*self.LOOK_LEAN
                # 观察初期稍侧身，随后缓慢放松；不加永久振荡，结束后仍能休眠。
                if behavior.state == Activity.OBSERVE:
                    lean *= 1-.4*min(1., behavior.state_ticks/max(1, behavior.duration))
                target = target*.35+lean
        # 回正与普通活动都以直立为基准，选择最近的等价角；即使漫游
        # 已绕过 ±180° 或转过多圈，也不会为了归零反向旋转一整圈。
        target = max(-25., min(25., scene.tilt_degrees+target))-scene.tilt_degrees
        self.target = self.angle+(target-self.angle+180.) % 360.-180.
        error = self.target-self.angle
        speed = self.MAX_SPEED
        desired = max(-speed, min(speed, error*.10))
        self.velocity = approach(self.velocity, desired, self.ACCELERATION)
        if abs(error) < 1e-5 and abs(self.velocity) < 1e-5:
            self.angle, self.velocity = self.target, 0.
        else:
            self.angle += self.velocity

    def observation_force(self, scene):
        """观察只施加轻微转矩，大部分转头仍由独立头颈完成。"""
        if not scene.behavior.drift_active or not scene.behavior.looking:
            return 0.
        gaze = scene.observed_pearl.position-scene.body.chunks[0].position
        axis = scene.body.direction
        return ((axis.x*gaze.y-axis.y*gaze.x)/max(1., gaze.length())
                * .012*self.weightlessness)
