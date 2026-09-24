import unittest
from rw_creature_pet.config import DebugConfig
from rw_creature_pet.scene import DebugScene
from rw_creature_pet.geometry import Vec2
from rw_creature_pet.render_lizard import LizardRenderer


class LimbViewTests(unittest.TestCase):
    def test_ground_pair_same_bend_in_both_directions_and_raised(self):
        s = DebugScene(DebugConfig())
        s.gait.enabled = True
        s.gait.set_speed(0)
        for _ in range(150): s.step()
        for posture in ('relaxed', 'raised'):
            s.gait.posture = posture
            for _ in range(150): s.step()
            self.assertTrue(all(f > .99 for f in s.appearance.limb_flips))
        s.gait.set_speed(-.65)
        for _ in range(90): s.step()
        s.gait.set_speed(0)
        for _ in range(200): s.step()
        self.assertTrue(all(f < -.99 for f in s.appearance.limb_flips))

    def test_geometry_transition_uses_all_banks_and_syncs(self):
        s = DebugScene(DebugConfig())
        foot = s.feet[0]
        foot.position = s.body.chunks[0].position + Vec2(0, -15)
        banks = set()
        for _ in range(20):
            s.appearance.update(s.body, s.world, s.feet)
            flip = s.appearance.limb_flips[0]
            banks.add((LizardRenderer.limb_frame(16, 1, False, False, flip)-1)//9)
        self.assertEqual(banks, {0, 1, 2})
        self.assertLess(s.appearance.limb_flips[0], -.99)
        s.appearance.sync_previous()
        self.assertEqual(s.appearance.previous_limb_flips,s.appearance.limb_flips)
        s.reset()
        self.assertEqual(s.appearance.limb_flips,[1.]*4)
