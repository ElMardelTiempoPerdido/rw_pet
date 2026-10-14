"""多槽位独立事件、常驻生命周期与配置迁移"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from rw_creature_pet.config import AppConfig
from rw_creature_pet.overseer.config import OverseerConfig, OverseerSlot
from rw_creature_pet.overseer.events import EventPhase, SpawnContext
from rw_creature_pet.overseer.group import OverseerGroup
from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.settings_store import SettingsStore


class OverseerGroupTests(unittest.TestCase):
    def setUp(self):
        self.bounds = Bounds(0, 0, 1920, 1080)
        self.context = SpawnContext(self.bounds, mouse=Vec2(960, 540))
        self.config = OverseerConfig(enabled=True, appearance_mode='resident',
            appearance_probability=0, duration_min=.1, duration_max=.1,
            slots=tuple(OverseerSlot(i, color) for i, color in enumerate(
                ('#ff557f', '#ffffff', '#f3cf74', '#b897ef'), 1)))
        self.group = OverseerGroup(self.config, self.bounds, seed=548)

    def step(self, count=1, **kwargs):
        for _ in range(count):
            self.group.step(Vec2(960, 540), context_factory=lambda: self.context, **kwargs)

    def test_individual_shapes_apply_without_restarting_neighbors_or_events(self):
        self.step(100)
        neighbor = self.group.entries[2]
        unchanged = (neighbor.model.head.position, neighbor.model.time,
                     neighbor.events.event_count, neighbor.model.random.getstate())
        entry = self.group.entries[1]
        event_count = entry.events.event_count
        original_head = entry.model.head.position
        slots = (replace(self.config.slots[0], filament_count=5), *self.config.slots[1:])
        self.group.configure(replace(self.config, slots=slots))
        self.assertIs(entry, self.group.entries[1])
        self.assertEqual(len(entry.model.filaments), 5)
        self.assertEqual(entry.model.head.position, original_head)
        slots = (replace(slots[0], size=1.), *slots[1:])
        self.group.configure(replace(self.config, slots=slots))
        self.assertTrue(entry.model.active)
        self.assertEqual(entry.events.phase, EventPhase.RESIDENT)
        self.assertEqual(entry.events.event_count, event_count)
        self.assertEqual(entry.model.reach, 50.)
        self.assertAlmostEqual((entry.model.hover-entry.model.root).length(), 30.)
        self.assertEqual(unchanged, (neighbor.model.head.position, neighbor.model.time,
                                     neighbor.events.event_count, neighbor.model.random.getstate()))
        self.step(100)
        self.assertTrue(entry.model.visible)
        slots = (replace(slots[0], appearance='friend', filament_count=3), *slots[1:])
        self.group.configure(replace(self.config, slots=slots))
        self.assertEqual(len(entry.model.filaments), 2)
        slots = (replace(slots[0], appearance='standard'), *slots[1:])
        self.group.configure(replace(self.config, slots=slots))
        self.assertEqual(len(entry.model.filaments), 3)
        self.step(10)


    def test_resident_starts_all_without_probability_and_does_not_expire(self):
        self.step(120)
        roots = []
        for slot, entry in zip(self.config.slots, self.group.entries.values()):
            self.assertEqual(entry.model.config.color, slot.color)
            self.assertEqual(entry.events.phase, EventPhase.RESIDENT)
            self.assertEqual(entry.events.event_count, 1)
            self.assertTrue(entry.model.visible)
            radius = entry.model.reach+entry.model.filament_length+12
            for root in roots:
                self.assertGreaterEqual((entry.model.root-root).length(), 2*radius)
            roots.append(entry.model.root)
        self.assertFalse(self.group.available)
        self.assertFalse(self.group.start(self.context))

    def test_random_checks_independent_and_lifetimes_differ(self):
        self.group.configure(replace(self.config, appearance_mode='random', check_interval=.1,
                                     appearance_probability=.5, duration_min=2, duration_max=4))
        self.group.clear()
        rolls = (0., .9, .2, .8)
        for entry, roll in zip(self.group.entries.values(), rolls):
            entry.events.random.random = lambda roll=roll: roll
        self.step(4)
        self.assertEqual([e.model.active for e in self.group.entries.values()], [True, False, True, False])
        self.assertEqual([e.events.check_count for e in self.group.entries.values()], [1]*4)
        self.assertNotEqual(self.group.entries[1].events.remaining, self.group.entries[3].events.remaining)

    def test_mode_changes_preserve_pose_then_random_event_expires(self):
        self.step(70)
        roots = [e.model.root for e in self.group.entries.values()]
        self.group.configure(replace(self.config, appearance_mode='random'))
        self.assertTrue(all(e.events.phase == EventPhase.ACTIVE for e in self.group.entries.values()))
        self.assertEqual(roots, [e.model.root for e in self.group.entries.values()])
        self.step(80)
        self.assertTrue(all(e.events.phase == EventPhase.COOLDOWN for e in self.group.entries.values()))
        self.group.configure(self.config)
        self.step()
        self.assertTrue(all(e.events.phase == EventPhase.RESIDENT for e in self.group.entries.values()))
        self.group.configure(replace(self.config, enabled=False))
        self.step(100)
        self.assertFalse(self.group.active)
        self.assertTrue(all(e.events.phase == EventPhase.DISABLED for e in self.group.entries.values()))

    def test_hidden_resident_avoids_and_relocates_without_restarting_other_slots(self):
        self.group.configure(replace(self.config, relocation_probability=1))
        self.step(65)
        entry = self.group.entries[1]
        old = entry.model.root
        others = [e.model.root for k, e in self.group.entries.items() if k != 1]
        self.step(100, threat=old)
        self.assertNotEqual(entry.model.root, old)
        self.assertEqual(entry.events.event_count, 1)
        self.assertEqual(entry.events.relocation_count, 1)
        self.assertEqual(others, [e.model.root for k, e in self.group.entries.items() if k != 1])
        self.assertEqual(entry.events.phase, EventPhase.RESIDENT)

    def test_no_space_retries_at_bounded_rate_and_recovers_on_resize(self):
        blocked = replace(self.context, obstacles=(self.bounds,))
        factory = Mock(return_value=blocked)
        for _ in range(81):
            self.group.step(context_factory=factory)
        self.assertEqual(factory.call_count, 3)  # 四槽共用本帧外形，最多每秒一次
        self.assertFalse(self.group.active)
        self.step(40)
        self.assertTrue(self.group.active)
        self.bounds = Bounds(0, 0, 900, 700)
        self.context = SpawnContext(self.bounds, edges=('right', 'bottom'))
        self.group.bind(self.bounds, self.context.edges)
        self.assertFalse(self.group.active)
        self.step()
        for e in self.group.entries.values():
            self.assertTrue(self.bounds.contains(e.model.root))
            self.assertIn(e.model.anchor.edge.value, self.context.edges)

    def test_add_remove_recolor_preserves_other_identity_and_zero_slots(self):
        self.step(50)
        original = dict(self.group.entries)
        slot = replace(self.config.slots[2], color='#abcdef')
        reduced = replace(self.config, slots=(self.config.slots[0], slot))
        self.group.configure(reduced)
        self.assertEqual(set(self.group.entries), {1, 3})
        self.assertIs(self.group.entries[3], original[3])
        self.assertEqual(self.group.entries[3].model.config.color, '#abcdef')
        self.assertFalse(original[2].model.active)
        self.assertEqual(self.group.entries[1].events.event_count, 1)
        self.group.configure(self.config)
        self.step()
        self.assertIsNot(self.group.entries[2], original[2])
        self.assertIs(self.group.entries[1], original[1])
        self.group.configure(replace(self.config, slots=()))
        factory = Mock()
        self.group.step(context_factory=factory)
        factory.assert_not_called()
        self.assertFalse(self.group.start(self.context))
        self.assertFalse(self.group.available)

    def test_slot_validation(self):
        for slots in ([{'id': True}], [{'id': 0}], [{'id': 5}], [1], 'invalid',
                      [{'id': 1}, {'id': 1}], [{'id': 1, 'appearance': 'unknown'}],
                      [{'id': 1, 'color': 'red'}], [OverseerSlot()]*5):
            with self.subTest(slots=slots), self.assertRaises((ValueError, TypeError)):
                replace(self.config, slots=slots)
        with self.assertRaises(ValueError):
            replace(self.config, appearance_mode='unknown')

    def test_friend_defaults_roundtrip_and_switch_preserves_live_event(self):
        self.assertEqual(OverseerSlot().color, '#ffffff')
        self.assertEqual(OverseerSlot(appearance='friend').color, '#000000')
        self.assertEqual(OverseerSlot(color='#123456', appearance='friend').color, '#123456')
        self.step(120)
        entry = self.group.entries[1]
        before = (entry.model.root, entry.model.head.position, entry.model.extended,
                  entry.events.phase, entry.events.event_count, entry.events.remaining,
                  entry.model.random.getstate())
        changed = replace(self.config, slots=(OverseerSlot(1, appearance='friend'), *self.config.slots[1:]))
        self.group.configure(changed)
        self.assertIs(self.group.entries[1], entry)
        self.assertEqual(entry.model.appearance, 'friend')
        self.assertEqual(entry.model.config.color, '#000000')
        self.assertEqual(before, (entry.model.root, entry.model.head.position, entry.model.extended,
                                entry.events.phase, entry.events.event_count, entry.events.remaining,
                                entry.model.random.getstate()))
        self.assertTrue(all(e.model.appearance == 'standard' for key, e in self.group.entries.items() if key != 1))
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            store.save(AppConfig(overseer=changed))
            restored = store.load().overseer
            self.assertEqual(restored, changed)
            self.assertEqual(OverseerGroup(restored).entries[1].model.appearance, 'friend')
        self.group.configure(self.config)
        self.assertEqual(entry.model.appearance, 'standard')

    def test_switch_waiting_resident_to_random_restarts_full_check_interval(self):
        self.context = replace(self.context, obstacles=(self.bounds,))
        self.step()
        self.group.configure(replace(self.config, appearance_mode='random', check_interval=30))
        self.assertTrue(all(e.events.check_remaining == 30 for e in self.group.entries.values()))

    def test_old_profile_migrates_color_before_filling_defaults_and_empty_stays_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            for overseer, expected in (({'color': '#123456'}, (OverseerSlot(color='#123456'),)),
                                       ({'color': '#123456', 'slots': []}, ())):
                store.path.write_text(json.dumps({'version': 1, 'config': {'overseer': overseer}}), encoding='utf-8')
                with patch('rw_creature_pet.settings_store.load_defaults', return_value=AppConfig(overseer=self.config)):
                    config, first, _ = store.startup()
                    self.assertFalse(first)
                    self.assertEqual(config.overseer.slots, expected)
                    store.save(config)
                    self.assertEqual(store.load().overseer, config.overseer)


if __name__ == '__main__':
    unittest.main()
