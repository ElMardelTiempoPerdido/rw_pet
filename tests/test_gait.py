import math
import unittest

from rw_creature_pet.config import DebugConfig
from rw_creature_pet.gait import FootPhase
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.scene import DebugScene, FixedStepper


class GaitTests(unittest.TestCase):
    def scene(self, speed=0.65):
        scene = DebugScene(DebugConfig())
        scene.gait.enabled = True
        scene.gait.set_speed(speed)
        return scene

    def test_walk_both_directions_with_fixed_grips_and_shape(self):
        for speed in (-0.9, -0.65, 0.65, 0.9):
            scene = self.scene(speed)
            if speed < 0:
                for _ in range(80):
                    scene.step()
            start_x = scene.body.chunks[1].position.x
            swings = set()
            min_height, max_height = 999, -999
            for tick in range(180):
                old = [(f.phase, f.position) for f in scene.gait.feet]
                scene.step()
                for i, foot in enumerate(scene.gait.feet):
                    if foot.phase == old[i][0] == FootPhase.STANCE:
                        self.assertEqual(foot.position, old[i][1], "支撑足不能滑动")
                    if foot.phase == FootPhase.SWING:
                        swings.add(i)
                        self.assertLessEqual(foot.position.y, scene.world.floor_y)
                    if foot.phase == FootPhase.STANCE:
                        self.assertEqual(foot.position.y, scene.world.floor_y)
                        self.assertLessEqual((foot.position - scene.body.chunks[foot.chunk_index].position).length(), scene.gait.REACH)
                if tick > 40:
                    self.assertGreaterEqual(scene.gait.grip_count, 2)
                    y = scene.body.chunks[1].position.y
                    min_height, max_height = min(min_height, y), max(max_height, y)
                for c in scene.body.chunks:
                    self.assertLessEqual(c.position.y + c.radius, scene.world.floor_y + 1e-6)
                    self.assertTrue(math.isfinite(c.position.x + c.position.y))
                self.assertLess(max(scene.body.connection_error(c) for c in scene.body.connections), 0.002)
            self.assertEqual(swings, {0, 1, 2, 3})
            self.assertGreater((scene.body.chunks[1].position.x - start_x) * (1 if speed > 0 else -1), 80)
            # 低伏爬行允许腹部接近地面，不再要求人为维持最小起伏幅度。
            self.assertLess(scene.world.floor_y-max_height, 10)
            self.assertLess(max_height - min_height, 3)

    def test_stop_stays_stable_and_reverse_walks(self):
        scene = self.scene()
        for _ in range(100):
            scene.step()
        scene.gait.set_speed(0)
        for _ in range(250):
            scene.step()
        points = [c.position for c in scene.body.chunks]
        steps = [f.steps for f in scene.gait.feet]
        for _ in range(2400):
            scene.step()
        for c, point in zip(scene.body.chunks, points):
            self.assertLess((c.position - point).length(), 1e-8)
            self.assertLess(c.velocity.length(), 1e-8)
        self.assertEqual(steps, [f.steps for f in scene.gait.feet])
        scene.gait.set_speed(-0.65)
        for _ in range(220):
            scene.step()
        self.assertLess(scene.body.chunks[1].position.x, points[1].x - 70)

    def test_airborne_has_no_drive_then_recovers(self):
        scene = self.scene()
        for c in scene.body.chunks:
            c.position = c.position + Vec2(0, -100)
            c.previous_position = c.position
        for _ in range(5):
            scene.step()
            self.assertEqual(scene.gait.grip_count, 0)
            self.assertEqual(scene.body.chunks[1].position.x, 240)
        self.assertEqual(scene.gait.no_grip_ticks, 5)
        for _ in range(100):
            scene.step()
        self.assertGreaterEqual(scene.gait.grip_count, 2)
        self.assertGreater(scene.body.chunks[1].position.x, 270)
        # 运动中抬离地面，旧抓点必须释放，不能隔空悬挂身体。
        for c in scene.body.chunks:
            c.position = c.position + Vec2(0, -80)
            c.velocity = Vec2()
        scene.step()
        self.assertEqual(scene.gait.grip_count, 0)
        self.assertGreater(scene.body.chunks[1].velocity.y, 0)

    def test_boundary_stops_and_can_leave_in_reverse(self):
        for speed in (-0.9, 0.9):
            scene = self.scene(speed)
            for _ in range(700):
                scene.step()
            self.assertTrue(scene.gait.blocked)
            self.assertEqual(scene.gait.grip_count, 4)
            x = scene.body.chunks[1].position.x
            self.assertLess(scene.body.chunks[1].velocity.length(), 1e-8)
            self.assertTrue(all(c.radius <= c.position.x <= scene.world.width - c.radius for c in scene.body.chunks))
            scene.gait.set_speed(-speed)
            for _ in range(180):
                scene.step()
            self.assertFalse(scene.gait.blocked)
            self.assertGreater((x - scene.body.chunks[1].position.x) * (1 if speed > 0 else -1), 60)

    def test_fixed_step_partition_and_disabled_mode(self):
        a, b = self.scene(), self.scene()
        ca, cb = FixedStepper(40), FixedStepper(40)
        for _ in range(300):
            ca.advance(0.01, a.step)
        for _ in range(120):
            cb.advance(0.025, b.step)
        self.assertEqual(a.body.chunks, b.body.chunks)
        self.assertEqual(a.gait.feet, b.gait.feet)
        a.gait.enabled = False
        for _ in range(300):
            a.step()
        self.assertEqual(a.gait.grip_count, 0)
        self.assertTrue(all(c.grounded and c.velocity == Vec2() for c in a.body.chunks))
        for value in (math.nan, math.inf, a.gait.MAX_SPEED + .1, -a.gait.MAX_SPEED - .1):
            with self.assertRaises(ValueError):
                a.gait.set_speed(value)


if __name__ == "__main__":
    unittest.main()
