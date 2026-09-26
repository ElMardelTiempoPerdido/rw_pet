import unittest

from rw_creature_pet.interaction.drag import DragController, DragHandle, follow_velocity
from rw_creature_pet.shared.geometry import Vec2


class DragTests(unittest.TestCase):
    def test_only_press_picks_and_keeps_original_offset(self):
        c = DragController()
        calls = []
        def pick(point):
            calls.append(point)
            return DragHandle('body', Vec2(12, 10)) if point.x == 10 else None
        self.assertFalse(c.press(Vec2(), pick))
        c.move(Vec2(10, 10))
        self.assertFalse(c.active)
        self.assertEqual(len(calls), 1)
        self.assertTrue(c.press(Vec2(10, 10), pick))
        c.move(Vec2(20, 30))
        self.assertEqual(c.target, Vec2(22, 30))
        self.assertFalse(c.press(Vec2(10, 10), pick))
        self.assertEqual(len(calls), 2)
        self.assertEqual(c.release().key, 'body')
        c.move(Vec2(10, 10))
        self.assertFalse(c.active)

    def test_damped_follow_is_bounded_and_settles(self):
        p, v = Vec2(), Vec2()
        goal = Vec2(100, 20)
        for _ in range(200):
            new = follow_velocity(p, v, goal)
            self.assertLessEqual((new-v).length(), .800001)
            self.assertLessEqual(new.length(), 7.000001)
            v = new
            p = p+v
        self.assertLess((p-goal).length(), .001)
        self.assertLess(v.length(), .001)
