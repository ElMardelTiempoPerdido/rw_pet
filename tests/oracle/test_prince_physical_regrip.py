"""探查伸展与自由末端触墙回抓，包含四边、拉伸余量和目标失效"""
from math import isfinite
import unittest

from rw_creature_pet.oracle.motion.prince_free_search import SearchPose
from rw_creature_pet.oracle.motion.prince_tentacles import GripRail, SupportTentacle
from rw_creature_pet.oracle.prince_tentacles import default_study
from rw_creature_pet.oracle.scene import OracleWorld
from rw_creature_pet.shared.geometry import Vec2


SIDES = (('right', Vec2(1, 0), Vec2(1280, 480)), ('left', Vec2(-1, 0), Vec2(0, 480)),
         ('top', Vec2(0, -1), Vec2(640, 0)), ('bottom', Vec2(0, 1), Vec2(640, 960)))


def make_part(definition, side, outward, near, distance):
    rail = GripRail(OracleWorld(1280, 960, .35, allowed_edges=(side,)))
    s = rail.project(near)
    root = rail.sample(s)[0]-outward*(definition.length*distance)
    part = SupportTentacle(definition, root, outward, s, rail, backend='auto', search_seed=42)
    part.length_limit = definition.length*1.2
    part.detach()
    return part, root, rail


class PrincePhysicalRegripTests(unittest.TestCase):
    def test_probe_extends_midsection_against_gravity_on_every_edge(self):
        for definition in default_study().tentacles[1:]:
            for side, outward, near in SIDES:
                with self.subTest(length=definition.length, side=side):
                    part, root, rail = make_part(definition, side, outward, near, 1.13)
                    pose = SearchPose(0., .91, 1.35)
                    part.free_search.step = lambda: pose
                    part.wall_probe.step = lambda base: base
                    part.wall_probe.value = pose
                    part.wall_probe.weight = 1.
                    for _ in range(500):
                        part.step(root, outward, rail)
                        self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                    delta = part.nodes[-1].position-root
                    self.assertGreater(delta.x*outward.x+delta.y*outward.y, definition.length*.78)
                    self.assertLessEqual(part.path(1).length, definition.length+1e-6)
                    self.assertFalse(part.attached)

    def test_regrip_uses_forces_until_contact_including_stretched_reach(self):
        for definition in default_study().tentacles[1:]:
            for side, outward, near in SIDES:
                with self.subTest(length=definition.length, side=side):
                    part, root, rail = make_part(definition, side, outward, near, 1.10)
                    part.wall_probe.wait = 10000
                    for _ in range(200):
                        part.step(root, outward, rail)
                    positions = tuple(n.position for n in part.nodes)
                    velocities = tuple(n.velocity for n in part.nodes)
                    part.release(part.grip_s, rail)
                    self.assertEqual(tuple(n.position for n in part.nodes), positions)
                    self.assertEqual(tuple(n.velocity for n in part.nodes), velocities)
                    self.assertTrue(part.free and part.transferring and part.reaching)
                    for tick in range(600):
                        previous = [n.position for n in part.nodes]
                        contact = rail.sample(rail.project(previous[-1], part.target_s))[0]
                        budget = part.free_length
                        part.step(root, outward, rail)
                        self.assertEqual(part.transfer_tick, 0)
                        self.assertEqual(part.nodes[0].position, root)
                        self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                        self.assertLessEqual(abs(part.free_length-budget),
                                             definition.length*part.FREE_LENGTH_RETURN+1e-6)
                        if part.attached:
                            # 不能从远处补间/瞬移落脚，接触前后中段也不能突然拉直
                            self.assertLess((previous[-1]-contact).length(), 10.)
                            self.assertLess(max((n.position-p).length() for n, p in zip(part.nodes, previous)), 10.)
                            break
                        self.assertTrue(part.free and part.reaching)
                    self.assertTrue(part.attached, (side, tick, (part.nodes[-1].position-part.grip).length()))
                    self.assertEqual(part.nodes[-1].position, part.grip)
                    self.assertFalse(part.transferring)

    def test_unreachable_grip_returns_to_search_and_can_be_reacquired(self):
        definition = default_study().tentacles[-1]
        for side, outward, near in SIDES:
            with self.subTest(side=side):
                part, root, rail = make_part(definition, side, outward, near, 1.10)
                part.wall_probe.wait = 10000
                for _ in range(180):
                    part.step(root, outward, rail)
                part.release(part.grip_s, rail)
                part.step(root, outward, rail)
                self.assertTrue(part.reaching)
                far = part.grip-outward*(definition.length*1.23)
                part.step(far, outward, rail)
                self.assertTrue(part.free)
                self.assertFalse(part.transferring)
                self.assertFalse(part.attached)
                self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                self.assertTrue(all(isfinite(n.position.x) and isfinite(n.position.y) for n in part.nodes))
                part.release(part.grip_s, rail)
                for _ in range(400):
                    part.step(part.grip-outward*(definition.length*.7), outward, rail)
                    if part.attached:
                        break
                self.assertTrue(part.attached)


if __name__ == '__main__':
    unittest.main()
