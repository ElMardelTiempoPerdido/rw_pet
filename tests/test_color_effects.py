import unittest
from rw_creature_pet.color_effects import ColorEffects, WHITE
from rw_creature_pet.config import DebugConfig
from rw_creature_pet.scene import DebugScene, FixedStepper


class ColorEffectTests(unittest.TestCase):
    def test_pulse_only_affects_head_and_render_is_read_only(self):
        c = ColorEffects()
        values = []
        for _ in range(500):
            c.update()
            values.append(c.head[0])
            self.assertEqual(c.body, WHITE)
        self.assertGreater(max(values)-min(values), .8)
        state = c.rng.getstate()
        before = (c.phase, c.flash, c.head)
        for _ in range(100):
            c.colors(.5)
        self.assertEqual(state, c.rng.getstate())
        self.assertEqual(before, (c.phase, c.flash, c.head))

    def test_flash_stun_display_expire_and_reset(self):
        s = DebugScene(DebugConfig())
        c = s.appearance.colors
        for effect in ('flash', 'stun', 'display'):
            c.trigger(effect)
        c.update()
        self.assertEqual(c.head, WHITE)
        tinted = False
        for _ in range(300):
            c.update()
            tinted |= c.body != WHITE
        self.assertTrue(tinted)
        self.assertEqual((c.flash, c.stun, c.dominance, c.amount), (0, 0, 0, 0))
        self.assertEqual(c.body, WHITE)
        s.reset()
        self.assertEqual(s.appearance.colors.ticks, 0)

    def test_pause_and_fixed_step_independence(self):
        a, b = ColorEffects(), ColorEffects()
        for c in (a, b):
            c.trigger('display')
            c.trigger('stun')
        x, y = FixedStepper(40), FixedStepper(40)
        for _ in range(100):
            x.advance(.01, a.update)
        for _ in range(40):
            y.advance(.025, b.update)
        self.assertEqual(a.colors(1), b.colors(1))
        self.assertEqual(a.rng.getstate(), b.rng.getstate())
        x.set_paused(True)
        before = a.colors(1)
        x.advance(10, a.update)
        self.assertEqual(a.colors(1), before)
