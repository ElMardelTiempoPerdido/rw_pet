"""珍珠行为闭环、路径与手动接管；核心检查不用 Qt 或次级外观积分。"""
from dataclasses import replace
import unittest

from rw_creature_pet.geometry import Vec2
from rw_creature_pet.oracle import OracleScene
from rw_creature_pet.oracle_behavior import Activity
from rw_creature_pet.oracle_config import OracleConfig


class OraclePearlTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(replace(OracleConfig(), **settings))
        scene.appearance.step = lambda scene: None  # 本组仅验证导航/行为，外观另有集成回放。
        return scene

    def step_until(self, scene, condition, limit=12000):
        for tick in range(limit):
            scene.step()
            p = scene.pearl
            self.assertTrue(p.region.segment_safe(p.previous_position, p.position))
            self.assertLessEqual((p.position-p.previous_position).length(), p.FOLLOW_SPEED+.02)
            for alpha in (0., .5, 1.):
                q = p.sample(alpha)
                self.assertTrue(p.region.contains(q))
                # 36px 的共用路径预留覆盖 15×15 标签与 6×6 珠体。
                for corner in (q+Vec2(-3, -15), q+Vec2(15, -15), q+Vec2(15, 3), q+Vec2(-3, 3)):
                    w = scene.world
                    self.assertTrue(0 <= corner.x <= w.width and 0 <= corner.y <= w.height)
                    inner = w.inner
                    self.assertFalse(inner.left < corner.x < inner.right and inner.top < corner.y < inner.bottom)
            if condition():
                return tick
        self.fail(f'行为未收敛：{scene.behavior.state}, pearl={scene.pearl.position}')

    def test_both_observation_cycles_at_all_edges_and_fixed_base(self):
        for side in ('top', 'right', 'bottom', 'left'):
            for sliding in (True, False):
                for mode, expected in (('approach', Activity.APPROACH), ('recall', Activity.RECALL)):
                    with self.subTest(side=side, sliding=sliding, mode=mode):
                        scene = self.scene(base_side=side, sliding_base=sliding)
                        home, glyph = scene.pearl.home, scene.pearl.glyph_id
                        start = scene.body.chunks[0].position
                        scene.observe_pearl(mode)
                        visited = []
                        def complete():
                            if not visited or visited[-1] != scene.behavior.state:
                                visited.append(scene.behavior.state)
                            if scene.behavior.looking:
                                self.assertEqual(scene.look_target, scene.pearl.position)
                            return scene.behavior.completed_cycles == 1
                        self.step_until(scene, complete)
                        self.assertEqual(visited, [Activity.NOTICE, expected, Activity.OBSERVE,
                                                   Activity.RETURN, Activity.IDLE])
                        self.assertEqual(scene.pearl.position, home)
                        self.assertEqual(scene.pearl.glyph_id, glyph)
                        self.assertIsNone(scene.look_target)
                        self.assertFalse(scene.behavior.active)
                        displacement = (scene.body.chunks[0].position-start).length()
                        self.assertGreater(displacement, 10) if mode == 'approach' else self.assertLess(displacement, .01)

    def test_far_manual_home_is_kept_near_puppet_then_recall_returns_there(self):
        scene = self.scene()
        scene.set_pearl_home(Vec2(480, 535))
        self.step_until(scene, lambda: scene.pearl.settled)
        home = scene.pearl.home
        self.assertTrue(scene.pearl.follow_bounds.contains(home))
        self.assertNotEqual(home, Vec2(480, 535))
        scene.observe_pearl('recall')
        self.step_until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        self.assertLess((scene.pearl.position-scene.body.chunks[0].position).length(), 40)
        self.assertLess(scene.pearl.route.length, 250)
        self.assertTrue(all(c.certified_safe(scene.pearl.region) for c in scene.pearl.route.curves))
        self.step_until(scene, lambda: scene.behavior.completed_cycles == 1)
        self.assertEqual(scene.pearl.position, home)

    def test_repeat_loop_includes_roaming_and_both_modes(self):
        scene = self.scene()
        scene.set_autonomous(True)
        states = set()
        def done():
            states.add(scene.behavior.state)
            return scene.behavior.completed_cycles >= 8
        # 珍珠观察现在只是独立可选活动；包含长停留和跨边，八轮不再保证几分钟内完成。
        self.step_until(scene, done, limit=50000)
        self.assertEqual(states, set(Activity))
        self.assertTrue(scene.behavior.enabled)

    def test_manual_takeover_during_recall_returns_without_teleport(self):
        scene = self.scene()
        scene.set_autonomous(True)
        scene.observe_pearl('recall')
        self.step_until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        before = scene.pearl.position
        scene.set_look_target(Vec2(400, 300))
        self.assertFalse(scene.behavior.active)
        self.assertEqual(scene.pearl.position, before)
        target = scene.look_target
        scene.set_target(Vec2(720, 60))
        self.step_until(scene, lambda: scene.pearl.settled and scene.arrived)
        self.assertEqual(scene.pearl.position, scene.pearl.home)
        self.assertEqual(scene.look_target, target)
        self.assertEqual(scene.behavior.completed_cycles, 0)

    def test_small_world_low_speed_and_corner_targets(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(world_width=640, world_height=480, arm_scale=.35,
                               float_speed=.3, base_side=side, base_fraction=0.)
            scene.observe_pearl('approach')
            self.step_until(scene, lambda: scene.behavior.completed_cycles == 1)
            self.assertTrue(scene.arrived)

    def test_reset_reproduces_behavior_without_advancing_visual_randomness(self):
        scene = self.scene()
        def run():
            scene.set_autonomous(True)
            result = []
            for tick in range(850):
                scene.step()
                if tick % 10 == 0:
                    result.append((scene.behavior.state, scene.body.chunks[0].position,
                                   scene.pearl.position, scene.pearl.glyph_id))
            return result
        before = run()
        scene.reset()
        scene.appearance.step = lambda scene: None
        self.assertFalse(scene.behavior.enabled)
        self.assertEqual(before, run())
