"""抚摸按时间识别，短暂越界可续接，无按键且必须实际移动"""
import unittest

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.interaction.petting import PettingMotion
from rw_creature_pet.shared.geometry import Vec2


class PettingTests(unittest.TestCase):
    def stroke(self, pet, seconds, *, inside=True, rate=40):
        for i in range(round(seconds*rate)):
            pet.step(1/rate, Vec2(2 if i % 2 else -2, 0), inside=inside)

    def test_deterministic_threshold_at_different_sample_rates(self):
        for rate in (20, 40, 60, 120):
            pet = PettingMotion()
            self.stroke(pet, 1.4, rate=rate)
            self.assertFalse(pet.active, rate)
            self.stroke(pet, .2, rate=rate)
            self.assertTrue(pet.active, rate)

    def test_stationary_jitter_and_moving_outside_do_not_count(self):
        for mode in ('stationary', 'jitter', 'outside'):
            pet = PettingMotion()
            for i in range(400):
                p = Vec2(10 if mode == 'stationary' else (i % 2)*(.01 if mode == 'jitter' else 20), 0)
                pet.step(.025, p, inside=mode != 'outside')
            self.assertFalse(pet.busy)
        pet = PettingMotion(.1)
        pet.step(.025, Vec2(-100, 0), inside=False)
        pet.step(.025, Vec2(), inside=True)
        for _ in range(40):
            pet.step(.025, Vec2(), inside=True)
        self.assertFalse(pet.busy)  # 仅移入后停住也不能算抚摸

    def test_grace_freezes_progress_and_short_exit_resumes(self):
        pet = PettingMotion()
        self.stroke(pet, .9)
        before = pet.elapsed
        self.stroke(pet, .4, inside=False)
        self.assertEqual(pet.elapsed, before)
        self.stroke(pet, .8)
        self.assertTrue(pet.active)
        for _ in range(10):
            pet.step(.025, None, inside=False)
        self.assertTrue(pet.active)
        self.stroke(pet, .2)
        self.assertTrue(pet.active)
        self.stroke(pet, .65, inside=False)
        self.assertFalse(pet.busy)
        self.stroke(pet, .5)
        self.assertFalse(pet.active)

    def test_stopped_motion_expires_and_press_disables_without_delayed_trigger(self):
        pet = PettingMotion(.3, .2)
        self.stroke(pet, .4)
        self.assertTrue(pet.active)
        for _ in range(20):
            pet.step(.025, Vec2(), inside=True)
        self.assertFalse(pet.busy)
        self.stroke(pet, .4)
        pet.step(.025, Vec2(), inside=True, pressed=True)
        self.assertFalse(pet.busy)
        self.stroke(pet, .1)
        self.assertFalse(pet.active)
        pet.step(.025, Vec2(), inside=True, enabled=False)
        self.assertEqual(pet.elapsed, 0.)

    def test_config_validation_and_zero_grace(self):
        for field, bad in (('petting_enabled', 1), ('petting_seconds', 0),
                           ('petting_seconds', float('nan')), ('petting_grace_seconds', -1)):
            with self.assertRaises(ValueError):
                InteractionConfig(**{field: bad})
        pet = PettingMotion(.3, 0)
        self.stroke(pet, .4)
        self.assertTrue(pet.active)
        pet.step(.025, Vec2(), inside=False)
        self.assertFalse(pet.busy)


if __name__ == '__main__':
    unittest.main()
