from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.shared.timing import FixedStepper
from rw_creature_pet.overseer.config import OverseerConfig
from rw_creature_pet.overseer.events import EventPhase, OverseerEvents, SpawnContext
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer


class OverseerEventTests(unittest.TestCase):
    def setUp(self):
        self.model = Overseer(config=OverseerConfig(enabled=True, check_interval=.1,
            appearance_probability=1, duration_min=2, duration_max=2, cooldown_min=.2, cooldown_max=.2,
            relocation_probability=0))
        self.events = OverseerEvents(self.model, seed=246)
        self.context = SpawnContext(self.model.bounds)
        self.factory = Mock(return_value=self.context)

    def step(self, count=1, **kwargs):
        for _ in range(count):
            self.events.step(context_factory=self.factory, **kwargs)

    def test_probability_has_fixed_check_times_and_no_idle_geometry_work(self):
        self.events.configure(replace(self.events.config, appearance_probability=0))
        self.step(3)
        self.assertEqual(self.events.check_count, 0)
        self.step()
        self.assertEqual(self.events.check_count, 1)
        self.step(36)
        self.assertEqual(self.events.check_count, 10)
        self.factory.assert_not_called()
        self.events.configure(replace(self.events.config, appearance_probability=1))
        self.step(4)
        self.assertEqual(self.events.check_count, 11)
        self.assertEqual(self.events.event_count, 1)
        self.assertEqual(self.events.phase, EventPhase.ACTIVE)
        self.factory.assert_called_once()

    def test_full_lifetime_includes_emergence_and_hidden_time(self):
        self.events.start(self.context)
        root = self.model.root
        self.step(50, threat=root)
        self.assertEqual(self.model.extended, 0)
        self.assertAlmostEqual(self.events.remaining, .75)
        self.step(30, threat=root)
        self.assertEqual(self.events.phase, EventPhase.COOLDOWN)
        self.assertFalse(self.model.active)
        self.assertEqual(self.model.root, root)
        self.assertAlmostEqual(self.events.cooldown_remaining, .2)

    def test_expiring_visible_event_finishes_even_if_mouse_leaves(self):
        self.events.start(self.context)
        self.step(70)
        self.assertEqual(self.model.extended, 1)
        self.step(10, threat=self.model.root)
        self.assertEqual(self.events.phase, EventPhase.EXITING)
        for _ in range(40):
            self.events.emerge()
            self.step()
            if self.events.phase == EventPhase.COOLDOWN:
                break
            self.assertFalse(self.model.wants_out)
        self.assertEqual(self.events.phase, EventPhase.COOLDOWN)
        self.assertFalse(self.model.visible)

    def test_cooldown_then_whole_check_interval_without_double_spawn(self):
        self.events.start(self.context)
        self.events.finish()
        self.step()  # 在尚未探出时退场。
        self.assertEqual(self.events.phase, EventPhase.COOLDOWN)
        self.step(8)
        self.assertEqual(self.events.phase, EventPhase.WAITING)
        self.assertEqual(self.events.check_count, 0)
        self.step(3)
        self.assertEqual(self.events.phase, EventPhase.WAITING)
        self.step()
        self.assertEqual(self.events.phase, EventPhase.ACTIVE)
        self.assertEqual(self.events.event_count, 2)

    def test_disable_finishes_current_event_and_no_new_events(self):
        self.events.start(self.context)
        self.step(60)
        self.events.configure(replace(self.events.config, enabled=False))
        self.assertEqual(self.events.phase, EventPhase.EXITING)
        self.step(100)
        self.assertEqual(self.events.phase, EventPhase.DISABLED)
        self.assertFalse(self.model.active)
        count = self.events.event_count
        state = self.events.random.getstate()
        self.step(300)
        self.assertEqual(self.events.event_count, count)
        self.assertEqual(self.events.random.getstate(), state)
        self.assertFalse(self.events.check(self.factory))
        self.events.configure(replace(self.events.config, enabled=True))
        self.step(3)
        self.assertEqual(self.events.phase, EventPhase.WAITING)
        self.step()
        self.assertEqual(self.events.phase, EventPhase.ACTIVE)

    def test_pause_freezes_wait_lifetime_exit_and_cooldown(self):
        clock = FixedStepper(40)
        clock.set_paused(True)
        for phase in (EventPhase.WAITING, EventPhase.ACTIVE, EventPhase.EXITING, EventPhase.COOLDOWN):
            if phase == EventPhase.ACTIVE:
                self.events.start(self.context)
                self.step(30)
            elif phase == EventPhase.EXITING:
                self.events.finish()
            elif phase == EventPhase.COOLDOWN:
                for _ in range(80):
                    self.step()
                    if self.events.phase == EventPhase.COOLDOWN:
                        break
            self.assertEqual(self.events.phase, phase)
            snapshot = (self.events.check_remaining, self.events.remaining, self.events.cooldown_remaining,
                        self.model.extended, self.events.random.getstate())
            clock.advance(300., self.step)
            self.assertEqual(snapshot, (self.events.check_remaining, self.events.remaining,
                self.events.cooldown_remaining, self.model.extended, self.events.random.getstate()))
        clock.single_step(self.step)
        self.assertAlmostEqual(self.events.cooldown_remaining, .175)

    def test_manual_preview_and_debug_operations_are_explicit(self):
        self.events.preview(self.context.bounds, Anchor(Edge.LEFT, .5))
        self.model.request_withdraw()
        self.step(100)
        self.assertEqual(self.events.phase, EventPhase.PREVIEW)
        self.assertEqual(self.events.check_count, 0)
        self.events.finish()
        self.step()
        self.events.skip_cooldown()
        self.assertEqual(self.events.phase, EventPhase.WAITING)
        self.assertTrue(self.events.check(self.factory))
        self.assertFalse(self.events.start(self.context))
        self.events.clear()
        self.assertFalse(self.model.active)
        self.assertEqual(self.events.phase, EventPhase.WAITING)
        self.assertEqual(self.events.check_remaining, self.events.config.check_interval)

    def test_spawns_respect_allowed_edges_corner_mouse_and_body_clearance(self):
        box = Bounds(400, 60, 540, 220)
        mouse = Vec2(150, 0)
        context = SpawnContext(Bounds(0, 0, 960, 600), ('top', 'right'), mouse, (box,))
        sides = set()
        for _ in range(100):
            anchor = self.events.choose_anchor(context)
            self.assertIsNotNone(anchor)
            self.model.place(context.bounds, anchor)
            root = self.model.root
            extent = self.model.reach+self.model.filament_length+12
            self.assertIn(anchor.edge, (Edge.TOP, Edge.RIGHT))
            sides.add(anchor.edge)
            along = root.x if anchor.edge == Edge.TOP else root.y
            length = 960 if anchor.edge == Edge.TOP else 600
            self.assertGreaterEqual(along, extent)
            self.assertLessEqual(along, length-extent)
            self.assertGreaterEqual((mouse-root).length(), self.events.config.reemerge_distance)
            self.assertGreaterEqual((root-box.clamp(root)).length()+1e-6, extent)
        self.assertEqual(sides, {Edge.TOP, Edge.RIGHT})

    def test_fully_blocked_check_skips_without_lifetime_or_cooldown(self):
        self.factory.return_value = replace(self.context, obstacles=(self.context.bounds,))
        self.step(4)
        self.assertEqual(self.events.phase, EventPhase.WAITING)
        self.assertEqual(self.events.event_count, 0)
        self.assertFalse(self.model.active)
        self.assertIn('没有安全', self.events.last_result)
        self.factory.return_value = self.context
        self.step(4)
        self.assertEqual(self.events.event_count, 1)

    def test_new_ranges_do_not_retime_current_event_or_cooldown(self):
        self.events.start(self.context)
        self.step(10)
        remaining = self.events.remaining
        self.events.configure(replace(self.events.config, duration_min=.5, duration_max=.5))
        self.assertEqual(self.events.remaining, remaining)
        self.events.finish()
        for _ in range(80):
            self.step()
            if self.events.phase == EventPhase.COOLDOWN:
                break
        remaining = self.events.cooldown_remaining
        self.events.configure(replace(self.events.config, cooldown_min=2, cooldown_max=3))
        self.assertEqual(self.events.cooldown_remaining, remaining)

    def test_automatic_cycles_reach_all_motion_and_event_states(self):
        self.events.configure(replace(self.events.config, duration_min=1.5, duration_max=1.5))
        phases, motions = set(), set()
        for _ in range(400):
            self.step()
            phases.add(self.events.phase)
            motions.add(self.model.state.value)
        self.assertEqual(phases, {EventPhase.WAITING, EventPhase.ACTIVE, EventPhase.EXITING, EventPhase.COOLDOWN})
        self.assertEqual(motions, {'hidden', 'emerging', 'watching', 'withdrawing'})
        self.assertGreaterEqual(self.events.event_count, 3)
        self.assertEqual(self.events.check_count, self.events.event_count)

    def test_manual_timed_event_can_be_tuned_while_auto_remains_disabled(self):
        self.events.configure(replace(self.events.config, enabled=False))
        self.assertTrue(self.events.start(self.context))
        self.step(10)
        remaining = self.events.remaining
        self.events.configure(replace(self.events.config, reemerge_distance=150))
        self.assertEqual(self.events.phase, EventPhase.ACTIVE)
        self.assertEqual(self.events.remaining, remaining)

    def moving_event(self, **config):
        self.events.configure(replace(self.events.config, duration_min=30, duration_max=30,
                                      relocation_probability=1, **config))
        self.events.start(self.context)
        self.step(64)
        self.assertEqual(self.model.extended, 1)
        return self.model.root

    def test_relocation_waits_for_invisible_frame_and_preserves_event(self):
        for edge in Edge:
            with self.subTest(edge=edge):
                self.events.clear()
                self.context = SpawnContext(self.model.bounds, (edge.value,))
                self.factory.return_value = self.context
                root = self.moving_event()
                self.factory.reset_mock()
                count, remaining = self.events.event_count, self.events.remaining
                relocated = self.events.relocation_count
                for tick in range(60):
                    self.step(threat=root, puppet=root+self.model.normal*50)
                    if self.model.root != root:
                        break
                else:
                    self.fail('完整缩回后没有换位')
                self.assertFalse(self.model.visible)
                self.assertEqual((self.model.extended, self.model.last_extended), (0, 0))
                self.assertEqual(self.model.anchor.edge, edge)
                self.assertGreaterEqual((self.model.root-root).length(), self.events.config.puppet_reemerge_distance)
                self.assertEqual(self.events.event_count, count)
                self.assertEqual(self.events.relocation_count, relocated+1)
                self.assertAlmostEqual(self.events.remaining, remaining-(tick+1)/40)
                self.factory.assert_called_once()
                new_root = self.model.root
                # 原位置仍有威胁，新的安全位置仍可重新探出；一次事件不会延长。
                self.step(100, threat=root, puppet=root)
                self.assertEqual(self.model.root, new_root)
                self.assertEqual(self.model.extended, 1)
                self.assertEqual(self.events.relocation_count, relocated+1)

    def test_original_position_is_kept_without_rerolling_while_hidden(self):
        root = self.moving_event()
        self.events.configure(replace(self.events.config, relocation_probability=0))
        self.factory.reset_mock()
        with patch.object(self.events.random, 'random', wraps=self.events.random.random) as draw:
            self.step(100, puppet=root)
            self.assertEqual(self.model.root, root)
            self.assertFalse(self.model.visible)
            draw.assert_called_once()
            self.factory.assert_not_called()
            self.step(90)
            self.assertEqual(self.model.extended, 1)
            self.step(100, puppet=root)
            self.assertEqual(draw.call_count, 2)  # 第二次遇险才重新选择。

    def test_no_other_safe_location_falls_back_without_repeated_geometry_work(self):
        root = self.moving_event()
        self.factory.return_value = replace(self.context, obstacles=(self.model.bounds,))
        self.factory.reset_mock()
        self.step(100, threat=root)
        self.factory.assert_called_once()
        self.assertEqual(self.model.root, root)
        self.assertFalse(self.model.visible)
        self.assertIn('没有其他安全', self.events.last_result)
        self.step(90)
        self.assertEqual(self.model.extended, 1)

    def test_fast_reversal_expiry_and_manual_preview_do_not_relocate(self):
        root = self.moving_event(safe_delay=0)
        self.factory.reset_mock()
        self.step(2, threat=root)
        self.step(70)
        self.assertEqual(self.model.root, root)
        self.assertEqual(self.model.extended, 1)
        self.factory.assert_not_called()
        self.events.remaining = .025
        for _ in range(60):
            self.step(puppet=root)
            if not self.model.active:
                break
        self.assertFalse(self.model.active)
        self.assertEqual(self.events.relocation_count, 0)
        # 到期退场不会为逃跑抽签、选点；手动预览保持指定位置。
        self.events.preview(self.model.bounds, Anchor(Edge.TOP, .5))
        root = self.model.root
        self.step(100, puppet=root)
        self.assertEqual(self.model.root, root)
        self.assertEqual(self.events.relocation_count, 0)
        self.factory.assert_not_called()

    def test_new_position_waits_for_both_threats_and_expiry_can_interrupt(self):
        root = self.moving_event()
        for _ in range(80):
            self.step(threat=root)
            if self.model.root != root:
                break
        self.assertNotEqual(self.model.root, root)
        self.assertFalse(self.model.visible)
        moves = self.events.relocation_count
        # 在新位置尚未探出时被追上，不连续乱跳，也不强行探出。
        self.step(80, puppet=self.model.root)
        self.assertFalse(self.model.visible)
        self.assertEqual(self.events.relocation_count, moves)
        self.events.remaining = .025
        self.step(puppet=self.model.root)
        self.assertFalse(self.model.active)
        self.assertEqual(self.events.phase, EventPhase.COOLDOWN)

    def test_spawn_excludes_puppet_safety_circle(self):
        puppet = Vec2(480, 40)
        context = SpawnContext(self.model.bounds, ('top',), puppet=puppet)
        for _ in range(50):
            anchor = self.events.choose_anchor(context)
            self.model.place(context.bounds, anchor)
            self.assertGreaterEqual((self.model.root-puppet).length(), self.events.config.puppet_reemerge_distance)


if __name__ == '__main__':
    unittest.main()
