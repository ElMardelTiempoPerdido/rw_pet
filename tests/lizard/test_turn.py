import unittest

from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.lizard.gait import FootPhase
from rw_creature_pet.lizard.scene import DebugScene
from rw_creature_pet.shared.timing import FixedStepper


class TurnTests(unittest.TestCase):
    def scene(self):
        s = DebugScene(DebugConfig())
        s.gait.enabled = True
        for _ in range(80):
            s.step()
        return s

    def assert_shape(self, s):
        self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), 0.002)
        for c in s.body.chunks:
            self.assertLessEqual(c.position.y + c.radius, s.world.floor_y + 1e-6)
            self.assertTrue(c.radius <= c.position.x <= s.world.width - c.radius)

    def test_turn_moves_real_chunks_continuously_both_ways(self):
        s = self.scene()
        identities = [id(c) for c in s.body.chunks]
        for direction in (-1, 1):
            s.gait.set_speed(direction * .65)
            turning_ticks = 0
            for _ in range(180):
                old = [c.position for c in s.body.chunks]
                feet = [(f.phase, f.position) for f in s.gait.feet]
                s.step()
                self.assert_shape(s)
                if s.gait.turning:
                    turning_ticks += 1
                    self.assertEqual(s.gait.effective_speed, 0)
                    self.assertGreaterEqual(s.gait.grip_count, 1)
                for c, p in zip(s.body.chunks, old):
                    self.assertLess((c.position - p).length(), 4)
                for f, (phase, point) in zip(s.gait.feet, feet):
                    if f.phase == phase == FootPhase.STANCE:
                        self.assertEqual(f.position, point)
            self.assertGreater(turning_ticks, 40)
            self.assertLess(turning_ticks, 100)
            self.assertEqual(s.gait.facing, direction)
            self.assertGreater((s.body.chunks[0].position.x - s.body.chunks[2].position.x) * direction, 33)
            self.assertGreater(s.body.chunks[1].velocity.x * direction, .5)
            self.assertEqual([id(c) for c in s.body.chunks], identities)

    def test_stop_during_turn_finishes_then_stands(self):
        s = self.scene()
        s.gait.set_speed(-.65)
        for _ in range(25):
            s.step()
        self.assertTrue(s.gait.turning)
        s.gait.set_speed(0)
        for _ in range(300):
            s.step()
        self.assertFalse(s.gait.turning)
        self.assertEqual(s.gait.facing, -1)
        self.assertEqual(s.gait.grip_count, 4)
        self.assertLess(max(c.velocity.length() for c in s.body.chunks), 1e-7)
        points = [c.position for c in s.body.chunks]
        for _ in range(400):
            s.step()
        self.assertTrue(all((c.position - p).length() < 1e-7 for c, p in zip(s.body.chunks, points)))

    def test_new_direction_during_turn_is_applied_after_completion(self):
        s = self.scene()
        s.gait.set_speed(-.65)
        for _ in range(25):
            s.step()
        s.gait.set_speed(.65)
        for _ in range(200):
            s.step()
            self.assert_shape(s)
        self.assertFalse(s.gait.turning)
        self.assertEqual(s.gait.facing, 1)
        self.assertGreater(s.body.chunks[0].position.x, s.body.chunks[2].position.x)

    def test_turn_pause_partition_reset_and_disable(self):
        a, b = self.scene(), self.scene()
        a.gait.set_speed(-.65)
        b.gait.set_speed(-.65)
        ca, cb = FixedStepper(40), FixedStepper(40)
        for _ in range(200):
            ca.advance(.01, a.step)
        for _ in range(80):
            cb.advance(.025, b.step)
        self.assertEqual(a.body.chunks, b.body.chunks)
        self.assertEqual(a.gait.feet, b.gait.feet)
        a.reset()
        for _ in range(20):
            a.step()
        self.assertTrue(a.gait.turning)
        ca.set_paused(True)
        tick = a.gait.turn_tick
        ca.advance(10, a.step)
        self.assertEqual(a.gait.turn_tick, tick)
        a.gait.enabled = False
        a.step()
        self.assertEqual(a.gait.grip_count, 0)
        self.assertEqual(a.gait.effective_speed, 0)
        for _ in range(200):
            a.step()
        self.assertFalse(a.gait.turning)
        # 中途失去支撑可能折叠落地，不能要求三个质点全都平铺。
        self.assertTrue(any(c.grounded for c in a.body.chunks))
        self.assertTrue(all(c.position.y + c.radius <= a.world.floor_y + 1e-6 for c in a.body.chunks))
        a.gait.enabled = True
        # 折叠姿态恢复的首帧沿用基础碰撞求解容差，之后重新收敛。
        a.step()
        self.assertLess(max(a.body.connection_error(c) for c in a.body.connections), .05)
        for _ in range(220):
            a.step()
            self.assert_shape(a)
        self.assertEqual(a.gait.facing, -1)


if __name__ == '__main__':
    unittest.main()
