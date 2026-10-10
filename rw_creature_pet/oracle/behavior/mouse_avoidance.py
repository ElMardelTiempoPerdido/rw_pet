"""注视一阵后才偶尔躲开；每轮停留只尝试一次，方向在触发时确定"""
from random import Random

from ...shared.geometry import Bounds
from .controller import Activity
from ..motion.navigation import approach


class OracleMouseAvoidance:
    DELAY = (3., 6.)
    PROBABILITY = .95
    STEP_SHARE = .45
    DISTANCE = (18., 32.)
    SPEED = (.30, .45)
    LEAN = (45., 70.)
    LEAN_SPEED = 10  # 度/秒，缓慢侧身，留出抓取时间
    HOLD = (3., 5.)
    MOVE_TIMEOUT = 8.

    def __init__(self):
        self.random = Random(8429)
        self.elapsed = 0.
        self.delay = None
        self.attempted = False
        self.lean = self.lean_goal = self.hold = 0.
        self.move_target = self.move_route = None
        self.move_elapsed = 0.

    @property
    def moving(self):
        return self.move_target is not None

    @property
    def busy(self):
        return self.moving or self.lean != 0. or self.lean_goal != 0.

    def owns_move(self, scene):
        return (self.moving and scene.target == self.move_target
                and (scene.navigator is None or scene.navigator.route is self.move_route))

    def stop_move(self, scene, *, brake=True):
        if self.owns_move(scene):
            if brake and not scene.drag.controlling:
                scene._move_to(scene.body.chunks[0].position, speed=scene.travel_speed)
            scene.behavior.state_ticks = 0
        self.move_target = self.move_route = None
        self.move_elapsed = 0.

    def cancel(self, scene):
        self.stop_move(scene)
        self.elapsed = 0.
        self.delay = None
        self.attempted = False
        self.lean = self.lean_goal = self.hold = 0.

    def start_move(self, scene, away):
        behavior = scene.behavior
        if (not behavior.enabled or not behavior.movement_enabled or behavior.state != Activity.IDLE
                or not scene.arrived or not scene.pose.settled):
            return
        start = scene.body.chunks[0].position
        region = scene.navigator.region if scene.navigator else scene.body_region
        box = region.edge_boxes[behavior.current_edge(scene)]
        # 身体弹性跟随允许少量过冲，终点不直接贴在走廊边界上
        margin = min(2., (box.right-box.left)*.25, (box.bottom-box.top)*.25)
        inset = Bounds(box.left+margin, box.top+margin, box.right-margin, box.bottom-margin)
        target = scene.project_target(inset.clamp(start+away*self.random.uniform(*self.DISTANCE)))
        offset = target-start
        if (not box.contains(target) or not 6. <= offset.length() <= self.DISTANCE[1]+1e-6
                or offset.x*away.x+offset.y*away.y <= 0 or not behavior.matrix_clear(scene, target)):
            return  # 边缘空间不足就只侧身，不改道、不绕到另一条边
        route = (scene.navigator.planner.round_polyline([start, target], box=box)
                 if scene.navigator else None)
        scene._move_to(target, route=route, speed=self.random.uniform(*self.SPEED))
        self.move_target = scene.target
        self.move_route = scene.navigator.route if scene.navigator else None
        self.move_elapsed = 0.

    def step(self, scene, *, active, pointer, enabled):
        if not enabled or scene.drag.controlling:
            self.cancel(scene)
            return
        dt = 1/scene.TICK_RATE
        if self.moving:
            self.move_elapsed += dt
            if not self.owns_move(scene):
                self.stop_move(scene, brake=False)  # 手动目标或其他行为接管，不覆盖新路线
            elif (not active or not scene.behavior.movement_enabled or not scene.behavior.enabled
                  or scene.behavior.state != Activity.IDLE or self.move_elapsed >= self.MOVE_TIMEOUT):
                self.stop_move(scene)
            elif scene.arrived:
                self.stop_move(scene, brake=False)
        if not active:
            self.elapsed = 0.
            self.delay = None
            self.attempted = False
            self.lean_goal = self.hold = 0.
        else:
            if self.delay is None:
                self.delay = self.random.uniform(*self.DELAY)
            if not self.attempted:
                self.elapsed += dt
                if self.elapsed+1e-9 >= self.delay:
                    self.attempted = True
                    if self.random.random() < self.PROBABILITY and not scene.behavior.drift_active:
                        away = scene.body.chunks[0].position-pointer
                        if away.length() > 1e-6:
                            away = away*(1/away.length())
                            if self.random.random() < self.STEP_SHARE:
                                self.start_move(scene, away)
                            self.lean_goal = away.x*self.random.uniform(*self.LEAN)
                            self.hold = self.random.uniform(*self.HOLD)+abs(self.lean_goal)/self.LEAN_SPEED
        if scene.behavior.drift_active:
            self.lean_goal = self.hold = 0.  # 自由失重朝向交给既有物理
        self.hold = max(0., self.hold-dt)
        if self.hold == 0.:
            self.lean_goal = 0.
        self.lean = approach(self.lean, self.lean_goal, self.LEAN_SPEED*dt)
