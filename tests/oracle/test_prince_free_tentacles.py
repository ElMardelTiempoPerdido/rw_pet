"""悬空触手的自由末端、弯曲余量、惯性追踪与双后端约束"""
from array import array
from dataclasses import replace
from math import hypot, isfinite, sin
import unittest

from rw_creature_pet.oracle.motion import prince_tentacle_numeric as numeric
from rw_creature_pet.oracle.motion.prince_tentacles import GripRail, SupportTentacle
from rw_creature_pet.oracle.prince_tentacles import default_study
from rw_creature_pet.oracle.scene import OracleWorld
from rw_creature_pet.shared.geometry import Vec2


SIDES = (('right', Vec2(1, 0), Vec2(640, 240)), ('left', Vec2(-1, 0), Vec2(0, 240)),
         ('top', Vec2(0, -1), Vec2(320, 0)), ('bottom', Vec2(0, 1), Vec2(320, 480)))


def make_part(side, outward, grip, backend='python', search_seed=42):
    rail = GripRail(OracleWorld(640, 480, .35, allowed_edges=(side,)))
    s = rail.project(grip)
    tip = rail.sample(s)[0]
    definition = replace(default_study().tentacles[-1], length=140.)
    root = tip-outward*(definition.length*1.15)
    part = SupportTentacle(definition, root, outward, s, rail, backend=backend, search_seed=search_seed)
    part.length_limit = definition.length*1.2
    for _ in range(60):
        part.step(root, outward, rail)
    return part, root, rail


def bend_distance(part):
    root, tip = part.nodes[0].position, part.nodes[-1].position
    axis = tip-root
    return max(abs((p.position-root).x*axis.y-(p.position-root).y*axis.x)
               /max(axis.length(), 1e-9) for p in part.nodes)


class PrinceFreeTentacleTests(unittest.TestCase):
    def test_free_solver_moves_tip_preserves_root_and_limits_every_segment(self):
        solvers = [numeric.solve_chain]
        try:
            solvers.append(numeric.compiled_tentacle_solver())
        except ImportError:
            pass
        for solver in solvers:
            x, y = array('d', (120., 150., 190., 240.)), array('d', (80., 150., 50., 180.))
            tip = (x[-1], y[-1])
            solver(x, y, array('d', [0.]*4), array('d', [0.]*4), 90., 8., 640., 480., 12, True)
            self.assertEqual((x[0], y[0]), (120., 80.))
            self.assertNotEqual((x[-1], y[-1]), tip)
            for i in range(3):
                self.assertLessEqual(hypot(x[i+1]-x[i], y[i+1]-y[i]), 30.+1e-9)
            self.assertTrue(all(8 <= v <= 632 for v in x))
            self.assertTrue(all(8 <= v <= 472 for v in y))

    def compiled(self):
        try:
            return numeric.compiled_tentacle_solver()
        except ImportError:
            self.skipTest('optional numba is not installed')

    def test_detach_is_continuous_and_retains_inertia_instead_of_pinning_goal(self):
        part, root, rail = make_part(*SIDES[0])
        other, _, _ = make_part(*SIDES[0])
        positions = tuple(p.position for p in part.nodes)
        part.detach()
        other.detach()
        self.assertEqual(positions, tuple(p.position for p in part.nodes))
        part.nodes[-1].velocity = Vec2(0., 2.)
        other.nodes[-1].velocity = Vec2(0., -2.)
        for p in (part, other):
            p.step(root, Vec2(1, 0), rail)
            self.assertGreater((p.nodes[-1].position-p.last_inputs[2]).length(), 20.)
            self.assertLess(max((a.position-b).length() for a, b in zip(p.nodes, positions)), 8.)
        self.assertGreater((part.nodes[-1].position-other.nodes[-1].position).length(), 1.)

    def test_held_free_tips_retract_with_slack_and_keep_searching_on_all_edges(self):
        for side, outward, grip in SIDES:
            with self.subTest(side=side):
                part, root, rail = make_part(side, outward, grip)
                part.detach()
                held_tips, bends, reaches = [], [], []
                for tick in range(420):
                    part.step(root, outward, rail)
                    self.assertTrue(part.free)
                    self.assertFalse(part.sleeping)
                    self.assertEqual(part.nodes[0].position, root)
                    self.assertLessEqual(part.path(1).length, part.length_limit+1e-6)
                    if tick > 90:
                        self.assertLessEqual(part.path(1).length, part.reference_length+1e-6)
                    self.assertTrue(all(isfinite(n.position.x) and isfinite(n.position.y) for n in part.nodes))
                    if tick > 90:
                        reaches.append((part.nodes[-1].position-root).length()/part.reference_length)
                    if tick > 300:
                        held_tips.append(part.nodes[-1].position)
                        bends.append(bend_distance(part))
                # 放松时允许被重力暂时拉直；不能一直被目标牵成直线
                self.assertLess(min(reaches), .9)
                self.assertGreater(max((p-held_tips[0]).length() for p in held_tips), 3.)
                self.assertGreater(max(bends), 3.)

    def test_free_trajectory_matches_compiled_backend_and_regrips(self):
        solver = self.compiled()
        signatures = tuple(solver.signatures)
        for side, outward, grip in (SIDES[0], SIDES[2]):
            with self.subTest(side=side):
                a, root, rail = make_part(side, outward, grip)
                b, _, _ = make_part(side, outward, grip, 'numba')
                for part in (a, b):
                    part.detach()
                tangent = Vec2(-outward.y, outward.x)
                for tick in range(300):
                    moving = root+tangent*(sin(tick*.06)*18.)
                    if tick >= 240:
                        moving = a.grip-outward*(a.reference_length*.6)
                    for part in (a, b):
                        if tick == 240:
                            part.release(part.grip_s, rail)
                        part.step(moving, outward, rail)
                    self.assertEqual(a.attached, b.attached)
                    self.assertLess(max((p.position-q.position).length() for p, q in zip(a.nodes, b.nodes)), 1e-7)
                self.assertTrue(a.attached)
                self.assertEqual(a.nodes[-1].position, a.grip)
        self.assertEqual(tuple(solver.signatures), signatures)


if __name__ == '__main__':
    unittest.main()
