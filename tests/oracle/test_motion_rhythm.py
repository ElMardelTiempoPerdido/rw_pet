"""行动速度、连续途经点与有限路径历史；不依赖渲染帧率。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.navigation import normalized
from rw_creature_pet.oracle.scene import OracleScene, dot
from rw_creature_pet.shared.geometry import Vec2


class MotionRhythmTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(OracleConfig(**settings))
        scene.appearance.step = lambda scene: None
        return scene

    def test_drift_speed_config_is_independent_and_validated(self):
        with TemporaryDirectory() as temp:
            path = Path(temp)/'config.toml'
            path.write_text('[oracle]\ndrift_speed = 1.2\n', encoding='utf-8')
            config = AppConfig.load(path).oracle
            self.assertEqual(config.drift_speed, 1.2)
            self.assertEqual(config.float_speed, OracleConfig().float_speed)
        for value in (0., 2., True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                OracleConfig(drift_speed=value)

    def test_weightlessness_does_not_slow_navigation_and_approach_is_faster(self):
        times = []
        for observing in (False, True):
            scene = self.scene(world_width=1600)
            scene.drift()
            scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
            for _ in range(130):
                scene.step()
            start = scene.body.chunks[0].position
            scene.behavior.drift_move_to(scene, start+Vec2(160, 0), observing=observing)
            pace, maximum = scene.travel_speed, 0.
            for tick in range(800):
                scene.step()
                self.assertEqual(scene.travel_speed, pace)
                self.assertEqual(scene.pose.weightlessness, 1.)
                maximum = max(maximum, scene.navigator.speed)
                if scene.arrived:
                    break
            self.assertLess(tick, 799)
            self.assertGreater(maximum, .8)  # 旧版完全失重只到 0.4。
            self.assertAlmostEqual(maximum, pace, places=6)
            times.append(tick)
        self.assertLess(times[1], times[0]*.8)

    def test_long_moves_have_a_stable_faster_pace_than_short_roams(self):
        scene = self.scene()
        short = [scene.behavior.travel_speed(scene, Activity.ROAM, 60) for _ in range(20)]
        long = [scene.behavior.travel_speed(scene, Activity.CROSS_EDGE, 500) for _ in range(20)]
        self.assertGreater(min(long), max(short)*1.25)
        # 速度抽样使用独立随机流，不改变自主活动选择。
        fresh = self.scene()
        self.assertEqual(scene.behavior.random.getstate(), fresh.behavior.random.getstate())

    def test_join_keeps_guide_speed_and_tangent_without_growing_history(self):
        scene = self.scene(world_width=3840)
        nav = scene.navigator
        box = nav.region.boxes[0]
        start = scene.body.chunks[0].position
        scene._move_to(start+Vec2(90, 0))
        joins = crossings = 0
        seam = None
        for _ in range(1500):
            if nav.route.length-nav.distance < 35 and joins < 12:
                before = (nav.guide, nav.velocity, nav.speed)
                previous = nav.route.curves[-1]
                target = previous.d+Vec2(90, 2 if joins % 2 else -2)
                self.assertTrue(nav.extend_to(target, box))
                self.assertEqual(before, (nav.guide, nav.velocity, nav.speed))
                next_curve = nav.route.curves[-1]
                self.assertGreater(dot(normalized(previous.d-previous.c),
                                       normalized(next_curve.b-next_curve.a)), .999999)
                self.assertLessEqual(len(nav.route.curves), 2)
                seam = nav.route.curve_offsets[-1]
                joins += 1
                for curve in nav.route.curves:
                    self.assertTrue(all(box.contains(curve.sample(i/100)) for i in range(101)))
            previous_distance = nav.distance
            nav.step(nav.guide, scene.arm.maximum_reach, speed_limit=1.)
            if seam is not None and previous_distance < seam <= nav.distance:
                self.assertGreater(nav.speed, .8, '途经点不应重新刹停')
                crossings += 1
            if nav.done:
                break
        self.assertEqual(joins, 12)
        self.assertEqual(crossings, 12)
        self.assertTrue(nav.done)

    def test_unsafe_join_keeps_stop_and_free_roam_can_still_be_interrupted(self):
        scene = self.scene(cross_edge_probability=0.)  # 本组隔离同边接续，跨边路线另测。
        start = scene.body.chunks[0].position
        scene._move_to(start+Vec2(90, 0))
        nav, box = scene.navigator, scene.navigator.region.boxes[0]
        route = nav.route
        self.assertFalse(nav.extend_to(start, box))  # 尖锐掉头。
        self.assertFalse(nav.extend_to(Vec2(800, 300), box))  # 中央禁区。
        self.assertIs(nav.route, route)
        scene.drift()
        scene.behavior.drift_next_observation = 100000
        joins = 0
        for _ in range(1600):
            before = scene.navigator.route
            scene.step()
            if scene.navigator.route is not before and len(scene.navigator.route.curves) == 2:
                joins += 1
            self.assertLessEqual(len(scene.navigator.route.curves), 2)
            self.assertLess(scene.arm.constraint_error, .025)
        self.assertGreater(joins, 2)
        scene.stop()
        for _ in range(900):
            scene.step()
        self.assertTrue(scene.arrived and scene.pose.settled)
        self.assertFalse(scene.behavior.active)

    def test_fast_drift_with_short_arm_and_slow_base_keeps_support_on_each_edge(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(world_width=1280, world_height=720, edge_fraction=.35,
                               base_side=side, base_fraction=0., arm_scale=.35,
                               drift_speed=1.8, base_speed=1.5, antigravity_duration_seconds=35.)
            scene.drift()
            scene.behavior.drift_next_observation = 100000
            for tick in range(2600):
                scene.step()
                upper, lower = scene.body.chunks
                self.assertTrue(scene.navigator.region.boxes[scene.behavior.drift_edge].contains(upper.position))
                self.assertLessEqual((upper.position-scene.base).length(), scene.arm.maximum_reach+1e-6)
                self.assertAlmostEqual((upper.position-lower.position).length(), 9., places=6)
                self.assertLess(scene.arm.constraint_error, .025)
                self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                                    for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))
                if not scene.behavior.active:
                    break
            self.assertLess(tick, 2599, side)
            self.assertTrue(scene.arrived and scene.pose.settled)

    def test_long_arm_slides_out_of_near_horizontal_fold_at_left_corner(self):
        scene = self.scene(world_width=640, world_height=480, arm_scale=.75,
                           base_side='left', base_fraction=0., antigravity_duration_seconds=45.)
        scene.drift()
        for _ in range(1900):
            scene.step()
            self.assertLess(scene.arm.constraint_error, .025)
            self.assertLess(max(p.velocity.length() for p in scene.arm.joints), 8.)
            self.assertTrue(all(scene.arm_region.segment_safe(a.position, b.position)
                                for a, b in zip(scene.arm.joints, scene.arm.joints[1:])))


if __name__ == '__main__':
    unittest.main()
