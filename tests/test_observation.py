import unittest
from math import atan2, degrees
from rw_creature_pet.config import DebugConfig
from rw_creature_pet.scene import DebugScene
from rw_creature_pet.geometry import Vec2


class ObservationTests(unittest.TestCase):
    def test_low_rest_and_variable_raise_preserve_grips_and_straight_trunk(self):
        for facing in (1, -1):
            s = DebugScene(DebugConfig())
            s.gait.enabled = True
            if facing < 0:
                s.gait.set_speed(-.65)
                for _ in range(110): s.step()
                s.gait.set_speed(0)
            for _ in range(300): s.step()
            feet = [f.position for f in s.feet]
            for posture, angle in (('low', 0), ('raised', 8), ('raised', 22), ('raised', 0), ('low', 0)):
                s.gait.posture = posture
                s.gait.set_chest_angle(angle)
                for _ in range(700):
                    old = [c.position for c in s.body.chunks]
                    s.step()
                    self.assertEqual(feet, [f.position for f in s.feet])
                    self.assertLess(max((c.position-p).length() for c,p in zip(s.body.chunks,old)), 1)
                front, middle, rear = [c.position for c in s.body.chunks]
                actual = degrees(atan2(rear.y-front.y, abs(front.x-rear.x)))
                self.assertAlmostEqual(actual, angle, delta=.1)
                self.assertLess((middle-front.lerp(rear,.5)).length(), .01)
                self.assertAlmostEqual(s.world.floor_y-rear.y, 9.5, delta=.05)
                self.assertLess(max(c.velocity.length() for c in s.body.chunks), 1e-7)
                self.assertLess(max(t.velocity.length() for t in s.appearance.tail), 1e-6)
            s.gait.set_speed(.65*facing)
            start = s.body.chunks[1].position.x
            for _ in range(150): s.step()
            self.assertGreater((s.body.chunks[1].position.x-start)*facing, 60)
            self.assertLess(s.gait.rest_blend, .001)

    def test_raised_rest_fixed_feet_and_resume(self):
        s = DebugScene(DebugConfig())
        s.gait.enabled = True
        s.gait.set_speed(0)
        for _ in range(200): s.step()
        feet = [f.position for f in s.feet]
        s.gait.posture = 'raised'
        for _ in range(500): s.step()
        self.assertGreater(s.body.chunks[2].position.y-s.body.chunks[0].position.y, 7)
        self.assertEqual(feet, [f.position for f in s.feet])
        positions = [c.position for c in s.body.chunks]
        for _ in range(2400): s.step()
        self.assertTrue(all((c.position-p).length()<1e-6 for c,p in zip(s.body.chunks,positions)))
        self.assertLess(max(s.body.connection_error(c) for c in s.body.connections), .002)
        s.gait.set_speed(.65)
        for _ in range(200): s.step()
        self.assertLess(s.gait.chest_blend, .001)

    def test_observation_is_independent_limited_expires(self):
        a,b = DebugScene(DebugConfig()),DebugScene(DebugConfig())
        for s in (a,b):
            s.gait.enabled=True
            s.gait.set_speed(0)
        for _ in range(200): a.step(); b.step()
        # 使用侧前方目标验证抬头；后方目标现在受原版风格的回正抑制。
        a.appearance.observe(Vec2(275,20), 200)
        for _ in range(150):
            old=a.appearance.head.position
            a.step();b.step()
            self.assertEqual(a.body.chunks,b.body.chunks)
            self.assertLessEqual(abs(a.appearance.look_angle),1.2)
            self.assertLess((a.appearance.head.position-old).length(),2)
        self.assertLess(a.appearance.head.position.y,b.appearance.head.position.y-5)
        for _ in range(300): a.step();b.step()
        self.assertIsNone(a.appearance.look_target)
        self.assertLess((a.appearance.head.position-b.appearance.head.position).length(),1e-5)
        a.appearance.observe(Vec2(100,40));a.reset()
        self.assertIsNone(a.appearance.look_target)
