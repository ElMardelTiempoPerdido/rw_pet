"""以落地、约束语义、扰动恢复和长期稳定作为验收标准。"""
import math
import unittest

from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.model import LizardBody
from rw_creature_pet.lizard.physics import solve_connection
from rw_creature_pet.lizard.scene import DebugScene


class PhysicsTests(unittest.TestCase):
    def assert_valid(self, scene, tolerance=0.002):
        for chunk in scene.body.chunks:
            for value in (chunk.position.x, chunk.position.y, chunk.velocity.x, chunk.velocity.y):
                self.assertTrue(math.isfinite(value))
            self.assertLessEqual(chunk.position.y + chunk.radius, scene.world.floor_y + 1e-7)
            self.assertGreaterEqual(chunk.position.x, chunk.radius - 1e-7)
            self.assertLessEqual(chunk.position.x + chunk.radius, scene.world.width + 1e-7)
        for connection in scene.body.connections:
            self.assertLess(scene.body.connection_error(connection), tolerance)

    def test_acceleration_then_ground_contact(self):
        scene = DebugScene(DebugConfig())
        scene.step()
        first_speed = scene.body.chunks[0].velocity.y
        self.assertGreater(first_speed, 0)
        scene.step()
        self.assertGreater(scene.body.chunks[0].velocity.y, first_speed)
        self.assertFalse(any(c.grounded for c in scene.body.chunks))
        for _ in range(100):
            scene.step()
            self.assert_valid(scene)
        self.assertTrue(all(c.grounded for c in scene.body.chunks))
        self.assertTrue(all(c.velocity == Vec2() for c in scene.body.chunks))

    def test_push_only_separates_and_never_pulls(self):
        body = LizardBody.preview(Vec2(100, 100))
        push = body.connections[2]
        before = [c.position for c in body.chunks]
        solve_connection(body, push)
        self.assertEqual(before, [c.position for c in body.chunks])
        body.chunks[2].position = body.chunks[0].position
        solve_connection(body, push)
        self.assertGreater((body.chunks[2].position - body.chunks[0].position).length(), 0)
        for _ in range(200):
            solve_connection(body, push)
        self.assertLess(body.connection_error(push), 1e-8)

    def test_normal_restores_stretched_and_compressed_connection(self):
        for length in (0, 5, 40):
            body = LizardBody.preview(Vec2(100, 100))
            first, second = body.chunks[:2]
            second.position = first.position + Vec2(length, 0)
            center = (first.position + second.position) * 0.5
            for _ in range(30):
                solve_connection(body, body.connections[0])
            self.assertLess(body.connection_error(body.connections[0]), 1e-8)
            self.assertLess(((first.position + second.position) * 0.5 - center).length(), 1e-8)

    def test_tilted_drop_and_floor_corner(self):
        for x, velocity in ((240, 2), (28, -3), (452, 3)):
            scene = DebugScene(DebugConfig())
            scene.body = LizardBody.preview(Vec2(x, 55))
            scene.body.chunks[0].position += Vec2(0, -13)
            scene.body.chunks[2].position += Vec2(0, 11)
            scene.set_horizontal_velocity(velocity)
            for _ in range(400):
                scene.step()
                self.assert_valid(scene, tolerance=0.15)
            self.assertTrue(all(c.grounded for c in scene.body.chunks))
            self.assertTrue(all(c.velocity.length() < 1e-6 for c in scene.body.chunks))

    def test_one_hour_rest_and_wake_by_external_velocity(self):
        scene = DebugScene(DebugConfig())
        for _ in range(200):
            scene.step()
        before = [c.position for c in scene.body.chunks]
        for _ in range(40 * 60 * 60):
            scene.step()
        self.assert_valid(scene)
        self.assertEqual(before, [c.position for c in scene.body.chunks])
        self.assertTrue(all(c.velocity == Vec2() for c in scene.body.chunks))
        scene.body.chunks[0].velocity = Vec2(1, -5)
        scene.step()
        self.assertLess(scene.body.chunks[0].position.y, before[0].y)
        for _ in range(400):
            scene.step()
        self.assert_valid(scene)
        self.assertTrue(all(c.grounded for c in scene.body.chunks))


if __name__ == "__main__":
    unittest.main()
