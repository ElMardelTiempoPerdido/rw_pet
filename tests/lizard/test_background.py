import unittest

from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene
from rw_creature_pet.shared.timing import FixedStepper


class BackgroundTests(unittest.TestCase):
    def test_eight_directions_fixed_feet_shape_and_stop(self):
        for direction in (Vec2(1, 0), Vec2(-1, 0), Vec2(0, 1), Vec2(0, -1),
                          Vec2(1, 1), Vec2(-1, 1), Vec2(1, -1), Vec2(-1, -1), Vec2(2, 1)):
            s = DebugScene(DebugConfig(world_width=1000, world_height=960, floor_y=900))
            s.place_on_background(450)
            s.background.set_direction(direction)
            start = s.body.chunks[1].position
            d = s.background.direction
            for tick in range(500):
                feet = [(f.phase, f.position) for f in s.feet]
                s.step()
                self.assertGreaterEqual(s.background.grip_count, 2)
                self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
                for f, (phase, point) in zip(s.feet, feet):
                    if f.phase == phase and f.phase.value == '支撑':
                        self.assertEqual(f.position, point)
                delta = s.body.chunks[1].position - start
                # 自由跟随的身体在起始转向时允许小幅侧移，稳定直行后回到导航路线。
                self.assertLess(abs(delta.x * d.y - delta.y * d.x), 6 if tick < 300 else .01)
            self.assertGreater(delta.length(), 100)
            self.assertGreater(s.body.chunks[1].velocity.length(), .25)
            self.assertLess(s.body.chunks[1].velocity.length(), .95)
            self.assertTrue(all(f.steps > 0 for f in s.feet))
            s.background.set_direction(Vec2())
            for _ in range(300):
                s.step()
            positions = [c.position for c in s.body.chunks]
            steps = [f.steps for f in s.feet]
            for _ in range(2400):
                s.step()
            self.assertTrue(all((c.position - p).length() < 1e-8 and c.velocity.length() < 1e-8 for c, p in zip(s.body.chunks, positions)))
            self.assertEqual(steps, [f.steps for f in s.feet])

    def test_moving_boundary_stop_reverse_and_release(self):
        for direction in (Vec2(0, -1), Vec2(0, 1), Vec2(-1, -1), Vec2(1, 1)):
            s = DebugScene(DebugConfig())
            s.place_on_background(90)
            s.background.set_direction(direction)
            for _ in range(650):
                s.step()
            self.assertTrue(s.background.blocked)
            self.assertTrue(s.background.attached)
            self.assertLess(s.body.chunks[1].velocity.length(), 1e-7)
            start = s.body.chunks[1].position
            s.background.set_direction(direction * -1)
            for _ in range(400):
                s.step()
            self.assertGreater((s.body.chunks[1].position - start).length(), 30)
            self.assertTrue(s.background.attached)
            s.background.set_enabled(False, s.body, s.world)
            for _ in range(200):
                s.step()
            self.assertFalse(s.background.attached)
            self.assertTrue(any(c.grounded for c in s.body.chunks))

    def test_moving_fixed_step_and_invalid_direction(self):
        a, b = DebugScene(DebugConfig()), DebugScene(DebugConfig())
        for s in (a, b):
            s.place_on_background(90)
            s.background.set_direction(Vec2(2, -1))
        ca, cb = FixedStepper(40), FixedStepper(40)
        for _ in range(500):
            ca.advance(.01, a.step)
        for _ in range(200):
            cb.advance(.025, b.step)
        self.assertEqual(a.body.chunks, b.body.chunks)
        self.assertEqual(a.feet, b.feet)
        for d in (Vec2(float('nan'), 0), Vec2(0, float('inf'))):
            with self.assertRaises(ValueError):
                a.background.set_direction(d)

    def test_holds_at_multiple_heights_without_floor_contact(self):
        for height in (8, 20, 75.5, 130, 172):
            s = DebugScene(DebugConfig())
            s.place_on_background(height)
            points = [c.position for c in s.body.chunks]
            feet = [f.position for f in s.feet]
            for _ in range(2400):
                s.step()
            self.assertTrue(s.background.attached)
            self.assertEqual(s.background.grip_count, 4)
            self.assertEqual(points, [c.position for c in s.body.chunks])
            self.assertEqual(feet, [f.position for f in s.feet])
            self.assertTrue(all(c.velocity == Vec2() for c in s.body.chunks))
            self.assertEqual(sum(c.grounded for c in s.body.chunks), 3 if height == 8 else 0)

    def test_release_falls_and_regrips_without_teleport(self):
        s = DebugScene(DebugConfig())
        s.place_on_background(130)
        points = [c.position for c in s.body.chunks]
        s.background.set_enabled(False, s.body, s.world)
        self.assertEqual(points, [c.position for c in s.body.chunks])
        self.assertEqual(s.background.grip_count, 0)
        s.step()
        self.assertAlmostEqual(s.body.chunks[1].velocity.y, .9 * .999)
        s.step()
        self.assertGreater(s.body.chunks[1].velocity.y, .9)
        point = s.body.chunks[1].position
        velocity = s.body.chunks[1].velocity
        s.background.set_enabled(True, s.body, s.world)
        self.assertEqual(s.body.chunks[1].position, point)
        self.assertEqual(s.body.chunks[1].velocity, velocity)
        for _ in range(400):
            s.step()
        self.assertLess((s.body.chunks[1].position - point).length(), 1e-8)
        self.assertTrue(s.background.attached)
        s.background.set_enabled(False, s.body, s.world)
        for _ in range(200):
            s.step()
        self.assertTrue(all(c.grounded and c.velocity == Vec2() for c in s.body.chunks))

    def test_impulse_is_damped_and_out_of_reach_releases(self):
        s = DebugScene(DebugConfig())
        s.place_on_background(90)
        point = s.body.chunks[1].position
        s.set_horizontal_velocity(3)
        s.step()
        self.assertGreater(s.body.chunks[1].position.x, point.x)
        for _ in range(400):
            s.step()
        self.assertLess((s.body.chunks[1].position - point).length(), 1e-8)
        for c in s.body.chunks:
            c.position = c.position + Vec2(70, 0)
        s.step()
        self.assertFalse(s.background.attached)
        self.assertEqual(s.background.grip_count, 0)
        self.assertGreater(s.body.chunks[1].velocity.y, 0)

    def test_fixed_step_pause_reset_and_grip_query(self):
        a, b = DebugScene(DebugConfig()), DebugScene(DebugConfig())
        for s in (a, b):
            s.place_on_background(90)
            s.set_horizontal_velocity(1)
        ca, cb = FixedStepper(40), FixedStepper(40)
        for _ in range(100):
            ca.advance(.01, a.step)
        for _ in range(40):
            cb.advance(.025, b.step)
        self.assertEqual(a.body.chunks, b.body.chunks)
        ca.set_paused(True)
        tick = a.ticks
        ca.advance(10, a.step)
        self.assertEqual(a.ticks, tick)
        a.reset()
        self.assertEqual(a.ticks, 0)
        self.assertTrue(a.background.attached)
        self.assertEqual(a.body.chunks[1].position.y, 90)
        self.assertIsNone(a.world.background_grip(Vec2(-1, 20), Vec2(20, 20), 25))
        self.assertIsNone(a.world.background_grip(Vec2(20, 20), Vec2(80, 80), 25))
        for height in (0, 180, float('nan')):
            with self.assertRaises(ValueError):
                a.place_on_background(height)
