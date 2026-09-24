"""软线受力、动态连接、有限松弛与停止收敛。"""
import unittest

from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle import OracleScene
from rw_creature_pet.oracle_config import OracleConfig
from rw_creature_pet.oracle_cords import Rope


class OracleCordTests(unittest.TestCase):
    def test_rope_sags_under_gravity_settles_and_wakes(self):
        points = [Vec2(i*3., 0) for i in range(21)]
        rope = Rope(points, [3.8]*20, .2, .84)
        pins = {0: points[0], 20: points[-1]}
        for _ in range(500):
            rope.step(pins)
        self.assertGreater(rope.points[10].position.y, 15.)
        self.assertTrue(rope.sleeping)
        self.assertLess(max(abs((b.position-a.position).length()-rest)
                            for a, b, rest in zip(rope.points, rope.points[1:], rope.rest)), .2)
        old = [p.position for p in rope.points]
        for _ in range(100):
            rope.step(pins)
        self.assertEqual([p.position for p in rope.points], old)
        rope.step({0: Vec2(-2, 0), 20: points[-1]})
        self.assertFalse(rope.sleeping)
        self.assertEqual(rope.points[0].position, Vec2(-2, 0))

    def test_fine_cords_keep_different_lengths_and_free_junction(self):
        scene = OracleScene()
        for _ in range(650):
            scene.step()
        a = scene.appearance
        self.assertGreater((a.main_cord[-1].position-scene.arm.joints[-1].position).length(), 3.)
        radius = (a.main_cord[-1].position-a.upper).length()
        self.assertGreater(radius, 80., '柔性拉回允许重力造成少量越界，不钉在圆周上')
        self.assertLess(radius, 86.)
        self.assertGreater((a.main_cord[27].position-scene.arm.joints[1].position).length(), 3.)
        lengths = [sum((q.position-p.position).length() for p, q in zip(c, c[1:]))
                   for c in a.small_cords]
        self.assertGreater(max(lengths)-min(lengths), 70.)
        self.assertGreater(max(p.position.y-a.upper.y for c in a.small_cords for p in c), 100.,
                           '最长细线应露出衣摆，形成超过百单位的自然垂弧')
        self.assertGreater(sum(a.cords.main.rest[60:]), 185.)
        self.assertLess(sum(a.cords.main.rest), 400., '桌面供线不直接套用原版总长 790')
        self.assertTrue(a.sleeping)
        for cord in a.small_cords:
            self.assertEqual(cord[0].position, a.main_cord[-1].position)
            self.assertEqual(cord[-1].position, a.head.position)
        original_lengths = a.cords.fine_lengths.copy()
        scene.reset()
        self.assertEqual(scene.appearance.cords.fine_lengths, original_lengths)

    def test_full_lap_keeps_connections_and_bounded_slack(self):
        # 长线允许局部垂入活动带外；仍防止跨越中央、绳段拉长或端点断开。
        scene = OracleScene(OracleConfig(world_width=640, world_height=480, arm_scale=.75))
        scene.start_lap()
        peak = 0.
        fine_peak = 0.
        penetration = 0.
        for tick in range(1500):
            scene.step()
            a = scene.appearance
            self.assertEqual(a.main_cord[0].position, scene.base)
            self.assertEqual(a.main_cord[60].position, a.cords.guide)
            self.assertLess((a.main_cord[-1].position-a.upper).length(), 112.)
            for p, q, rest in zip(a.main_cord, a.main_cord[1:], a.cords.main.rest):
                peak = max(peak, abs((q.position-p.position).length()-rest))
            h = scene.world.inner
            for p in a.main_cord:
                v = p.position
                penetration = max(penetration, min(v.x-h.left, h.right-v.x, v.y-h.top, h.bottom-v.y))
            for cord, rope in zip(a.small_cords, a.cords.fine):
                self.assertEqual(cord[0].position, a.main_cord[-1].position)
                self.assertEqual(cord[-1].position, a.head.position)
                for p, q, rest in zip(cord, cord[1:], rope.rest):
                    fine_peak = max(fine_peak, abs((q.position-p.position).length()-rest))
                for p in cord:
                    self.assertLess((p.position-a.upper).length(), 160.)
                    v = p.position
                    penetration = max(penetration, min(v.x-h.left, h.right-v.x, v.y-h.top, h.bottom-v.y))
        self.assertLess(peak, 1.2, '低迭代仍须及时传递牵引，不能靠明显拉伸省计算')
        self.assertLess(fine_peak, 1.2, '分线端移动时应及时供线，不能把不足的长度集中到末段')
        self.assertLess(penetration, 120., '允许较长的局部下垂，不应形成跨中央的长线')

    def test_sleep_ignores_noise_but_wakes_for_accumulated_motion(self):
        points = [Vec2(i*3., 0) for i in range(21)]
        rope = Rope(points, [3.8]*20, .2, .84)
        pins = {0: points[0], 20: points[-1]}
        for _ in range(500):
            rope.step(pins)
        self.assertTrue(rope.sleeping)
        rope.step({0: points[0]+Vec2(.0001, 0), 20: points[-1]})
        self.assertTrue(rope.sleeping)
        self.assertEqual(rope.iterations, 0)
        for k in range(1, 21):
            rope.step({0: points[0]+Vec2(k*.0001, 0), 20: points[-1]})
        self.assertFalse(rope.sleeping, '累计小移动必须唤醒，不能每帧重置容差参考')


if __name__ == '__main__':
    unittest.main()
