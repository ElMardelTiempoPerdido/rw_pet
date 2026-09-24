import math
from pathlib import Path
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.lizard.config import DebugConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.lizard.scene import DebugScene
from rw_creature_pet.shared.timing import FixedStepper


class SceneTests(unittest.TestCase):
    def test_fixed_time_partition_is_equivalent(self):
        scenes = [DebugScene(DebugConfig()) for _ in range(2)]
        clocks = [FixedStepper(40) for _ in scenes]
        for scene in scenes:
            scene.set_horizontal_velocity(0.5)
        for _ in range(100):
            clocks[0].advance(0.01, scenes[0].step)
        for _ in range(40):
            clocks[1].advance(0.025, scenes[1].step)
        self.assertEqual(scenes[0].ticks, 40)
        self.assertEqual(scenes[0].body.chunks, scenes[1].body.chunks)
        self.assertGreater(scenes[0].body.chunks[1].position.x, 240)

    def test_pause_resume_does_not_catch_up(self):
        scene, clock = DebugScene(DebugConfig()), FixedStepper(40)
        clock.advance(0.02, scene.step)
        clock.set_paused(True)
        clock.advance(100, scene.step)
        self.assertEqual(scene.ticks, 0)
        clock.single_step(scene.step)
        self.assertEqual(scene.ticks, 1)
        self.assertEqual(clock.alpha, 1)
        clock.set_paused(False)
        self.assertEqual(clock.advance(0.01, scene.step), 0)
        self.assertEqual(clock.advance(0.015, scene.step), 1)

    def test_long_frame_is_bounded_and_reported(self):
        scene, clock = DebugScene(DebugConfig()), FixedStepper(40)
        self.assertEqual(clock.advance(1.01, scene.step), 4)
        self.assertAlmostEqual(clock.dropped_seconds, 0.9)
        self.assertAlmostEqual(clock.alpha, 0.4)
        self.assertEqual(clock.advance(0.015, scene.step), 1)

    def test_motion_settles_preserving_shape(self):
        for speed in (-3, 3):
            scene = DebugScene(DebugConfig())
            scene.set_horizontal_velocity(speed)
            for _ in range(400):
                scene.step()
            for chunk in scene.body.chunks:
                self.assertGreaterEqual(chunk.position.x - chunk.radius, 0)
                self.assertLessEqual(chunk.position.x + chunk.radius, scene.world.width)
                self.assertEqual(chunk.velocity, Vec2())
            self.assertAlmostEqual((scene.body.chunks[0].position - scene.body.chunks[1].position).length(), 17)
            scene.reset()
            self.assertEqual(scene.ticks, 0)
            self.assertEqual(scene.body.chunks[1].position, Vec2(240, 152))

    def test_config_errors_are_explicit(self):
        for kwargs in ({"tick_rate": 0}, {"floor_y": math.nan}, {"world_width": 30}, {"floor_y": 230}):
            with self.assertRaises(ValueError):
                DebugConfig(**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            with self.assertRaises(FileNotFoundError):
                AppConfig.load(path)
            path.write_text('game_dir = "X:/not-installed"\n[debug]\ntick_rate=40\n', encoding="utf-8")
            self.assertEqual(AppConfig.load(path).game_dir, Path("X:/not-installed"))


if __name__ == "__main__":
    unittest.main()
