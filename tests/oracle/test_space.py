"""高倍率空间计算、真实倍率和宽活动带导航回归"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import isfinite
import unittest

from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.space import SpaceAssessment, minimum_world_size
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.behavior.controller import Activity
from rw_creature_pet.oracle.ui.desktop import OracleDesktopMotion, OracleDesktopViewport, current_anchor


class SpaceTests(unittest.TestCase):
    def test_small_world_comfort_and_hard_limits_are_separate(self):
        info = SpaceAssessment(640, 385, .6, .2)
        self.assertTrue(info.valid)
        self.assertFalse(info.baseline_fits)
        self.assertAlmostEqual(info.clearance, 5.)
        self.assertEqual(info.recommendation, (.6, .3))
        info = replace(info, arm_scale=.75)
        self.assertFalse(info.valid)
        self.assertEqual(info.recommendation, (.75, .3))
        self.assertAlmostEqual(replace(info, fraction=.3).clearance, 34.5)
        self.assertTrue(replace(info, arm_scale=.65).valid)

    def test_recommendation_preserves_wider_band_and_only_shrinks_arm_when_needed(self):
        self.assertEqual(SpaceAssessment(640, 385, .75, .45).recommendation, (.75, .45))
        self.assertEqual(SpaceAssessment(640, 210, .75, .2).recommendation, (.4, .499))
        self.assertIsNone(SpaceAssessment(640, 180, .6, .2).recommendation)
        for width, height in ((640, 385), (385, 640), (400, 280), (300, 210)):
            for arm in (.35, .6, .65, .75):
                info = SpaceAssessment(width, height, arm, .2)
                recommendation = info.recommendation
                if recommendation:
                    proposed = replace(info, arm_scale=recommendation[0], fraction=recommendation[1])
                    self.assertTrue(proposed.valid)
                    self.assertGreaterEqual(proposed.clearance, 32.-1e-7)

    def test_selected_edges_and_matrix_minimum_reserve(self):
        info = SpaceAssessment(640, 200, .35, .2, ('left',))
        self.assertTrue(info.valid)
        self.assertFalse(replace(info, edges=('top',)).valid)
        self.assertFalse(replace(info, height=190).valid)
        # 活动带足够宽，但长臂在极小场景转角仍可能短暂无解
        self.assertFalse(SpaceAssessment(240, 200, .6, .499).valid)

    def test_true_four_times_at_150_percent_dpi_and_temporary_fallback(self):
        cfg = OracleConfig(arm_scale=.75, edge_fraction=.3)
        viewport = OracleDesktopViewport(-1707, 0, 1707, 1027, 1.5, 4.).with_settings(cfg)
        self.assertEqual(viewport.physical_scale, 4.)
        self.assertAlmostEqual(viewport.world_size.x, 640.125)
        self.assertAlmostEqual(viewport.world_size.y, 385.125)
        self.assertEqual(viewport.assessment.recommendation, (.75, .3))
        cramped = replace(viewport, edge_fraction=.2)
        self.assertFalse(cramped.assessment.valid)
        self.assertLess(cramped.physical_scale, 4.)
        self.assertEqual(cramped.requested_scale, 4.)
        self.assertAlmostEqual(cramped.world_size.y, minimum_world_size(.75, .2)[1])
        self.assertEqual(replace(cramped, height=1500).physical_scale, 4.)
        motion = OracleDesktopMotion(replace(cfg, edge_fraction=.2), viewport)
        self.assertLess(motion.viewport.physical_scale, 4.)
        self.assertTrue(motion.scene.body_region.contains(motion.scene.body.chunks[0].position))

    def test_config_accepts_small_valid_world_and_rejects_degenerate_band(self):
        OracleConfig(world_width=640, world_height=385, edge_fraction=.499, arm_scale=.75)
        for changes in ({'edge_fraction': .5}, {'edge_fraction': .501},
                        {'world_height': 385, 'arm_scale': .75}, {'world_width': 100}):
            with self.assertRaises(ValueError):
                OracleConfig(**changes)

    def test_fallback_at_narrow_band_boundary_can_complete_a_lap(self):
        motion = OracleDesktopMotion(OracleConfig(arm_scale=.75, edge_fraction=.2,
            pearl_matrix_enabled=True, pearl_orbits_enabled=True, hide_cords=True),
            OracleDesktopViewport(0, 0, 1707, 1027, 1.5, 4.))
        scene = motion.scene
        scene.set_autonomous(False)
        self.assertLess(motion.viewport.physical_scale, 4.)
        self.assertAlmostEqual(scene.world.height, 410.)
        scene.start_lap()
        for tick in range(3600):
            scene.step()
            self.assertTrue(scene.body_region.contains(scene.body.chunks[0].position))
            self.assertLess(scene.arm.constraint_error, .2)
            if scene.arrived:
                break
        self.assertLess(tick, 3599)

    def test_wide_bands_complete_laps_and_settle_with_full_appearance(self):
        for fraction, side in ((.3, 'top'), (.45, 'right'), (.499, 'bottom')):
            with self.subTest(fraction=fraction):
                scene = OracleScene(OracleConfig(world_width=640, world_height=385, arm_scale=.75,
                    edge_fraction=fraction, base_side=side, pearl_matrix_enabled=True,
                    pearl_orbits_enabled=True, pearl_fixed_count=2, pearl_satellite_count=1,
                    hide_cords=True))
                scene.start_lap()
                visited = set()
                for tick in range(3600):
                    scene.step()
                    visited.add(current_anchor(scene)[0].value)
                    if tick % 10 == 0:
                        self.assertTrue(scene.navigator.region.contains(scene.body.chunks[0].position))
                        self.assertLess(scene.arm.constraint_error, .2)
                        self.assertTrue(all(isfinite(p.position.x) and isfinite(p.position.y)
                                            for p in (*scene.body.chunks, *scene.arm.joints)))
                        self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                                            for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))
                    if scene.arrived:
                        break
                self.assertLess(tick, 3599)
                self.assertEqual(visited, {'top', 'right', 'bottom', 'left'})
                for _ in range(600):
                    scene.step()
                self.assertTrue(scene.appearance.sleeping)

    def test_near_half_band_adjacent_drift_crossings_in_both_directions(self):
        sides = ('top', 'right', 'bottom', 'left')
        for edge, side in enumerate(sides):
            for sign in (-1, 1):
                with self.subTest(side=side, sign=sign):
                    scene = OracleScene(OracleConfig(world_width=640, world_height=385, arm_scale=.75,
                        edge_fraction=.499, base_side=side, hide_cords=True))
                    scene.drift()
                    scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
                    for _ in range(130):
                        scene.step()
                    destination = (edge+sign) % 4
                    self.assertTrue(scene.behavior.start_drift_crossing(scene, destination))
                    for tick in range(3000):
                        scene.step()
                        self.assertTrue(scene.navigator.region.contains(scene.body.chunks[0].position))
                        self.assertLess(scene.arm.constraint_error, .2)
                        if scene.behavior.state != Activity.DRIFT_CROSS_EDGE:
                            break
                    self.assertLess(tick, 2999)
                    # 宽活动带的两边会重叠，底座可继续在原边支撑；行为和身体应进入目标走廊
                    self.assertEqual(scene.behavior.drift_edge, destination)
                    self.assertTrue(scene.navigator.region.edge_boxes[destination].contains(scene.body.chunks[0].position))


if __name__ == '__main__':
    unittest.main()
