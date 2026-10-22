"""保留原向量求解作为对照，验证数值加速的轨迹、限长、休眠与后端回退"""
from math import sin
import os
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.motion import prince_tentacle_numeric as numeric
from rw_creature_pet.oracle.motion.prince_tentacles import GripRail, SupportTentacle, fit_length
from rw_creature_pet.oracle.prince_tentacles import default_study
from rw_creature_pet.oracle.scene import OracleScene, OracleWorld
from rw_creature_pet.shared.geometry import Vec2


class ReferenceTentacle(SupportTentacle):
    """优化前的向量与列表算法，避免只比较两个同源的新后端而漏掉共同偏差"""
    def solve_chain(self, root, tip, rail):
        # 旧固定端算法仅用于支撑/换点；新增自由端的约束与轨迹另有专门回归
        if self.free:
            return super().solve_chain(root, tip, rail)
        last = len(self.nodes)-1
        budget = self.shape_length_limit(root, tip)
        if (tip-root).length() >= budget-1e-6:
            for i, node in enumerate(self.nodes):
                node.position = root.lerp(tip, i/last)
            self.nodes[0].position, self.nodes[-1].position = root, tip
            return 0.
        rest, pad = budget/last, min(self.padding, rail.inset)
        for iteration in range(self.SOLVER_ITERATIONS):
            indices = range(last) if iteration % 2 == 0 else range(last-1, -1, -1)
            for i in indices:
                a, b = self.nodes[i:i+2]
                delta = b.position-a.position
                distance = delta.length()
                if distance <= rest:
                    continue
                correction = delta*((distance-rest)/max(distance, 1e-9))
                if i == 0:
                    b.position -= correction
                elif i+1 == last:
                    a.position += correction
                elif iteration % 2 == 0:
                    b.position -= correction
                else:
                    a.position += correction
            for node in self.nodes[1:-1]:
                p = node.position
                node.position = Vec2(max(pad, min(rail.width-pad, p.x)),
                                     max(pad, min(rail.height-pad, p.y)))
        for node, p in zip(self.nodes, fit_length([n.position for n in self.nodes], budget)):
            node.position = p
        return max(max(0., (b.position-a.position).length()-rest)
                   for a, b in zip(self.nodes, self.nodes[1:]))


class PrinceTentacleNumericTests(unittest.TestCase):
    def compare_trajectory(self, backend):
        rail = GripRail(OracleWorld(640, 480, .35))
        s = rail.project(Vec2(640, 200))
        tip = rail.sample(s)[0]
        for definition in (default_study().tentacles[0], default_study().tentacles[-1]):
            root = tip-Vec2(definition.length*.6, 0)
            before = ReferenceTentacle(definition, root, Vec2(1, 0), s, rail, search_seed=42)
            after = SupportTentacle(definition, root, Vec2(1, 0), s, rail, backend=backend, search_seed=42)
            buffers = (after._solve_x, after._solve_y, after._line_x, after._line_y)
            slept = False
            for tick in range(1010):
                moving = root+Vec2(0, sin(tick*.08)*12) if tick < 60 else root
                if 180 <= tick < 240:
                    moving = tip-Vec2(definition.length*1.15, 0)
                if tick >= 1000:
                    moving = root+Vec2(0, -3)
                for part in (before, after):
                    if tick == 60:
                        part.release(s+70, rail)
                    elif tick == 100:
                        part.detach()
                    elif tick == 130:
                        part.release(s, rail)
                    elif tick == 180:
                        part.length_limit = definition.length*1.2
                    elif tick == 300:
                        part.length_limit = None
                    part.step(moving, Vec2(1, 0), rail)
                self.assertEqual(before.sleeping, after.sleeping, (backend, tick))
                self.assertEqual(before.attached, after.attached)
                self.assertLess(max((a.position-b.position).length()
                                    for a,b in zip(before.nodes, after.nodes)), 1e-7, (backend, tick))
                self.assertLess(max((a.velocity-b.velocity).length()
                                    for a,b in zip(before.nodes, after.nodes)), 1e-7, (backend, tick))
                self.assertEqual(after.nodes[0].position, moving)
                if after.length_limit is not None:
                    self.assertLessEqual(after.path(1).length, after.length_limit+1e-6)
                slept |= after.sleeping
            self.assertTrue(slept)
            self.assertFalse(after.sleeping)
            self.assertTrue(all(a is b for a,b in zip(buffers,
                (after._solve_x, after._solve_y, after._line_x, after._line_y))))

    def test_python_preserves_reference_trajectory(self):
        self.compare_trajectory('python')

    def test_compiled_preserves_reference_without_compiling_during_motion(self):
        try:
            solver = numeric.compiled_tentacle_solver()
        except ImportError:
            self.skipTest('optional numba is not installed')
        signatures = tuple(solver.signatures)
        self.compare_trajectory('numba')
        self.assertEqual(tuple(solver.signatures), signatures)

    def test_auto_fallback_explicit_errors_and_environment_override(self):
        with patch.dict(os.environ, {'RW_PET_NUMERIC_BACKEND': 'auto'}):
            for failure in (ImportError('missing'), RuntimeError('compile failed')):
                numeric.tentacle_solver.cache_clear()
                with patch.object(numeric, 'compiled_tentacle_solver', side_effect=failure):
                    if isinstance(failure, ImportError):
                        self.assertIs(numeric.tentacle_solver(), numeric.solve_chain)
                    else:
                        with self.assertWarns(RuntimeWarning):
                            self.assertIs(numeric.tentacle_solver(), numeric.solve_chain)
                    with patch.dict(os.environ, {'RW_PET_NUMERIC_BACKEND': 'numba'}):
                        with self.assertRaises(type(failure)):
                            numeric.tentacle_solver('numba')
            numeric.tentacle_solver.cache_clear()
            with patch.dict(os.environ, {'RW_PET_NUMERIC_BACKEND': 'python'}), \
                    patch.object(numeric, 'compiled_tentacle_solver', side_effect=AssertionError('must not compile')):
                self.assertIs(numeric.tentacle_solver('auto'), numeric.solve_chain)
        numeric.tentacle_solver.cache_clear()

    def test_scene_passes_backend_to_all_tentacles(self):
        scene = OracleScene(OracleConfig(body_appearance='prince', physics_backend='python'))
        self.assertTrue(all(p._solver is numeric.solve_chain for p in scene.prince_tentacles.parts))


if __name__ == '__main__':
    unittest.main()
