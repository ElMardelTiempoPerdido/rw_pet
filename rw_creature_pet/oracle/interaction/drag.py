"""人偶拖拽适配：手动可进入中央，保留臂长，松手平滑返回活动带。"""
from math import atan2, degrees, sin, cos, pi

from ...interaction.drag import DragController, DragHandle, follow_velocity, limited
from ...shared.geometry import Bounds, Vec2
from ..motion.navigation import CurveRoute


def unit(v, fallback=Vec2(0, -1)):
    return v*(1/v.length()) if v.length() > 1e-9 else fallback


class OracleDrag:
    def __init__(self, scene, enabled=False):
        self.scene = scene
        self.enabled = enabled
        self.controller = DragController()
        self.prince_target = None
        self.prince_reference_direction = None
        self.recovering = False
        self.resume_autonomy = False
        self.home = None
        self.saved_corridor = scene.arm.corridor
        w = scene.world
        self.outer = Bounds(w.body_margin, w.body_margin,
                            w.width-w.body_margin, w.height-w.body_margin)
        self.free_arm = Bounds(7., 7., w.width-7., w.height-7.)

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
            if s.prince_posture is not None:
                points = s.prince_posture.frame(s.appearance.upper, s.appearance.direction).points
                index = min(range(len(points)), key=lambda i: (points[i]-p).length())
                return DragHandle(('prince', index), points[index])
            index = min(range(len(s.body.chunks)), key=lambda i: (s.body.chunks[i].position-p).length())
            return DragHandle(index, s.body.chunks[index].position)
        if not self.controller.press(point, pick):
            return False
        self.prince_reference_direction = s.body.direction if s.prince_posture is not None else None
        if not self.recovering:
            self.resume_autonomy = s.behavior.enabled
        # end_drift 可能完成跨边收尾，必须在自由模式启用前取消旧导航。
        s.behavior.cancel(s, stop_body=False)
        s.behavior.enabled = False
        s.behavior.release_observation()
        self.recovering = False
        s.arm.corridor = self.free_arm
        self.prince_target = self.controller.target
        s.drag_reactions.begin(s)
        if s.prince_tentacles is not None:
            s.prince_tentacles.begin_drag()
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
        self.prince_target = None
        self.prince_reference_direction = None
        s = self.scene
        self.recovering = True
        s.pose.recover_upright(s)
        s.drag_reactions.end(s, cancel=cancel)
        s.look_target = None
        if s.prince_tentacles is not None:
            support = s.prince_tentacles
            attached = [p for p in support.parts if p.attached]
            guard = (support.guard if support.guard in attached else
                     min(attached, key=lambda p: (p.grip-s.body.chunks[0].position).length(), default=None))
            # 长触手允许越过屏幕中线；按实际支撑的边归位，避免选到够不到的对边
            location = guard.grip_s if guard is not None else support.location
            edge = support.rail.sample(location)[0]
            normal = support.rail.normal(location)
            delta = s.body.chunks[0].position-edge
            edge = s.body.chunks[0].position-normal*(delta.x*normal.x+delta.y*normal.y)
            # 配置以真实工作区边缘为基准，扣除触手抓附轨道的内缩
            depth = support.study.motion.body_edge_distance-support.rail.inset
            self.home = s.project_target(edge+normal*depth)
        else:
            self.home = s.project_target(s.base+s.base_normal()*64.)
        for chunk in s.body.chunks:
            chunk.velocity = Vec2() if cancel else limited(chunk.velocity, 3.)

    def project_upper(self, point, direction, *, choose_support=False):
        # 末段连接是 upper - direction*last_length，不能以身体中心冒充臂端。
        center = self.scene.base+direction*self.scene.arm.lengths[3]
        support = self.scene.prince_tentacles
        if support is not None:
            point = support.project_drag(self.scene, point, choose=choose_support, for_target=choose_support)
        for _ in range(12):
            point = self.outer.clamp(point)
            if support is not None:
                point = support.project_drag(self.scene, point, for_target=choose_support)
            else:
                point = center+limited(point-center, self.reach)
        return point

    def prince_grab(self):
        if (self.active and isinstance(self.controller.handle.key, tuple)
                and self.controller.handle.key[0] == 'prince'):
            return self.controller.handle.key[1], self.prince_target
        return None

    def step_body(self):
        s = self.scene
        upper, lower = s.body.chunks
        direction = s.body.direction
        for c in s.body.chunks:
            c.previous_position = c.position
        s.eyes.step()
        prince = self.prince_grab()
        selected = self.controller.handle.key if self.active and prince is None else 0
        requested = self.controller.target if self.active else self.home
        if prince is not None:
            # 仅导航换算沿用按下时的方向；实际身体仍自由转动、弯曲
            # 否则下摆的长力臂会把转角反馈给支点位置，静止抓取也会持续摆动
            ideal = s.prince_posture.goals(upper.position, self.prince_reference_direction)[prince[0]]
            requested += upper.position-ideal
        desired_upper = requested+(upper.position-s.body.chunks[selected].position)
        if s.navigator:
            # 共用底座的圆角、加速度与换向滞回；它不会瞬移到鼠标所在边。
            base_target = (s.prince_tentacles.project_drag(s, desired_upper, choose=True, for_target=True)
                           if s.prince_tentacles is not None else desired_upper)
            # 隐藏的导航锚点跟随实际可达位置，不能追着超出触手范围的鼠标跨到另一边
            # 恢复时允许隐藏锚点追上已经换边的触手，否则旧机械臂跨度会把两者卡在不同边
            base_reach = float('inf') if s.prince_tentacles is not None else self.reach+4
            s.navigator.base.step(base_target, upper.position-direction*s.arm.lengths[3], base_reach)
        safe_upper = self.project_upper(desired_upper, direction, choose_support=True)
        if prince is not None:
            self.prince_target = self.controller.target+safe_upper-desired_upper
        target = safe_upper+(s.body.chunks[selected].position-upper.position)
        if self.active:
            for i, c in enumerate(s.body.chunks):
                c.velocity = (follow_velocity(c.position, c.velocity, target) if i == selected else
                              c.velocity*.90+Vec2(0, .065 if i == 1 else -.065))
                c.position = c.position+c.velocity
            if prince is not None:
                # 导航骨架保持同一参考系，避免换算方向和支点方向分离后抓取点滑离鼠标
                # Prince 的实际五段身体仍由独立的柔性物理跟随，不固定其节点姿态
                direction = self.prince_reference_direction
                angle = atan2(direction.x, -direction.y)
            else:
                axis = unit(upper.position-lower.position, direction)
                # 限制单帧转角；没有固定的拖拽侧躺姿态。
                angle = atan2(direction.x, -direction.y)
                delta = (atan2(axis.x, -axis.y)-angle+pi) % (2*pi)-pi
                angle += max(-.075, min(.075, delta))
                direction = Vec2(sin(angle), -cos(angle))
            s.pose.angle = degrees(angle)-s.tilt_degrees
            s.pose.velocity = 0.
            s.pose.target = s.pose.angle
            # Prince 拖动只由抓取力带动身体，不叠加朝鼠标主动弯腰的注视姿态
            s.look_target = None if prince is not None else self.controller.pointer
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

    def after_step(self):
        if not self.recovering:
            return
        s = self.scene
        upper = s.body.chunks[0]
        region = s.navigator.region if s.navigator else s.world.corridor(s.anchor.side)
        support_ready = (s.prince_tentacles.settled if s.prince_tentacles is not None
                         else s.arm.safe_in(self.saved_corridor) and s.arm.settled)
        # Prince 的触手与导航可达范围共同限制归位，目标可能比实际可达点远几像素
        home = (self.project_upper(self.home, s.body.direction)
                if s.prince_tentacles is not None else self.home)
        if ((upper.position-home).length() > .15 or upper.velocity.length() > .03
                or not region.contains(upper.position) or not support_ready or not s.pose.settled
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
