import unittest

from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.gait import FootPhase
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene
from rw_creature_pet.shared.timing import FixedStepper


class TrackingTests(unittest.TestCase):
    def scene(self):
        s = DebugScene(DebugConfig(world_width=700, world_height=650, floor_y=600))
        s.place_on_background(300)
        return s

    def test_right_angle_uturn_and_tail_continuity(self):
        s = self.scene()
        identities = [id(c) for c in s.body.chunks]
        tail_ids = [id(t) for t in s.appearance.tail]
        bent = False
        for target in (Vec2(480, 300), Vec2(480, 420), Vec2(200, 420), Vec2(200, 150)):
            s.background.set_goal(target, s.body, s.world)
            for _ in range(1500):
                previous = [c.position for c in s.body.chunks]
                old_tail = [t.position for t in s.appearance.tail]
                old_feet = [(f.phase, f.position) for f in s.feet]
                s.step()
                self.assertGreaterEqual(s.background.grip_count, 2)
                self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
                for c, p in zip(s.body.chunks, previous):
                    self.assertLess((c.position - p).length(), 2)
                for t, p in zip(s.appearance.tail, old_tail):
                    self.assertLess((t.position - p).length(), 12)
                for f, (phase, point) in zip(s.feet, old_feet):
                    if f.phase == phase == FootPhase.STANCE:
                        self.assertEqual(f.position, point)
                a = s.body.chunks[0].position - s.body.chunks[1].position
                b = s.body.chunks[1].position - s.body.chunks[2].position
                bent |= abs(a.x * b.y - a.y * b.x) > 5
                if s.background.arrived:
                    break
            self.assertTrue(s.background.arrived)
            self.assertLess((s.body.chunks[1].position - target).length(), .6)
        self.assertTrue(bent)
        self.assertEqual(identities, [id(c) for c in s.body.chunks])
        self.assertEqual(tail_ids, [id(t) for t in s.appearance.tail])
        for _ in range(300):
            s.step()
        positions = [c.position for c in s.body.chunks]
        for _ in range(2400):
            s.step()
        self.assertTrue(all((c.position - p).length() < 1e-8 for c, p in zip(s.body.chunks, positions)))

    def test_retarget_cancel_clamp_and_release(self):
        s = self.scene()
        s.background.set_goal(Vec2(490, 320), s.body, s.world)
        for _ in range(80):
            s.step()
        s.background.set_goal(Vec2(200, 200), s.body, s.world)
        for _ in range(1200):
            s.step()
        self.assertTrue(s.background.arrived)
        s.background.set_goal(Vec2(-200, 900), s.body, s.world)
        self.assertEqual(s.background.goal, Vec2(37, 563))
        s.background.set_direction(Vec2())
        self.assertIsNone(s.background.goal)
        s.background.set_goal(Vec2(300, 300), s.body, s.world)
        s.background.set_enabled(False, s.body, s.world)
        self.assertIsNone(s.background.goal)
        with self.assertRaises(ValueError):
            s.background.set_goal(Vec2(float('nan'), 20), s.body, s.world)

    def test_tracking_fixed_step_partition(self):
        a, b = self.scene(), self.scene()
        for s in (a, b):
            s.background.set_goal(Vec2(470, 410), s.body, s.world)
        ca, cb = FixedStepper(40), FixedStepper(40)
        for _ in range(500):
            ca.advance(.01, a.step)
        for _ in range(200):
            cb.advance(.025, b.step)
        self.assertEqual(a.body.chunks, b.body.chunks)
        self.assertEqual(a.feet, b.feet)

