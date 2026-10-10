"""桌面移动开关不关闭原地互动；切换、中断、拖拽与重建保持各自的许可。"""
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class StationaryBehaviorTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(OracleConfig(physics_backend='python', hide_cords=True,
                                        halo_enabled=False, **settings))
        scene.appearance.step = lambda _: None
        return scene

    def until(self, scene, condition, limit=3000):
        for _ in range(limit):
            scene.step()
            if condition():
                return
        self.fail(f'{scene.behavior.state}: arrived={scene.arrived}')

    def test_random_stationary_cycles_recall_fixed_and_matrix_pearls_without_travel(self):
        for matrix in (False, True):
            with self.subTest(matrix=matrix):
                scene = self.scene(pearl_matrix_enabled=matrix, pearl_fixed_count=0 if matrix else 1)
                self.until(scene, lambda: scene.arrived and scene.observation_pearls_settled)
                scene.set_autonomous_movement(False)
                behavior, origin = scene.behavior, scene.target
                behavior.IDLE_TICKS = (4, 8)
                behavior.LONG_IDLE_TICKS = (12, 20)
                behavior.OBSERVE_TICKS = (12, 20)
                behavior.MEDITATE_TICKS = (12, 20)
                states, max_distance = set(), 0.
                for _ in range(8000):
                    scene.step()
                    states.add(behavior.state)
                    max_distance = max(max_distance, (scene.body.chunks[0].position-origin).length())
                    self.assertLess((scene.target-origin).length(), 2.)
                    self.assertEqual(scene.navigator.route.length, 0.)
                    if behavior.completed_cycles >= 2:
                        break
                self.assertGreaterEqual(behavior.completed_cycles, 2)
                self.assertTrue({Activity.NOTICE, Activity.RECALL, Activity.OBSERVE, Activity.RETURN} <= states)
                self.assertTrue(states <= {Activity.IDLE, Activity.MEDITATE, Activity.NOTICE,
                                           Activity.RECALL, Activity.OBSERVE, Activity.RETURN})
                self.assertLess(max_distance, 2., '只保留阅读时的轻微姿态响应')
                self.assertTrue(behavior.enabled)
                self.assertFalse(behavior.movement_enabled)
                self.assertTrue(scene.observation_returned)

    def test_matrix_overlap_does_not_force_stationary_puppet_to_roam(self):
        scene = self.scene(pearl_matrix_enabled=True)
        self.until(scene, lambda: scene.arrived and scene.observation_pearls_settled)
        scene.set_autonomous_movement(False)
        behavior = scene.behavior
        behavior.duration = 0
        with patch.object(behavior, 'matrix_clear', return_value=False), \
                patch.object(behavior, 'choose_activity', return_value=Activity.NOTICE), \
                patch.object(behavior, 'start_roam') as roam:
            scene.step()
            self.assertEqual(behavior.state, Activity.NOTICE)
            self.assertEqual(behavior.mode, 'recall')
            roam.assert_not_called()

    def test_disabling_during_movement_brakes_without_teleporting(self):
        for action in ('roam', 'drift'):
            with self.subTest(action=action):
                scene = self.scene()
                getattr(scene, action)()
                scene.set_autonomous(True)
                for _ in range(180):
                    scene.step()
                snapshot = [(c.position, c.velocity) for c in scene.body.chunks]
                scene.set_autonomous_movement(False)
                self.assertEqual(snapshot, [(c.position, c.velocity) for c in scene.body.chunks])
                self.assertFalse(scene.behavior.drift_active)
                self.assertEqual(scene.behavior.state, Activity.IDLE)
                stopped_target = scene.target
                with patch.object(scene.behavior, 'choose_activity', return_value=Activity.IDLE):
                    self.until(scene, lambda: scene.arrived and scene.pose.settled)
                self.assertEqual(scene.target, stopped_target)
                self.assertEqual(scene.navigator.route.length, 0.)

    def test_disabling_approach_recalls_same_pearl_and_preserves_reading(self):
        scene = self.scene()
        scene.observe_pearl('approach')
        scene.set_autonomous(True)
        self.until(scene, lambda: scene.behavior.state == Activity.APPROACH)
        pearl = scene.observed_pearl
        scene.set_autonomous_movement(False)
        self.assertIs(scene.observed_pearl, pearl)
        self.assertEqual(scene.behavior.state, Activity.RECALL)
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        before = (scene.behavior.state_ticks, scene.behavior.duration, scene.eyes.random.getstate(), scene.target)
        scene.set_autonomous_movement(True)
        scene.set_autonomous_movement(False)
        self.assertEqual(before, (scene.behavior.state_ticks, scene.behavior.duration,
                                  scene.eyes.random.getstate(), scene.target))
        self.assertIs(scene.observed_pearl, pearl)
        self.assertEqual(scene.behavior.state, Activity.OBSERVE)
        # 开关重新开启后移动分支仍可被正常选择。
        scene.set_autonomous_movement(True)
        with patch.object(scene.behavior.random, 'random', return_value=0.):
            self.assertEqual(scene.behavior.choose_activity(scene), Activity.CROSS_EDGE)

    def test_drag_recovery_and_resize_preserve_stationary_policy(self):
        scene = self.scene()
        scene.set_autonomous_movement(False)
        scene.drag.set_enabled(True)
        scene.drag.press(scene.head.position, lambda _: True)
        scene.drag.move(scene.body.chunks[0].position+Vec2(50, 40))
        for _ in range(45):
            scene.step()
        scene.set_autonomous_movement(True)
        scene.set_autonomous_movement(False)
        self.assertFalse(scene.behavior.enabled)
        self.assertTrue(scene.drag.resume_autonomy)
        scene.drag.release()
        self.until(scene, lambda: not scene.drag.controlling)
        self.assertTrue(scene.behavior.enabled)
        self.assertFalse(scene.behavior.movement_enabled)
        new = OracleDesktopMotion(scene.config, OracleDesktopViewport(-1280, 40, 1280, 680, 1.5), scene).scene
        self.assertTrue(new.behavior.enabled)
        self.assertFalse(new.behavior.movement_enabled)

    def test_stationary_idle_still_sleeps_with_behavior_loop_running(self):
        scene = OracleScene(OracleConfig(physics_backend='python', hide_cords=True,
                                        halo_enabled=False, pearl_fixed_count=0))
        scene.set_autonomous_movement(False)
        with patch.object(scene.behavior, 'choose_activity', return_value=Activity.IDLE):
            for _ in range(800):
                scene.step()
            self.assertTrue(scene.appearance.sleeping)
            revision = (scene.appearance.revision, scene.eyes.revision, scene.pearl_visual_revision)
            for _ in range(300):
                scene.step()
            self.assertEqual(revision, (scene.appearance.revision, scene.eyes.revision, scene.pearl_visual_revision))


if __name__ == '__main__':
    unittest.main()
