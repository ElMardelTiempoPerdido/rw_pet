"""偶发朝墙探查的节奏、连续受力、长度限制及抓附优先级"""
from math import isfinite
import random
import unittest

from rw_creature_pet.oracle.motion.prince_free_search import SearchPose, WallProbe
from tests.oracle.test_prince_free_tentacles import SIDES, make_part


class PrinceWallProbeTests(unittest.TestCase):
    def test_occasional_probes_change_targets_and_blend_back_to_normal_search(self):
        probe = WallProbe(42)
        probe.begin()
        base = SearchPose(.3, .6, .4)
        previous = base
        starts, durations, targets = [], [], []
        episode = 0
        peak_reach = peak_strength = 0.
        returned = False
        for tick in range((max(probe.WAIT_TICKS)+max(probe.DURATION_TICKS))*10):
            before = probe.remaining
            value = probe.step(base)
            if before == 0 and probe.remaining > 0:
                starts.append(tick)
                episode = 0
                targets.append(set())
            if before > 0 or probe.remaining > 0:
                episode += 1
                targets[-1].add(probe.target)
            if before == 1:
                durations.append(episode)
            if durations and probe.weight == 0.:
                self.assertEqual(value, base)
                returned = True
            self.assertLess(abs(value.strength-previous.strength), .14)
            self.assertLess(abs(value.reach-previous.reach), .05)
            self.assertLess(abs(value.angle-previous.angle), .10)
            self.assertLessEqual(value.reach, .96)
            self.assertLessEqual(value.strength, 1.55)
            peak_reach = max(peak_reach, value.reach)
            peak_strength = max(peak_strength, value.strength)
            previous = value
        self.assertTrue(returned)
        self.assertGreater(peak_reach, .88)
        self.assertGreater(peak_strength, 1.2)
        self.assertTrue(probe.FIRST_WAIT_TICKS[0]-1 <= starts[0] <= probe.FIRST_WAIT_TICKS[1]-1)
        self.assertGreater(len(starts), 5)
        self.assertGreater(len(set(durations)), 3)
        for i, duration in enumerate(durations):
            self.assertTrue(probe.DURATION_TICKS[0] <= duration <= probe.DURATION_TICKS[1])
            self.assertGreaterEqual(len(targets[i]), 2)
            if i+1 < len(starts):
                gap = starts[i+1]-starts[i]-duration
                self.assertTrue(probe.WAIT_TICKS[0]-1 <= gap <= probe.WAIT_TICKS[1]-1)

    def test_tentacles_use_independent_clocks_and_do_not_share_global_randomness(self):
        state = random.getstate()
        a, b, same = WallProbe(13), WallProbe(29), WallProbe(13)
        for probe in (a, b, same):
            probe.begin()
        starts = [[], []]
        alone = 0
        for tick in range(2600):
            before = (a.remaining, b.remaining)
            self.assertEqual(a.step(SearchPose()), same.step(SearchPose()))
            b.step(SearchPose())
            for i, probe in enumerate((a, b)):
                if before[i] == 0 and probe.remaining > 0:
                    starts[i].append(tick)
            alone += ((a.weight > .8 and b.weight < .1) or
                      (b.weight > .8 and a.weight < .1))
        self.assertNotEqual(starts[0], starts[1])
        self.assertGreater(alone, 200)
        self.assertEqual(random.getstate(), state)

    def test_probe_retains_free_tip_constraints_and_regrip_preempts_it_on_all_edges(self):
        for side, outward, grip in SIDES:
            with self.subTest(side=side):
                part, root, rail = make_part(side, outward, grip)
                ordinary, _, _ = make_part(side, outward, grip)
                for p in (part, ordinary):
                    p.detach()
                part.wall_probe.wait = 0
                ordinary.wall_probe.wait = 10000
                separation = 0.
                for _ in range(180):
                    part.step(root, outward, rail)
                    ordinary.step(root, outward, rail)
                    self.assertTrue(part.free)
                    self.assertEqual(part.nodes[0].position, root)
                    self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                    self.assertTrue(all(isfinite(p.position.x) and isfinite(p.position.y) for p in part.nodes))
                    self.assertGreater((part.nodes[-1].position-part.last_inputs[2]).length(), 1e-5)
                    separation = max(separation, (part.nodes[-1].position-ordinary.nodes[-1].position).length())
                self.assertGreater(separation, 3.)
                # 在探查动作尚未结束时让真实抓点变得可达
                part.wall_probe.wait = 0
                part.step(root, outward, rail)
                self.assertGreater(part.wall_probe.remaining, 0)
                timers = (part.wall_probe.wait, part.wall_probe.remaining, part.wall_probe.retarget)
                state = part.wall_probe.random.getstate()
                part.release(part.grip_s, rail)
                for _ in range(80):
                    part.step(part.grip-outward*(part.reference_length*.6), outward, rail)
                self.assertTrue(part.attached)
                self.assertEqual(part.nodes[-1].position, part.grip)
                self.assertEqual((part.wall_probe.wait, part.wall_probe.remaining, part.wall_probe.retarget), timers)
                self.assertEqual(part.wall_probe.random.getstate(), state)


if __name__ == '__main__':
    unittest.main()
