from dataclasses import replace
import unittest

from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer, State


class RetractionTests(unittest.TestCase):
    def watch(self, model):
        model.show()
        for _ in range(64):
            model.step()
        self.assertEqual(model.state, State.WATCHING)

    def test_cycle_and_hidden_event_does_not_advance_appearance(self):
        model = Overseer()
        self.watch(model)
        root = model.root
        model.request_withdraw()
        self.assertEqual(model.extended, 1)  # 请求不会重置姿态或跳帧。
        model.step()
        self.assertEqual(model.state, State.WITHDRAWING)
        for _ in range(50):
            model.step()
        self.assertEqual(model.state, State.HIDDEN)
        self.assertTrue(model.active)
        self.assertFalse(model.visible)
        snapshot = model.random.getstate(), model.time, model.revision
        for _ in range(100):
            model.step(threat=model.root)
        self.assertEqual((model.random.getstate(), model.time, model.revision), snapshot)
        model.request_emerge()
        model.step(threat=model.root)
        self.assertEqual(model.extended, 0)  # 手动探出不能绕过避让。
        for _ in range(100):
            model.step()
        self.assertEqual(model.state, State.WATCHING)
        self.assertEqual(model.root, root)
        model.clear()
        for _ in range(100):
            model.step()
        self.assertFalse(model.active)
        self.assertEqual(model.state, State.HIDDEN)

    def test_hysteresis_and_uninterrupted_safe_wait(self):
        model = Overseer()
        self.watch(model)
        for i in range(160):
            distance = 59.5 if i % 2 else 60.5
            model.step(threat=model.root+model.normal*distance)
        self.assertEqual(model.extended, 0)
        self.assertTrue(model.scared)
        for i in range(160):
            distance = 99.5 if i % 2 else 100.5
            model.step(threat=model.root+model.normal*distance)
            self.assertEqual(model.extended, 0)
        far = model.root+model.normal*101
        for _ in range(17):
            model.step(threat=far)
        self.assertTrue(model.scared)
        model.step(threat=model.root+model.normal*90)
        self.assertEqual(model.safe_time, 0)
        for _ in range(18):
            model.step(threat=far)
        self.assertFalse(model.scared)
        self.assertEqual(model.state, State.EMERGING)

    def test_fast_reversals_keep_geometry_and_velocity_continuous_on_all_edges(self):
        for edge in Edge:
            model = Overseer(Bounds(0, 0, 600, 600),
                replace(OverseerConfig(), safe_delay=0, emerge_seconds=.8, withdraw_seconds=.8))
            model.show(anchor=Anchor(edge, .5))
            root = model.root
            self.assertEqual(model.state, State.HIDDEN)
            reversals = set()
            for i in range(300):
                # 起始伸展、快速靠近又离开、缩回途中再靠近。
                near = i % 60 in range(20, 25) or i % 60 in range(28, 34)
                threat = root+model.normal*(20 if near else 200)
                old_eye = model.eye_position()
                old_points = [model.stem(t/10) for t in range(11)]
                velocity = model.extension_velocity
                model.step(root+model.normal*300, threat=threat)
                reversals.add(model.state)
                self.assertEqual(model.root, root)
                self.assertLess((model.eye_position(0)-old_eye).length(), 1e-8)
                self.assertLess((model.eye_position()-old_eye).length(), 6)
                for j, p in enumerate(old_points):
                    self.assertLess((model.stem(j/10, 0)-p).length(), 1e-8)
                self.assertLess(abs(model.extension_velocity-velocity), 2.5)
                self.assertGreaterEqual(model.extended, 0)
                self.assertLessEqual(model.extended, 1)
            self.assertIn(State.EMERGING, reversals)
            self.assertIn(State.WITHDRAWING, reversals)

    def test_look_target_is_not_implicitly_a_threat(self):
        model = Overseer()
        self.watch(model)
        for _ in range(100):
            model.step(model.root)
        self.assertFalse(model.scared)
        self.assertEqual(model.extended, 1)
        model.step(model.root+Vec2(200, 200), threat=model.root)
        self.assertTrue(model.scared)

    def test_puppet_avoidance_and_mouse_both_must_be_safe_on_all_edges(self):
        for edge in Edge:
            model = Overseer()
            model.show(anchor=Anchor(edge, .5))
            for _ in range(64):
                model.step()
            root, normal = model.root, model.normal
            for i in range(80):
                model.step(puppet=root+normal*(99 if i % 2 else 101))
            self.assertTrue(model.scared)
            self.assertFalse(model.visible)
            for i in range(80):
                model.step(puppet=root+normal*(149 if i % 2 else 151))
            self.assertFalse(model.visible)
            # 鼠标还在安全圈内时，人偶离开也不能解除避让，反之亦然。
            for _ in range(30):
                model.step(threat=root+normal*80, puppet=root+normal*200)
            self.assertEqual(model.safe_time, 0)
            for _ in range(30):
                model.step(threat=root+normal*200, puppet=root+normal*120)
            self.assertEqual(model.safe_time, 0)
            for _ in range(17):
                model.step(threat=root+normal*200, puppet=root+normal*200)
            self.assertTrue(model.scared)
            model.step(threat=root+normal*200, puppet=root+normal*200)
            self.assertFalse(model.scared)
            self.assertEqual(model.state, State.EMERGING)

    def test_different_motion_speeds_do_not_jump_at_a_reversal_endpoint(self):
        model = Overseer(config=replace(OverseerConfig(), emerge_seconds=40))
        model.show()
        model.extended = model.last_extended = .03
        model.extension_velocity = -3.  # 快速缩回接近墙内时，请求很慢地探出。
        model.request_emerge()
        model.step()
        self.assertEqual(model.extended, 0)
        self.assertEqual(model.extension_velocity, 0)
        model.step()
        self.assertLess(model.extended, .001)


if __name__ == '__main__':
    unittest.main()
