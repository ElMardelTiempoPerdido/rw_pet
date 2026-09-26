"""矩阵抽取、槽位归队及中断：颜色/字形不变，整条路径包含投影余量。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.behavior import Activity
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene


class MatrixObservationTests(unittest.TestCase):
    def scene(self, **settings):
        scene = OracleScene(replace(OracleConfig(pearl_matrix_enabled=True), **settings))
        scene.appearance.step = lambda _: None
        return scene

    def until(self, scene, condition, limit=4000):
        for tick in range(limit):
            scene.step()
            if condition():
                return tick
        self.fail(f'未完成：{scene.behavior.state}, extracted={scene.pearl_matrix.extracted}')

    def assert_safe(self, scene, pearl):
        self.assertTrue(pearl.region.segment_safe(pearl.previous_position, pearl.position))
        self.assertLessEqual((pearl.position-pearl.previous_position).length(), pearl.FOLLOW_SPEED+.001)
        w, hole = scene.world, scene.world.inner
        for alpha in (0., .5, 1.):
            p = pearl.sample(alpha)
            self.assertTrue(pearl.region.contains(p))
            self.assertTrue(0 <= p.x-4 and p.x+15 <= w.width and 0 <= p.y-15 and p.y+4 <= w.height)
            self.assertTrue(p.x+15 <= hole.left or p.x-4 >= hole.right
                            or p.y+4 <= hole.top or p.y-15 >= hole.bottom)

    def test_cycles_at_four_edges_keep_slot_identity_and_singleton(self):
        for size in ((960, 600), (640, 480)):
            for side in ('top', 'right', 'bottom', 'left'):
                with self.subTest(size=size, side=side):
                    scene = self.scene(world_width=size[0], world_height=size[1], base_side=side)
                    matrix = scene.pearl_matrix
                    original = matrix.pearls
                    primary = (scene.pearl.position, scene.pearl.glyph_id, scene.pearl.color_slot)
                    scene.observe_matrix_pearl((2, 0))
                    selected = scene.observed_pearl
                    member = matrix.extracted_member
                    self.assertEqual(selected.position, matrix.anchor.position+member.offset)
                    self.assertEqual((selected.glyph_id, selected.color_slot), (member.glyph_id, member.color_slot))
                    states = []

                    def complete():
                        if not states or states[-1] != scene.behavior.state:
                            states.append(scene.behavior.state)
                        self.assert_safe(scene, selected)
                        self.assertEqual(len(tuple(matrix.samples())), 14)
                        if scene.behavior.looking:
                            self.assertEqual(scene.look_target, selected.position)
                        if scene.behavior.state == Activity.OBSERVE:
                            # 留出槽位空缺，没有把其余 13 颗重新排列或复制被抽取的珠子。
                            self.assertGreater((selected.position-selected.home).length(), 5)
                            for p, sample in zip(matrix.pearls, matrix.samples()):
                                self.assertEqual(sample[0], selected.position if p is member else matrix.anchor.position+p.offset)
                        return scene.behavior.completed_cycles == 1

                    self.until(scene, complete)
                    self.assertEqual(states, [Activity.NOTICE, Activity.RECALL, Activity.OBSERVE, Activity.RETURN, Activity.IDLE])
                    self.assertIsNone(matrix.extracted)
                    self.assertEqual(original, matrix.pearls)
                    self.assertEqual(selected.position, matrix.anchor.position+member.offset)
                    for p, sample in zip(matrix.pearls, matrix.samples()):
                        self.assertEqual(sample, (matrix.anchor.position+p.offset, p.glyph_id, p.color_slot))
                    self.assertEqual(primary, (scene.pearl.position, scene.pearl.glyph_id, scene.pearl.color_slot))
                    self.assertIsNone(scene.behavior.observation_pearl)

    def test_all_slots_begin_at_actual_matrix_position_and_invalid_slot_is_atomic(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(base_side=side, world_width=640, world_height=480)
            for member in scene.pearl_matrix.pearls:
                scene.reset()
                matrix = scene.pearl_matrix
                original = tuple(matrix.samples(.5))
                scene.observe_matrix_pearl(member.slot)
                self.assertEqual(original, tuple(matrix.samples(.5)))
                self.assert_safe(scene, scene.observed_pearl)
                before = (scene.behavior.state, scene.observed_pearl, scene.behavior.enabled)
                with self.assertRaises(ValueError):
                    scene.observe_matrix_pearl((2, 2))
                self.assertEqual(before, (scene.behavior.state, scene.observed_pearl, scene.behavior.enabled))

    def test_cancel_then_cross_corner_returns_to_migrated_slot(self):
        scene = self.scene(float_speed=2.)
        scene.observe_matrix_pearl((1, 3))
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        matrix, selected = scene.pearl_matrix, scene.observed_pearl
        member, old_home = matrix.extracted_member, selected.home
        scene.set_target(Vec2(885, 320))  # 手动接管，珠子归队和整组过角并行。
        self.assertIsNone(scene.behavior.observation_pearl)
        with patch.object(selected.planner, 'plan', wraps=selected.planner.plan) as plan:
            def complete():
                self.assert_safe(scene, selected)
                return scene.arrived and matrix.settled and matrix.extracted is None
            ticks = self.until(scene, complete)
            self.assertLess(plan.call_count, ticks/10+1)
        self.assertGreater((matrix.anchor.position+member.offset-old_home).length(), 150)
        self.assertEqual(selected.position, matrix.anchor.position+member.offset)
        self.assertTrue(all(c.certified_safe(selected.region) for c in selected.route.curves))

    def test_repeated_requests_and_switching_to_singleton_do_not_orphan_pearls(self):
        scene = self.scene()
        scene.observe_matrix_pearl((0, 0))
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        selected = scene.observed_pearl
        scene.observe_matrix_pearl((1, 3))
        self.assertIs(scene.observed_pearl, selected)
        self.assertEqual(scene.pearl_matrix.extracted_member.slot, (0, 0))
        scene.observe_pearl('recall')
        self.assertIs(scene.observed_pearl, scene.pearl)
        self.assertTrue(selected.returning_home)
        self.until(scene, lambda: scene.behavior.completed_cycles == 1 and scene.pearl_matrix.extracted is None)
        self.assertEqual(len(tuple(scene.pearl_matrix.samples())), 14)

    def test_return_tracks_moving_matrix_around_every_corner(self):
        sides = ('top', 'right', 'bottom', 'left')
        for side in range(4):
            for turn in (-1, 1):
                scene = self.scene(base_side=sides[side], world_width=640, world_height=480)
                matrix = scene.pearl_matrix
                destination = scene.body_region.boxes[(side+turn) % 4].clamp(Vec2(320, 240))
                # 先启动整组，覆盖从正在移动的矩阵抽出时的前后帧和速度。
                for _ in range(35):
                    matrix.step(destination)
                original = tuple(matrix.samples(.5))
                selected = matrix.extract((2, 4))
                for before, after in zip(original, matrix.samples(.5)):
                    self.assertLess((before[0]-after[0]).length(), 1e-9)
                    self.assertEqual(before[1:], after[1:])
                self.assertEqual(selected.velocity, matrix.anchor.velocity)
                selected.move_to(selected.region.clamp(selected.position+Vec2(25, 25)))
                for _ in range(40):
                    matrix.step(destination)
                selected.return_home()
                for tick in range(1800):
                    matrix.step(destination)
                    self.assert_safe(scene, selected)
                    if matrix.settled and matrix.extracted is None:
                        break
                self.assertLess(tick, 1799, (side, turn))
                self.assertTrue(all(c.certified_safe(selected.region) for c in selected.route.curves))

    def test_fixed_base_can_recall_and_return_matrix_pearl(self):
        for side in ('top', 'right', 'bottom', 'left'):
            scene = self.scene(base_side=side, sliding_base=False)
            scene.observe_matrix_pearl((0, 2))
            self.until(scene, lambda: scene.behavior.completed_cycles == 1)
            self.assertIsNone(scene.pearl_matrix.extracted)

    def test_disable_and_reset_during_each_phase(self):
        for state in (Activity.NOTICE, Activity.RECALL, Activity.OBSERVE, Activity.RETURN):
            scene = self.scene()
            scene.observe_matrix_pearl()
            self.until(scene, lambda: scene.behavior.state == state)
            scene.set_autonomous(True)
            scene.set_pearl_matrix(False)
            self.assertIsNone(scene.pearl_matrix)
            self.assertTrue(scene.behavior.enabled)
            self.assertEqual(scene.behavior.state, Activity.IDLE)
            self.assertIsNone(scene.look_target)
            self.assertIs(scene.observed_pearl, scene.pearl)
            self.assertFalse(scene.observe_matrix_pearl())
            scene.set_pearl_matrix(True)
            scene.observe_matrix_pearl()
            scene.reset()
            self.assertIsNone(scene.pearl_matrix.extracted)
            self.assertEqual(len(tuple(scene.pearl_matrix.samples())), 14)

    def test_autonomous_selection_both_sources_without_immediate_slot_repeat(self):
        scene = self.scene()
        sources, slots = set(), []
        for _ in range(80):
            scene.behavior.notice(scene)
            sources.add(scene.behavior.matrix_observation)
            if scene.behavior.matrix_observation:
                slots.append(scene.behavior.last_matrix_slot)
            scene.behavior.cancel(scene)
            self.until(scene, lambda: scene.pearl_matrix.extracted is None)
        self.assertEqual(sources, {True, False})
        self.assertTrue(all(a != b for a, b in zip(slots, slots[1:])))
        scene.set_pearl_matrix(False)
        rng = scene.behavior.pearl_random.getstate()
        for _ in range(10):
            scene.behavior.notice(scene)
        self.assertEqual(rng, scene.behavior.pearl_random.getstate())

    def test_drift_observation_returns_then_resumes_and_recovers_after_expiry(self):
        scene = self.scene()
        scene.drift()
        for _ in range(150):
            scene.step()
        scene.observe_matrix_pearl()
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        self.assertTrue(scene.behavior.drift_active)
        scene.behavior.drift_duration = scene.behavior.drift_ticks+1
        self.until(scene, lambda: scene.behavior.completed_cycles == 1)
        self.assertEqual(scene.behavior.state, Activity.DRIFT)
        self.assertIsNone(scene.pearl_matrix.extracted)
        self.until(scene, lambda: not scene.behavior.drift_active)
        self.assertEqual(scene.behavior.state, Activity.IDLE)

    def test_resize_reassembles_same_members_and_preserves_selection_rng(self):
        scene = self.scene()
        scene.observe_matrix_pearl((1, 3))
        scene.set_autonomous(True)
        self.until(scene, lambda: scene.behavior.state == Activity.OBSERVE)
        original = [(p.slot, p.glyph_id, p.color_slot) for p in scene.pearl_matrix.pearls]
        for viewport in (OracleDesktopViewport(0, 0, 640, 480), OracleDesktopViewport(-1080, 0, 1080, 1920)):
            new = OracleDesktopMotion(scene.config, viewport, scene).scene
            self.assertEqual(original, [(p.slot, p.glyph_id, p.color_slot) for p in new.pearl_matrix.pearls])
            self.assertIsNone(new.pearl_matrix.extracted)
            self.assertIsNone(new.behavior.observation_pearl)
            self.assertEqual(new.behavior.state, Activity.IDLE)
            self.assertTrue(new.behavior.enabled)
            self.assertEqual(new.behavior.pearl_random.getstate(), scene.behavior.pearl_random.getstate())
            self.assertEqual(new.behavior.last_matrix_slot, (1, 3))


class MatrixObservationRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_debug_trigger_pause_and_stable_sleep_after_cycle(self):
        window = OracleDebugWindow(AppConfig(), load_atlas=False)
        window.timer.stop()
        try:
            window.set_paused(True)
            self.assertFalse(window.matrix_pearl_button.isEnabled())
            window.matrix_box.setChecked(True)
            window.matrix_pearl_button.click()
            scene = window.scene
            self.assertEqual(scene.behavior.state, Activity.NOTICE)
            before = (scene.ticks, scene.pearl_visual_revision)
            window.on_timer()
            self.assertEqual(before, (scene.ticks, scene.pearl_visual_revision))
            for tick in range(1800):
                scene.step()
                if scene.behavior.completed_cycles and scene.appearance.sleeping and scene.pearls_settled:
                    break
            self.assertLess(tick, 1799)
            revisions = (scene.pearl_visual_revision, scene.appearance.revision, scene.eyes.revision)
            for _ in range(200):
                scene.step()
            self.assertEqual(revisions, (scene.pearl_visual_revision, scene.appearance.revision, scene.eyes.revision))
        finally:
            window.close()

    def test_extracted_pearl_alone_reuses_body_cache(self):
        scene = OracleScene(OracleConfig(pearl_matrix_enabled=True))
        for _ in range(900):
            scene.step()
        renderer = OracleRenderer()
        image = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            renderer.draw(painter, scene)
            frame, revision = renderer._frame, scene.appearance.revision
            pearl = scene.pearl_matrix.extract((0, 0))
            pearl.move_to(pearl.position+Vec2(45, 0))
            for _ in range(80):
                scene.step()
                renderer.draw(painter, scene)
                self.assertIs(renderer._frame, frame)
            self.assertEqual(scene.appearance.revision, revision)
            previous = (scene.pearl_visual_revision, pearl.position)
            for alpha in (0., .5, 1.):
                renderer.draw(painter, scene, alpha)
            self.assertEqual(previous, (scene.pearl_visual_revision, pearl.position))
        finally:
            painter.end()


if __name__ == '__main__':
    unittest.main()
