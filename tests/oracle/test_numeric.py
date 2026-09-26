"""编译后端的轨迹、迭代收敛、休眠唤醒与可选依赖回退。"""
from math import sin, cos
import unittest
from unittest.mock import patch

from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.cords import Rope
from rw_creature_pet.oracle import numeric


class NumericTests(unittest.TestCase):
    def test_optional_dependency_and_compilation_failure_fall_back(self):
        for failure in (ImportError('missing'), RuntimeError('compile failed')):
            numeric.rope_solver.cache_clear()
            with patch.object(numeric, 'compiled_rope_solver', side_effect=failure):
                if isinstance(failure, ImportError):
                    self.assertIs(numeric.rope_solver('auto'), numeric.solve_rope)
                else:
                    with self.assertWarns(RuntimeWarning):
                        self.assertIs(numeric.rope_solver('auto'), numeric.solve_rope)
                with self.assertRaises(type(failure)):
                    numeric.rope_solver('numba')
        numeric.rope_solver.cache_clear()

    def test_numba_matches_python_through_motion_supply_sleep_and_wake(self):
        try:
            numeric.compiled_rope_solver()
        except ImportError:
            self.skipTest('optional numba is not installed')
        for n in (20, 80):
            positions = [Vec2(i*2., 0.) for i in range(n)]
            ropes = [Rope(positions, [2.8]*(n-1), .2, .84, backend=b) for b in ('python', 'numba')]
            for tick in range(950):
                moving = tick < 160 or tick >= 930
                wave = sin(tick*.04)*10 if moving else 0.
                pins = {0: Vec2(wave, 0.), n-1: Vec2((n-1)*2+wave, cos(tick*.03)*4 if moving else 0.)}
                # 切换固定点集合覆盖中段导向；最后长时间停稳后再移动。
                if n == 80 and tick < 100:
                    pins[60] = Vec2(120+wave, 2.)
                for rope in ropes:
                    rope.step(pins, supply=((0, n-1, (n-1)*2.9),),
                              end_pull=(Vec2(60, 5), 120.), forces={1: Vec2(.03, .01)})
                a, b = ropes
                self.assertEqual(a.iterations, b.iterations)
                self.assertEqual(a.sleeping, b.sleeping)
                self.assertLess(max((p.position-q.position).length() for p, q in zip(a.points, b.points)), 1e-7)
                self.assertLess(max((p.velocity-q.velocity).length() for p, q in zip(a.points, b.points)), 1e-7)
            self.assertFalse(ropes[1].sleeping)


if __name__ == '__main__':
    unittest.main()
