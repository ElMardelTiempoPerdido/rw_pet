"""摸摸只拦截新自主行动，当前路线与读珠流程可以完整收尾"""
from random import Random
import unittest
from unittest.mock import patch

from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.behavior_config import ReadingConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2


class PettingBehaviorTests(unittest.TestCase):
    def scene(self, **kwargs):
        scene = OracleScene(OracleConfig(physics_backend='python', hide_cords=True, halo_enabled=False,
            reading=ReadingConfig(notice_min_seconds=.6, notice_max_seconds=.6,
                                  observe_min_seconds=.3, observe_max_seconds=.3), **kwargs))
        scene.appearance.step = lambda _: None
        scene.mouse_reaction.configure(scene, InteractionConfig(
            hover_probability=0, petting_seconds=.3, petting_grace_seconds=.4))
        for _ in range(400):
            scene.step()
        self.assertTrue(scene.arrived and scene.pose.settled and scene.observation_pearls_settled)
        return scene

    def stroke(self, scene, ticks=1):
        for _ in range(ticks):
            self.motion_tick = getattr(self, 'motion_tick', 0)+1
            offset = Vec2(2 if self.motion_tick % 2 else -2, 0)
            scene.mouse_reaction.sample_input(scene.head.position+offset, inside=True, motion_pointer=offset)
            scene.step()

    def until(self, scene, predicate, limit=4000):
        for _ in range(limit):
            self.stroke(scene)
            if predicate():
                return
        self.fail(f'{scene.behavior.state}: arrived={scene.arrived}')

    @staticmethod
    def random_states(behavior):
        return {name: value.getstate() for name, value in vars(behavior).items() if isinstance(value, Random)}

    def test_idle_blocks_selection_and_matrix_avoidance_through_grace_then_resumes(self):
        for movement in (False, True):
            with self.subTest(movement=movement):
                scene = self.scene()
                scene.set_autonomous_movement(movement)
                behavior = scene.behavior
                self.stroke(scene, 13)
                self.assertTrue(scene.mouse_reaction.petting.active)
                behavior.duration = 0
                before = self.random_states(behavior), behavior.state_ticks, scene.target
                with patch.object(behavior, 'choose_activity', return_value=Activity.NOTICE) as choose, \
                        patch.object(behavior, 'start_roam') as roam, \
                        patch.object(behavior, 'matrix_clear', return_value=False):
                    self.stroke(scene, 80)
                    scene.mouse_reaction.sample_input(None, inside=False)
                    for _ in range(10):
                        scene.step()
                    self.assertTrue(scene.mouse_reaction.petting.active)
                    choose.assert_not_called()
                    roam.assert_not_called()
                self.assertEqual(before, (self.random_states(behavior), behavior.state_ticks, scene.target))
                self.assertTrue(behavior.enabled)
                self.assertEqual(behavior.movement_enabled, movement)
                with patch.object(behavior, 'choose_activity', return_value=Activity.NOTICE) as choose:
                    for _ in range(6):
                        scene.step()
                    self.assertFalse(scene.mouse_reaction.petting.active)
                    choose.assert_called_once()
                    self.assertEqual(behavior.state, Activity.NOTICE)

    def test_movement_and_crossing_finish_then_wait_without_selecting_again(self):
        for adjacent in (False, True):
            with self.subTest(adjacent=adjacent):
                scene = self.scene()
                self.assertTrue(scene.roam(adjacent=adjacent))
                scene.set_autonomous(True)
                behavior = scene.behavior
                self.stroke(scene, 13)
                self.assertTrue(scene.mouse_reaction.petting.active)
                target, route = scene.target, scene.navigator.route
                with patch.object(behavior, 'choose_activity') as choose:
                    self.until(scene, lambda: behavior.state == Activity.IDLE)
                    self.assertLess((scene.body.chunks[0].position-target).length(), 2.)
                    self.assertTrue(route.length > 0.)
                    self.assertTrue(scene.arrived)
                    behavior.duration = 0
                    self.stroke(scene, 80)
                    choose.assert_not_called()
                    self.assertEqual(behavior.state, Activity.IDLE)

    def test_drift_finishes_current_curve_without_joining_reading_or_crossing_and_can_expire(self):
        scene = self.scene(cross_edge_probability=1.)
        scene.drift()
        behavior = scene.behavior
        behavior.drift_next_move = behavior.drift_next_observation = 100000
        behavior.drift_move_to(scene, scene.body.chunks[0].position+Vec2(90, 0))
        self.stroke(scene, 13)
        self.assertTrue(scene.mouse_reaction.petting.active)
        behavior.drift_next_move = behavior.drift_next_observation = behavior.drift_next_cross_check = 0
        behavior.cross_cooldown = 0
        behavior.drift_bout_until = behavior.drift_duration
        target, route, tick = scene.target, scene.navigator.route, behavior.drift_ticks
        streams = self.random_states(behavior)
        with patch.object(behavior, 'continue_drift') as join, \
                patch.object(behavior, 'notice') as notice, \
                patch.object(behavior, 'try_drift_crossing') as crossing, \
                patch.object(behavior, 'drift_point') as point:
            self.until(scene, lambda: scene.arrived)
            self.stroke(scene, 80)
            for method in (join, notice, crossing, point):
                method.assert_not_called()
        self.assertIs(scene.navigator.route, route)
        self.assertEqual(scene.target, target)
        self.assertGreater(behavior.drift_ticks, tick)
        self.assertEqual(self.random_states(behavior), streams)
        self.assertTrue(behavior.drift_active)
        behavior.drift_duration = behavior.drift_ticks+1
        self.until(scene, lambda: not behavior.drift_active)
        self.assertEqual(behavior.state, Activity.IDLE)
        self.assertTrue(scene.pose.settled)
        self.assertEqual(scene.pose.weightlessness, 0.)

    def test_active_drift_crossing_reaches_neighbor_before_waiting(self):
        scene = self.scene()
        scene.drift()
        behavior = scene.behavior
        self.assertTrue(behavior.start_drift_crossing(scene, target_edge=1))
        scene.set_autonomous(True)
        self.stroke(scene, 13)
        self.assertEqual(behavior.state, Activity.DRIFT_CROSS_EDGE)
        self.until(scene, lambda: behavior.state == Activity.DRIFT)
        self.assertEqual(behavior.drift_edge, 1)
        target = scene.target
        behavior.drift_next_move = behavior.drift_next_observation = 0
        self.stroke(scene, 80)
        self.assertEqual(behavior.state, Activity.DRIFT)
        self.assertEqual(scene.target, target)
        self.assertTrue(scene.arrived)

    def test_reading_fixed_or_matrix_pearl_completes_and_returns_during_petting(self):
        for matrix in (False, True):
            for drifting in (False, True):
                with self.subTest(matrix=matrix, drifting=drifting):
                    scene = self.scene(pearl_matrix_enabled=matrix, pearl_fixed_count=0 if matrix else 1)
                    if drifting:
                        scene.drift()
                    start = scene.observe_matrix_pearl if matrix else lambda: scene.observe_pearl('recall')
                    self.assertTrue(start())
                    scene.set_autonomous(True)
                    behavior = scene.behavior
                    pearl = scene.observed_pearl
                    self.stroke(scene, 13)
                    self.assertTrue(scene.mouse_reaction.petting.active)
                    self.assertEqual(behavior.state, Activity.NOTICE)
                    visited = {behavior.state}
                    with patch.object(behavior, 'notice') as notice:
                        for _ in range(4000):
                            self.stroke(scene)
                            visited.add(behavior.state)
                            if behavior.completed_cycles:
                                break
                            self.assertIs(scene.observed_pearl, pearl)
                        self.assertEqual(behavior.completed_cycles, 1)
                        self.assertTrue({Activity.RECALL, Activity.OBSERVE, Activity.RETURN} <= visited)
                        self.assertTrue(scene.observation_returned)
                        if matrix:
                            self.assertIsNone(scene.pearl_matrix.extracted)
                        behavior.duration = 0
                        behavior.drift_next_move = behavior.drift_next_observation = 0
                        self.stroke(scene, 80)
                        notice.assert_not_called()
                        self.assertEqual(behavior.completed_cycles, 1)
                        self.assertEqual(behavior.state, Activity.DRIFT if drifting else Activity.IDLE)

    def test_manual_reading_still_allowed_while_petting(self):
        scene = self.scene()
        self.stroke(scene, 13)
        self.assertTrue(scene.mouse_reaction.petting.active)
        self.assertTrue(scene.observe_pearl('recall'))
        self.until(scene, lambda: scene.behavior.completed_cycles == 1)
        self.assertTrue(scene.observation_returned)


if __name__ == '__main__':
    unittest.main()
