"""探寻力度、目标连续性、独立随机流与重复松开的回归"""
import random
import unittest

from rw_creature_pet.oracle.motion.prince_free_search import FreeTipSearch
from tests.oracle.test_prince_free_tentacles import SIDES, make_part


class PrinceFreeSearchTests(unittest.TestCase):
    def test_targets_and_force_vary_smoothly_with_irregular_intervals(self):
        search = FreeTipSearch(42)
        search.begin()
        previous = search.value
        values, changes = [], []
        for tick in range(2400):
            value = search.step()
            if search.tick == 1:
                changes.append(tick)
            self.assertLessEqual(abs(value.angle), search.ANGLE+1e-9)
            self.assertTrue(.45-1e-9 <= value.reach <= .80+1e-9)
            self.assertTrue(0. <= value.strength <= 1.+1e-9)
            # 覆盖段切换处；不允许新随机目标直接跳到新角度、距离或力度
            self.assertLess(abs(value.angle-previous.angle), .060)
            self.assertLess(abs(value.reach-previous.reach), .022)
            self.assertLess(abs(value.strength-previous.strength), .060)
            values.append(value)
            previous = value
        self.assertGreater(len(set(b-a for a, b in zip(changes, changes[1:]))), 5)
        self.assertGreater(max(v.angle for v in values), .3)
        self.assertLess(min(v.angle for v in values), -.3)
        self.assertGreater(max(v.reach for v in values)-min(v.reach for v in values), .2)
        self.assertGreater(max(v.strength for v in values), .9)
        self.assertTrue(any(v.strength < .2 for v in values[200:]))

    def test_independent_streams_and_clocks_do_not_consume_global_randomness(self):
        state = random.getstate()
        a, b, other = FreeTipSearch(11), FreeTipSearch(11), FreeTipSearch(29)
        for search in (a, b, other):
            search.begin()
        changes = [[], []]
        opposed = 0
        for tick in range(2400):
            x, y, z = a.step(), b.step(), other.step()
            self.assertEqual(x, y)
            for i, search in enumerate((a, other)):
                if search.tick == 1:
                    changes[i].append(tick)
            opposed += (x.strength > .65 and z.strength < .3 or
                        z.strength > .65 and x.strength < .3)
            # 另一条触手重新松开不会重置本条的随机序列或时钟
            if tick % 137 == 0:
                other.begin()
        self.assertNotEqual(changes[0], changes[1])
        self.assertGreater(opposed, 100)
        self.assertEqual(random.getstate(), state)

    def test_detach_changes_plan_without_teleport_and_attached_motion_pauses_search(self):
        side, outward, grip = SIDES[0]
        part, root, rail = make_part(side, outward, grip)
        initial = part.free_search.random.getstate()
        part.step(root, outward, rail)
        self.assertEqual(part.free_search.random.getstate(), initial)
        plans = []
        for _ in range(3):
            positions = tuple(p.position for p in part.nodes)
            velocities = tuple(p.velocity for p in part.nodes)
            part.detach()
            self.assertEqual(tuple(p.position for p in part.nodes), positions)
            self.assertEqual(tuple(p.velocity for p in part.nodes), velocities)
            self.assertEqual(part.free_search.value.strength, 0.)
            plans.append(part.free_search.target)
            for tick in range(140):
                part.step(root, outward, rail)
                self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                self.assertLessEqual((part.last_inputs[2]-root).length(),
                                     part.wall_probe.REACH[1]*part.reference_length+1e-6)
            state = part.free_search.random.getstate()
            search_tick = part.free_search.tick
            part.release(part.grip_s, rail)
            for _ in range(80):
                part.step(part.grip-outward*(part.reference_length*.6), outward, rail)
            self.assertTrue(part.attached)
            self.assertEqual(part.nodes[-1].position, part.grip)
            self.assertEqual(part.free_search.tick, search_tick)
            self.assertEqual(part.free_search.random.getstate(), state)
        self.assertEqual(len(set(plans)), 3)


if __name__ == '__main__':
    unittest.main()
