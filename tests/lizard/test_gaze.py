"""空间观察保持、独立性、头颈收缩与边界稳定性。"""
from math import pi
import unittest

from rw_creature_pet.lizard.appearance import unit
from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.gaze import Gaze
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene, FlatWorld
from rw_creature_pet.shared.timing import FixedStepper
from tests.lizard.test_wall_observation import placed
from tests.lizard.test_wall_rhythm import walking


class GazeTests(unittest.TestCase):
    def test_world_point_holds_while_body_moves_and_refreshes_after_turn(self):
        gaze = Gaze()
        world = FlatWorld(1000, 1000, 900)
        original = gaze.update(Vec2(400, 450), Vec2(1, 0), world)
        for tick in range(1, 50):
            point = gaze.update(Vec2(400+tick, 450), Vec2(1, 0), world)
            self.assertEqual(point, original)
        # 身体掉头后，旧观察点落在后方，应在有限时间内选到新的前方点。
        point = gaze.update(Vec2(450, 450), Vec2(-1, 0), world)
        self.assertNotEqual(point, original)
        self.assertLess(point.x, 450)
        for _ in range(30):
            self.assertEqual(gaze.update(Vec2(450, 450), Vec2(-1, 0), world), point)

    def test_explicit_focus_has_priority_without_changing_ambient_sequence(self):
        a, b = Gaze(), Gaze()
        world = FlatWorld(1000, 1000, 900)
        explicit = Vec2(450, 250)
        changes = 0
        last = None
        for tick in range(500):
            point = a.update(Vec2(400, 450), Vec2(1, 0), world, explicit)
            b.update(Vec2(400, 450), Vec2(1, 0), world)
            self.assertEqual(point, explicit)
            self.assertEqual(a.ambient_target, b.ambient_target)
            changes += last is not None and last != a.ambient_target
            last = a.ambient_target
        self.assertGreaterEqual(changes, 2)
        self.assertEqual(a.update(Vec2(400, 450), Vec2(1, 0), world),
                         b.update(Vec2(400, 450), Vec2(1, 0), world))

    def test_edge_clipping_cannot_reselect_every_tick(self):
        gaze = Gaze()
        world = FlatWorld(700, 650, 600)
        last, changed_at = None, None
        for tick in range(400):
            point = gaze.update(Vec2(7, 7), Vec2(-1, 0), world)
            if last != point:
                if changed_at is not None:
                    self.assertGreaterEqual(tick-changed_at, 20)
                changed_at = tick
                last = point

    def assert_head_safe(self, s):
        head = s.appearance.head
        axis = unit(s.body.chunks[0].position-s.body.chunks[1].position)
        anchor = s.body.chunks[0].position+axis*12
        offset = head.position-anchor
        self.assertLessEqual(offset.length(), 11+1e-6)
        self.assertGreaterEqual(offset.x*axis.x+offset.y*axis.y, 2-1e-6)
        self.assertLess((head.position-head.previous_position).length(), 5)
        self.assertLessEqual(abs(s.appearance.look_angle), 1.2)
        if s.background_mode:
            self.assertTrue(s.world.background_contains(head.position, head.radius))
        else:
            self.assertLessEqual(head.position.y+head.radius, s.world.floor_y)

    def test_neck_can_contract_and_fixed_focus_settles_without_jitter(self):
        s = placed()
        radii = []
        for tick in range(300):
            if tick % 100 == 0:
                s.appearance.observe(Vec2(440, 430 if tick % 200 == 0 else 170), 2000)
            s.step()
            self.assert_head_safe(s)
            anchor = s.body.chunks[0].position+unit(s.body.chunks[0].position-s.body.chunks[1].position)*12
            if tick > 60:
                radii.append((s.appearance.head.position-anchor).length())
        self.assertLess(min(radii), 10.7, '颈部不应始终绷在最大伸长位置')
        self.assertGreater(max(radii)-min(radii), .08)
        for _ in range(400): s.step()
        point = s.appearance.head.position
        for _ in range(400):
            s.step()
            self.assertLess((s.appearance.head.position-point).length(), 1e-7)
            self.assertLess(s.appearance.head.velocity.length(), 1e-7)

    def test_moving_observation_does_not_steer_body_or_feet(self):
        a, b = walking(tracking=True), walking(tracking=True)
        a.appearance.observe(a.body.chunks[0].position+Vec2(180, -120), 1200)
        angles = []
        for tick in range(600):
            if tick == 180:
                for s in (a, b):
                    s.background.set_goal(s.body.chunks[1].position+Vec2(-150, 0), s.body, s.world)
            a.step(); b.step()
            # 只比较运动阶段：已有的手动停留观察仍可使用旧的轻微躯干偏转。
            self.assertEqual(a.background.was_moving, b.background.was_moving)
            if not a.background.was_moving:
                break
            self.assertEqual(a.body.chunks, b.body.chunks)
            self.assertEqual(a.feet, b.feet)
            self.assert_head_safe(a)
            self.assert_head_safe(b)
            angles.append(a.appearance.look_angle)
            if a.background.arrived: break
        self.assertGreater(max(angles)-min(angles), .4)

    def test_floor_turns_and_wall_boundaries_keep_head_attached(self):
        floor = DebugScene(DebugConfig())
        floor.gait.enabled = True
        for tick in range(850):
            if tick % 200 == 0:
                floor.gait.set_speed(.88 if tick % 400 == 0 else -.88)
            if tick % 100 == 0:
                floor.appearance.observe(Vec2(200, 20 if tick % 200 == 0 else 400), 100)
            floor.step()
            self.assert_head_safe(floor)
        for center, angle in ((Vec2(130, 300), -pi/2), (Vec2(570, 300), pi/2),
                              (Vec2(350, 110), 0), (Vec2(350, 490), pi)):
            s = placed(angle, center, edge=True)
            s.appearance.observe(Vec2(350, 300), 2000)
            for _ in range(600):
                s.step()
                self.assert_head_safe(s)

    def test_gaze_and_head_obey_fixed_steps_pause_and_reset(self):
        a, b = placed(), placed()
        ca, cb = FixedStepper(40), FixedStepper(40)
        for _ in range(1000): ca.advance(.01, a.step)
        for _ in range(400): cb.advance(.025, b.step)
        self.assertEqual(a.appearance.head, b.appearance.head)
        self.assertEqual(a.appearance.gaze.point, b.appearance.gaze.point)
        before = (a.appearance.head.position, a.appearance.gaze.point, a.appearance.gaze.hold_ticks)
        ca.set_paused(True)
        ca.advance(10, a.step)
        self.assertEqual(before, (a.appearance.head.position, a.appearance.gaze.point, a.appearance.gaze.hold_ticks))
        a.reset(); b.reset()
        for _ in range(180): a.step(); b.step()
        self.assertEqual(a.appearance.head, b.appearance.head)
        self.assertEqual(a.appearance.gaze.point, b.appearance.gaze.point)
