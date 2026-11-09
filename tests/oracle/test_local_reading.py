"""游走关闭仍可局部阅读；矩阵共用方式，重复阅读不累计位移"""
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.behavior_config import ReadingConfig
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.shared.geometry import Vec2


class LocalReadingTests(unittest.TestCase):
    def scene(self, *, matrix=False, mode='orbit', **options):
        weights = {name+'_weight': 100 if name == mode else 0 for name in ('approach', 'recall', 'orbit')}
        config = OracleConfig(physics_backend='python', hide_cords=True, halo_enabled=False,
            pearl_matrix_enabled=matrix, pearl_matrix_count=4, pearl_fixed_count=0 if matrix else 1,
            pearl_playback_probability=0, reading=ReadingConfig(notice_min_seconds=.1, notice_max_seconds=.1,
                observe_min_seconds=.2, observe_max_seconds=.2, **weights), **options)
        scene = OracleScene(config)
        scene.appearance.step = lambda _: None
        self.until(scene, lambda: scene.arrived and scene.pose.settled and scene.observation_pearls_settled)
        scene.set_autonomous_movement(False)
        return scene

    def until(self, scene, predicate, budget=2200):
        for _ in range(budget):
            scene.step()
            if predicate():
                return
        self.fail(f'{scene.behavior.state}, mode={scene.behavior.mode}, target={scene.target}')

    def cycle(self, scene):
        b = scene.behavior
        before = b.completed_cycles
        self.assertTrue(b.notice(scene))
        pearl = scene.observed_pearl
        identity = pearl.color_slot, pearl.glyph_id
        space, states = b.reading_motion.box, set()
        for _ in range(2200):
            scene.step()
            states.add(b.state)
            point = scene.body.chunks[0].position
            self.assertTrue(space.contains(point, tolerance=1.5), (space, point))
            self.assertTrue(scene.body_region.segment_safe(scene.body.chunks[0].previous_position, point))
            self.assertTrue(pearl.region.segment_safe(pearl.previous_position, pearl.position))
            if b.completed_cycles > before:
                break
        self.assertEqual(b.completed_cycles, before+1)
        self.assertEqual(identity, (pearl.color_slot, pearl.glyph_id))
        self.assertLess((scene.body.chunks[0].position-b.reading_motion.anchor).length(), .05)
        self.assertTrue(scene.observation_returned)
        return states

    def test_three_modes_work_for_both_pearl_types_on_all_edges(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for matrix in (False, True):
                for mode, expected in (('approach', Activity.APPROACH), ('recall', Activity.RECALL), ('orbit', Activity.ORBIT)):
                    with self.subTest(side=side, matrix=matrix, mode=mode):
                        s = self.scene(matrix=matrix, mode=mode, base_side=side)
                        states = self.cycle(s)
                        self.assertIn(expected, states)
                        self.assertNotIn(Activity.CROSS_EDGE, states)
                        if matrix:
                            self.assertIsNone(s.pearl_matrix.extracted)
                            self.assertEqual(len(tuple(s.pearl_matrix.samples())), 4)

    def test_repeated_reads_keep_one_anchor_and_matrix_position(self):
        for matrix in (False, True):
            s = self.scene(matrix=matrix)
            origin = s.body.chunks[0].position
            anchor = s.pearl_matrix.anchor.position if matrix else None
            for _ in range(4):
                self.assertIn(Activity.ORBIT, self.cycle(s))
                self.assertEqual(s.behavior.reading_motion.anchor, origin)
                if matrix:
                    self.assertEqual(s.pearl_matrix.anchor.position, anchor)

    def test_switch_off_during_orbit_keeps_pearl_and_selected_mode(self):
        s = self.scene(matrix=True)
        s.set_autonomous_movement(True)
        s.behavior.notice(s)
        self.until(s, lambda: s.behavior.state == Activity.ORBIT)
        pearl = s.observed_pearl
        snapshot = tuple(c.position for c in s.body.chunks)
        s.set_autonomous_movement(False)
        self.assertEqual(tuple(c.position for c in s.body.chunks), snapshot)
        self.assertIs(s.observed_pearl, pearl)
        self.assertEqual(s.behavior.mode, 'orbit')
        self.until(s, lambda: s.behavior.completed_cycles == 1)
        self.assertLess((s.body.chunks[0].position-s.behavior.reading_motion.anchor).length(), .05)
        self.assertIsNone(s.pearl_matrix.extracted)

    def test_no_arc_falls_back_to_approach_and_no_position_to_recall(self):
        s = self.scene(matrix=True)
        with patch.object(s.navigator.planner, 'local_arc', return_value=None):
            states = self.cycle(s)
        self.assertIn(Activity.APPROACH, states)
        self.assertNotIn(Activity.ORBIT, states)
        with patch.object(s.behavior.reading_motion, '_candidates', return_value=[]):
            states = self.cycle(s)
        self.assertIn(Activity.RECALL, states)

    def test_drag_cancels_reading_and_new_placement_reanchors(self):
        s = self.scene(matrix=True)
        s.behavior.notice(s)
        self.until(s, lambda: s.behavior.state == Activity.ORBIT)
        pearl = s.observed_pearl
        old = s.behavior.reading_motion.anchor
        s.drag.set_enabled(True)
        self.assertTrue(s.drag.press(s.head.position, lambda _: True))
        self.assertIsNone(s.behavior.reading_motion.anchor)
        self.assertTrue(pearl.returning_home)
        s.drag.move(s.body.chunks[0].position+Vec2(120, 20))
        for _ in range(100):
            s.step()
        s.drag.release()
        self.until(s, lambda: not s.drag.controlling and s.arrived and s.pose.settled and s.observation_pearls_settled)
        placed = s.body.chunks[0].position
        self.assertGreater((placed-old).length(), 10)
        s.behavior.notice(s)
        self.assertLess((s.behavior.reading_motion.anchor-placed).length(), .001)

    def test_resize_preserves_and_projects_rest_anchor(self):
        s = self.scene(matrix=True)
        s.behavior.notice(s)
        self.until(s, lambda: s.behavior.state == Activity.ORBIT)
        anchor = s.behavior.reading_motion.anchor
        new = OracleDesktopMotion(s.config, OracleDesktopViewport(0, 0, 1280, 680), s).scene
        expected = new.project_target(Vec2(anchor.x/s.world.width*new.world.width,
                                           anchor.y/s.world.height*new.world.height))
        self.assertEqual(new.behavior.reading_motion.anchor, expected)
        self.assertEqual(new.target, expected)
        self.assertFalse(new.behavior.movement_enabled)
        self.assertIsNone(new.pearl_matrix.extracted)

    def test_temporary_lean_does_not_move_the_persistent_anchor(self):
        s = self.scene()
        origin = s.body.chunks[0].position
        offset = Vec2(8, -4)
        s.mouse_reaction.avoidance.offset = offset
        for chunk in s.body.chunks:
            chunk.position = chunk.position+offset
        s.behavior.notice(s, stationary=True)
        self.assertEqual(s.behavior.reading_motion.anchor, origin)
        self.assertIsNone(s.behavior.reading_motion.return_to)


if __name__ == '__main__':
    unittest.main()
