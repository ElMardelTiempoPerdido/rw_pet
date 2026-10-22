"""独立随机绕转、投影连续性和仿真边界"""
from dataclasses import asdict
import unittest

from PySide6.QtGui import QImage, QPainter

from rw_creature_pet.overseer.filament_motion import FilamentMotion
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.timing import FixedStepper
from tests.overseer.test_filament_observation import make_model


def snapshot(motion):
    return asdict(motion.rotation), asdict(motion.spread), motion.random.getstate()


class FilamentRotationTests(unittest.TestCase):
    def test_random_rotation_has_pauses_and_both_directions_with_bounded_steps(self):
        motion = FilamentMotion(73)
        increments, angles, radii = [], [], []
        for _ in range(4000):
            before = motion.rotation.value
            motion.step()
            increments.append(motion.rotation.value-before)
            angles.append(motion.rotation.value)
            radii.append(motion.radius)
        self.assertTrue(any(delta > .005 for delta in increments))
        self.assertTrue(any(delta < -.005 for delta in increments))
        self.assertGreater(sum(abs(delta) < 1e-12 for delta in increments), 400)
        self.assertLess(max(abs(delta) for delta in increments), .031)
        self.assertGreater(max(angles)-min(angles), 1.)
        self.assertTrue(all(15 <= radius <= 25 for radius in radii))
        self.assertGreater(max(radii)-min(radii), 8.)

    def test_ring_turns_without_wrapping_jump_and_free_chains_follow(self):
        for appearance in ('standard', 'friend'):
            model = make_model(appearance)
            target = model.root+model.local_vector(Vec2(-160, 150))
            for _ in range(160):
                model.step(target)
            model.lens.remaining = 10
            for _ in range(100):
                model.step(target)
            motion = model.filament_motion
            motion.rotation.value = 1.-1e-8
            before = motion.ring_offsets(model, 4, 12)
            motion.rotation.value = 1.+1e-8
            after = motion.ring_offsets(model, 4, 12)
            self.assertTrue(all((a-b).length() < 1e-5 for a, b in zip(before, after)))
            # 固定身体与视线，单独转动引导环；实际触须仍通过速度和约束跟随
            poses = []
            for phase in (0., .25):
                motion.rotation.value = phase
                for _ in range(100):
                    old = [[p.position for p in s] for s in model.filaments]
                    model._step_filaments()
                    for strand, previous in zip(model.filaments, old):
                        self.assertTrue(all((p.position-v).length() < 3 for p, v in zip(strand, previous)))
                poses.append([p.position for s in model.filaments for p in s[1:]])
            self.assertGreater(max((a-b).length() for a, b in zip(*poses)), 1.)

    def test_motion_is_separate_from_lens_and_body_rng_and_freezes_when_hidden_or_paused(self):
        resting, observing = [make_model('standard') for _ in range(2)]
        target = resting.root+resting.local_vector(Vec2(-200, 180))
        for tick in range(220):
            if tick == 70:
                observing.lens.remaining = 8
            for model in (resting, observing):
                model.step(target)
        self.assertEqual(snapshot(resting.filament_motion), snapshot(observing.filament_motion))
        self.assertEqual(resting.random.getstate(), observing.random.getstate())
        self.assertEqual(resting.lens.random.getstate(), observing.lens.random.getstate())
        state = snapshot(observing.filament_motion)
        clock = FixedStepper(40)
        clock.set_paused(True)
        clock.advance(20, lambda: observing.step(target))
        self.assertEqual(snapshot(observing.filament_motion), state)
        renderer = OverseerRenderer()
        canvas = QImage(640, 640, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(0)
        painter = QPainter(canvas)
        try:
            for alpha in (0., .5, 1., .5, 1.):
                renderer.draw(painter, observing, alpha)
        finally:
            painter.end()
        self.assertEqual(snapshot(observing.filament_motion), state)
        observing.request_withdraw()
        for _ in range(100):
            observing.step(target)
        self.assertFalse(observing.visible)
        state = snapshot(observing.filament_motion)
        for _ in range(100):
            observing.step(target)
        self.assertEqual(snapshot(observing.filament_motion), state)
        observing.clear()
        observing.step(target)
        self.assertEqual(snapshot(observing.filament_motion), state)


if __name__ == '__main__':
    unittest.main()
