"""人偶拖拽适配：手动可进入中央，保留臂长，松手平滑返回活动带。"""
from math import atan2, degrees, sin, cos, pi

from ..interaction.drag import DragController, DragHandle, follow_velocity, limited
from ..shared.geometry import Bounds, Vec2
from .navigation import CurveRoute


def unit(v, fallback=Vec2(0, -1)):
    return v*(1/v.length()) if v.length() > 1e-9 else fallback


class ScreenRegion(Bounds):
    """自由拖拽使用凸矩形，不含自主导航的中央孔洞。"""
    def safe_move(self, previous, candidate):
        return self.clamp(candidate)


class OracleDrag:
    def __init__(self, scene, enabled=False):
        self.scene = scene
        self.enabled = enabled
        self.controller = DragController()
        self.recovering = False
        self.resume_autonomy = False
        self.home = None
        self.saved_corridor = scene.arm.corridor
        w = scene.world
        self.outer = Bounds(w.body_margin, w.body_margin,
                            w.width-w.body_margin, w.height-w.body_margin)
        self.free_arm = Bounds(7., 7., w.width-7., w.height-7.)
        h = scene.halo.extent
        self.halo_region = ScreenRegion(h, h, w.width-h, w.height-h)

    @property
    def active(self):
        return self.controller.active

    @property
    def controlling(self):
        return self.active or self.recovering

    @property
    def reach(self):
        # 真实可折叠段的长度上限，区别于自主导航主动保留的大幅余量。
        return sum(self.scene.arm.lengths[:3])*.98-.5

    def press(self, point, hit_test):
        if not self.enabled:
            return False
        s = self.scene
        def pick(p):
            if not hit_test(p):
                return None
            index = min(range(len(s.body.chunks)), key=lambda i: (s.body.chunks[i].position-p).length())
            return DragHandle(index, s.body.chunks[index].position)
        if not self.controller.press(point, pick):
            return False
        if not self.recovering:
            self.resume_autonomy = s.behavior.enabled
        # end_drift 可能完成跨边收尾，必须在自由模式启用前取消旧导航。
        s.behavior.cancel(s, stop_body=False)
        s.behavior.enabled = False
        s.behavior.release_observation()
        self.recovering = False
        s.arm.corridor = self.free_arm
        s.drag_reactions.begin(s)
        return True

    def move(self, point):
        self.controller.move(point)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not enabled:
            self.release(cancel=True)

    def release(self, *, cancel=False):
        if not self.controller.release():
            return
        s = self.scene
        self.recovering = True
        s.pose.recover_upright(s)
        s.drag_reactions.end(s, cancel=cancel)
        s.look_target = None
        self.home = s.project_target(s.base+s.base_normal()*64.)
        for chunk in s.body.chunks:
            chunk.velocity = Vec2() if cancel else limited(chunk.velocity, 3.)

    def project_upper(self, point, direction):
        # 末段连接是 upper - direction*last_length，不能以身体中心冒充臂端。
        center = self.scene.base+direction*self.scene.arm.lengths[3]
        for _ in range(12):
            point = self.outer.clamp(point)
            point = center+limited(point-center, self.reach)
        return point

    def step_body(self):
        s = self.scene
        upper, lower = s.body.chunks
        direction = s.body.direction
        for c in s.body.chunks:
            c.previous_position = c.position
        s.eyes.step()
        selected = self.controller.handle.key if self.active else 0
        requested = self.controller.target if self.active else self.home
        desired_upper = requested+(upper.position-s.body.chunks[selected].position)
        if s.navigator:
            # 共用底座的圆角、加速度与换向滞回；它不会瞬移到鼠标所在边。
            s.navigator.base.step(desired_upper, upper.position-direction*s.arm.lengths[3], self.reach+4)
        safe_upper = self.project_upper(desired_upper, direction)
        target = safe_upper+(s.body.chunks[selected].position-upper.position)
        if self.active:
            for i, c in enumerate(s.body.chunks):
                c.velocity = (follow_velocity(c.position, c.velocity, target) if i == selected else
                              c.velocity*.90+Vec2(0, .065 if i == 1 else -.065))
                c.position = c.position+c.velocity
            axis = unit(upper.position-lower.position, direction)
            # 限制单帧转角；没有固定的拖拽侧躺姿态。
            angle = atan2(direction.x, -direction.y)
            delta = (atan2(axis.x, -axis.y)-angle+pi) % (2*pi)-pi
            angle += max(-.075, min(.075, delta))
            direction = Vec2(sin(angle), -cos(angle))
            s.pose.angle = degrees(angle)-s.tilt_degrees
            s.pose.velocity = 0.
            s.pose.target = s.pose.angle
            s.look_target = self.controller.pointer
        else:
            s.pose.step(s)
            direction = s.desired_direction
            for i, c in enumerate(s.body.chunks):
                goal = safe_upper-direction*(i*s.body.connection_length)
                c.velocity = follow_velocity(c.position, c.velocity, goal, speed=2., acceleration=.18)
                c.position = c.position+c.velocity
        # 保留抓住的质点，另一端主要通过连接跟随；再整体投影到可达范围。
        anchor = s.body.chunks[selected].position
        upper.position = anchor+direction*(selected*s.body.connection_length)
        lower.position = upper.position-direction*s.body.connection_length
        shift = self.project_upper(upper.position, direction)-upper.position
        for c in s.body.chunks:
            c.position = c.position+shift
            c.velocity = c.position-c.previous_position
        if self.recovering:
            # 先在自由区域内让中间关节逐步收回，避免切换回边缘约束时跳变。
            for joint in s.arm.joints[1:3]:
                goal = self.saved_corridor.clamp(joint.position)
                joint.velocity = joint.velocity+limited(goal-joint.position, 3.)*.3

    def after_step(self):
        if not self.recovering:
            return
        s = self.scene
        upper = s.body.chunks[0]
        region = s.navigator.region if s.navigator else s.world.corridor(s.anchor.side)
        arm_safe = all(self.saved_corridor.contains(j.position) for j in s.arm.joints)
        if hasattr(self.saved_corridor, 'segment_safe'):
            arm_safe = arm_safe and all(self.saved_corridor.segment_safe(a.position, b.position)
                                       for a, b in zip(s.arm.joints, s.arm.joints[1:]))
        if ((upper.position-self.home).length() > .15 or upper.velocity.length() > .03
                or not region.contains(upper.position) or not arm_safe or not s.pose.settled
                or (s.halo_visible and not s.halo.region.contains(s.halo.center))
                or (s.navigator and abs(s.navigator.base.velocity) > .01)):
            return
        self.recovering = False
        s.arm.corridor = self.saved_corridor
        s.requested_target = s.target = upper.position
        s.travel_speed = None
        if s.navigator:
            s.navigator.speed = 0.
            s.navigator.set_route(CurveRoute([], upper.position))
        s.behavior.enabled = False
        if self.resume_autonomy:
            s.behavior.set_enabled(s, True)
