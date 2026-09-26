"""漫游的长短停顿、连续漂浮时长、事件优先级与停稳休眠。"""
import unittest
from unittest.mock import patch

from rw_creature_pet.oracle.behavior import Activity, OracleBehavior
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.timing import FixedStepper


class DriftTimingTests(unittest.TestCase):
    def scene(self, *, real=False, **settings):
        scene = OracleScene(OracleConfig(cross_edge_probability=0., **settings))
        if not real:
            scene.appearance.step = lambda scene: None
        scene.drift()
        scene.behavior.drift_next_move = scene.behavior.drift_next_observation = 100000
        for _ in range(130):
            scene.step()
        return scene

    def until(self, scene, condition, limit=1500):
        for _ in range(limit):
            scene.step()
            if condition():
                return
        self.fail(f'未完成：{scene.behavior.state}, tick={scene.behavior.drift_ticks}')

    def test_pause_distribution_has_distinct_lengths_without_repeated_long_rests(self):
        behavior = OracleBehavior()
        streams = [r.getstate() for r in (behavior.random, behavior.pace_random, behavior.detail_random)]
        values = [behavior.sample_drift_pause() for _ in range(3000)]
        counts = [sum(lo <= value <= hi for value in values) for lo, hi in behavior.DRIFT_PAUSE_BANDS]
        self.assertEqual(sum(counts), len(values))
        self.assertGreater(counts[0]/len(values), .45)
        self.assertGreater(counts[1]/len(values), .25)
        self.assertTrue(.08 < counts[2]/len(values) < .18)
        self.assertLess(min(values), 20)
        self.assertGreater(max(values), 520)
        self.assertGreater(len(set(values)), 350)
        self.assertFalse(any(a >= 280 and b >= 280 for a, b in zip(values, values[1:])))
        self.assertEqual(streams, [r.getstate() for r in (behavior.random, behavior.pace_random, behavior.detail_random)])
        reset = OracleBehavior()
        self.assertEqual(values[:30], [reset.sample_drift_pause() for _ in range(30)])

    def test_long_pause_is_sampled_once_without_replanning_until_deadline(self):
        scene = self.scene()
        behavior = scene.behavior
        behavior.drift_move_to(scene, scene.body.chunks[0].position+Vec2(90, 0))
        behavior.drift_bout_until = behavior.drift_next_move = 0  # 强制本段结束后停顿。
        with patch.object(behavior, 'sample_drift_pause', return_value=560) as sample:
            self.until(scene, lambda: behavior.drift_next_move > behavior.drift_ticks)
            self.assertEqual(sample.call_count, 1)
            deadline, route = behavior.drift_next_move, scene.navigator.route
            streams = [r.getstate() for r in (behavior.random, behavior.timing_random)]
            clock = FixedStepper(40)
            clock.set_paused(True)
            tick = behavior.drift_ticks
            clock.advance(5., scene.step)
            self.assertEqual(behavior.drift_ticks, tick)
            while behavior.drift_ticks < deadline-1:
                scene.step()
                self.assertIs(scene.navigator.route, route)
            self.assertEqual(streams, [r.getstate() for r in (behavior.random, behavior.timing_random)])
            scene.step()
            self.assertIsNot(scene.navigator.route, route)
            self.assertEqual(sample.call_count, 1)

    def test_truly_resting_pause_does_not_wake_soft_parts(self):
        scene = self.scene(real=True)
        behavior = scene.behavior
        # 停顿不强行冻结尚未收敛的身体；这里先等待真实停稳。
        self.until(scene, lambda: scene.appearance.sleeping and scene.arrived and scene.pearl.settled)
        behavior.drift_next_move = behavior.drift_ticks+560
        revisions = (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision)
        stream = behavior.timing_random.getstate()
        for _ in range(559):
            scene.step()
        self.assertEqual(revisions, (scene.appearance.revision, scene.pearl.revision, scene.eyes.revision))
        self.assertEqual(stream, behavior.timing_random.getstate())
        scene.step()
        self.assertFalse(scene.appearance.sleeping)

    def test_bout_keeps_its_deadline_across_safe_joins_and_stops_at_endpoint(self):
        scene = self.scene(world_width=3840)
        behavior = scene.behavior
        behavior.drift_move_to(scene, scene.body.chunks[0].position+Vec2(90, 0))
        behavior.drift_next_move = 0
        behavior.drift_bout_until = until = behavior.drift_ticks+400
        joins = 0
        with patch.object(behavior, 'drift_point', side_effect=lambda scene, start, forward=None: start+Vec2(90, 0)), \
                patch.object(behavior, 'sample_drift_pause', return_value=560):
            for _ in range(900):
                before = scene.navigator.route
                scene.step()
                self.assertEqual(behavior.drift_bout_until, until)
                self.assertLessEqual(len(scene.navigator.route.curves), 2)
                if scene.navigator.route is not before:
                    joins += 1
                if behavior.drift_next_move > behavior.drift_ticks:
                    break
            self.assertGreater(joins, 1)
            self.assertTrue(scene.navigator.done)
            self.assertLess((scene.body.chunks[0].position-scene.target).length(), 2.)
            self.assertLess(behavior.drift_ticks, until+240)

    def test_observation_and_expiry_override_a_long_pause(self):
        for expire in (False, True):
            scene = self.scene()
            behavior = scene.behavior
            behavior.drift_next_move = behavior.drift_ticks+560
            if expire:
                behavior.drift_duration = behavior.drift_ticks+10
            else:
                behavior.drift_next_observation = behavior.drift_ticks+10
            for _ in range(11):
                scene.step()
            if expire:
                self.assertTrue(behavior.drift_recovering)
                self.assertLess(scene.pose.weightlessness, 1.)
            else:
                self.assertEqual(behavior.state, Activity.NOTICE)
                self.assertTrue(behavior.drift_active)

    def test_entry_resume_and_bout_times_vary_and_resize_preserves_timing_stream(self):
        scene = self.scene()
        behavior = scene.behavior
        entries, resumes, bouts = [], [], []
        for _ in range(60):
            behavior.start_drift(scene)
            entries.append(behavior.drift_next_move)
            behavior.drift_pause_ticks = 560  # 观察/冥想接管后不再补上旧停顿。
            behavior.resume_or_idle(scene)
            self.assertEqual(behavior.drift_pause_ticks, 0)
            resumes.append(behavior.drift_next_move-behavior.drift_ticks)
            behavior.drift_move_to(scene, scene.body.chunks[0].position+Vec2(70, 0))
            bouts.append(behavior.drift_bout_until-behavior.drift_ticks)
        self.assertTrue(all(100 <= value <= 200 for value in entries))
        self.assertTrue(all(20 <= value <= 120 for value in resumes))
        self.assertGreater(len(set(entries)), 20)
        self.assertGreater(len(set(resumes)), 20)
        self.assertLess(min(bouts), 240)
        self.assertGreater(max(bouts), 800)
        stream = behavior.timing_random.getstate()
        resized = OracleDesktopMotion(scene.config, OracleDesktopViewport(0, 0, 1280, 680, 1.), scene).scene
        self.assertEqual(resized.behavior.timing_random.getstate(), stream)
        self.assertEqual(resized.behavior.drift_bout_until, 0)

    def test_fixed_base_also_pauses_at_destination(self):
        scene = self.scene(sliding_base=False)
        behavior = scene.behavior
        behavior.drift_next_move = 0
        with patch.object(behavior, 'sample_drift_pause', return_value=400) as sample:
            behavior.drift_move_to(scene, scene.body.chunks[0].position+Vec2(50, 0))
            self.until(scene, lambda: behavior.drift_next_move > behavior.drift_ticks)
            self.assertEqual(sample.call_count, 1)
            self.assertEqual(behavior.drift_next_move-behavior.drift_ticks, 400)


if __name__ == '__main__':
    unittest.main()
