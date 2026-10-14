"""预设字段归属必须完整且互斥，新增隐藏参数也必须显式选择归属"""
from dataclasses import dataclass, field, make_dataclass
from pathlib import Path
import subprocess
import sys
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.face_config import FaceDecal
from rw_creature_pet.presets import FIELD_SCOPES, FieldScope, paths_for, scope_for
from rw_creature_pet.presets.registry import build_registry, schema_paths, validate_registry


@dataclass(frozen=True, slots=True)
class ExtraDecal(FaceDecal):
    opacity: float = .5


@dataclass(frozen=True, slots=True)
class OptionalDecals:
    decals: tuple[ExtraDecal, ...] | None = None

    def __post_init__(self):
        raise AssertionError('归属检查不应创建配置实例')


class PresetFieldTests(unittest.TestCase):
    def test_current_schema_is_complete_and_scopes_are_disjoint(self):
        validate_registry(FIELD_SCOPES, AppConfig)
        buckets = [set(paths_for(scope)) for scope in FieldScope]
        self.assertEqual(set.union(*buckets), schema_paths(AppConfig))
        for index, bucket in enumerate(buckets):
            for other in buckets[index+1:]:
                self.assertFalse(bucket & other)

    def test_hidden_behavior_and_user_preferences_have_different_scopes(self):
        for path in (
            'oracle.base_speed', 'oracle.pearl_follow_width', 'oracle.pearl_follow_height',
            'oracle.drag_reactions.enabled', 'oracle.drag_reactions.gesture_probability',
            'oracle.drag_reactions.flutter_probability',
            'oracle.drag_reactions.alternating_probability',
            'oracle.drag_reactions.eye_open_probability', 'oracle.drag_reactions.voice_probability',
            'interaction.hover_radius', 'interaction.hover_dwell_seconds',
            'interaction.hover_probability', 'interaction.hover_open_probability',
            'interaction.hover_avoidance_enabled',
        ):
            with self.subTest(path=path):
                self.assertIs(scope_for(path), FieldScope.PROFILE)
        for path in (
            'desktop.autonomous', 'interaction.drag_enabled', 'audio.enabled', 'audio.volume',
            'oracle.glow_enabled', 'oracle.glow_color', 'oracle.glow_radius', 'oracle.glow_opacity',
            'oracle.arm_scale', 'oracle.sliding_base', 'oracle.physics_backend', 'oracle.voice_directory',
        ):
            with self.subTest(path=path):
                self.assertIs(scope_for(path), FieldScope.LOCAL)

    def test_projection_and_pearl_exceptions_are_explicit(self):
        for path in (
            'oracle.pearl_bubble_color', 'oracle.colors.pearl_glyph',
            'oracle.custom_colors.pearl_glyph', 'oracle.outfit', 'oracle.body_appearance',
        ):
            self.assertIs(scope_for(path), FieldScope.APPEARANCE)
        for path in (
            'oracle.pearl_matrix_enabled', 'oracle.pearl_orbits_enabled',
            'oracle.pearl_playback_probability', 'oracle.pearl_bubble_max_size',
            'oracle.projection_opacity', 'oracle.halo_scale', 'oracle.halo_arc_max_count',
            'oracle.drag_projection_probability', 'oracle.drag_projection_cooldown_seconds',
        ):
            self.assertIs(scope_for(path), FieldScope.PROFILE)
        for path in ('oracle.halo_enabled', 'oracle.halo_arcs_enabled'):
            self.assertIs(scope_for(path), FieldScope.LOCAL)

    def test_all_overseer_and_screen_fields_stay_local(self):
        overseer_paths = [path for path in schema_paths(AppConfig) if path.startswith('overseer.')]
        self.assertIn('overseer.slots[].id', overseer_paths)
        self.assertIn('overseer.slots[].appearance', overseer_paths)
        for path in overseer_paths + [
            'game_dir', 'desktop.screen', 'desktop.scale', 'ui.language',
            'oracle.world_width', 'oracle.world_height', 'oracle.edge_fraction',
            'oracle.base_side', 'oracle.allowed_edges', 'oracle.base_fraction',
            'oracle.pixel_mode', 'oracle.coarse_pixels_4x', 'oracle.hide_cords',
        ]:
            with self.subTest(path=path):
                self.assertIs(scope_for(path), FieldScope.LOCAL)

    def test_unknown_fields_do_not_inherit_scope_from_parent_or_siblings(self):
        for path in ('oracle.colors.new_color', 'oracle.custom_appearance.new_parameter',
                     'overseer.slots[].new_parameter', 'oracle', 'unknown'):
            with self.subTest(path=path), self.assertRaises(KeyError):
                scope_for(path)

    def test_new_config_field_requires_registration(self):
        future = make_dataclass('FutureConfig', [
            ('hidden_behavior', float, field(default=.5)),
        ], bases=(AppConfig,), frozen=True, slots=True)
        with self.assertRaisesRegex(ValueError, '未登记字段：hidden_behavior'):
            validate_registry(FIELD_SCOPES, future)

    def test_renamed_or_deleted_field_reports_missing_and_stale_paths(self):
        entries = dict(FIELD_SCOPES)
        entries['oracle.old_float_speed'] = entries.pop('oracle.float_speed')
        with self.assertRaises(ValueError) as raised:
            validate_registry(entries, AppConfig)
        self.assertIn('未登记字段：oracle.float_speed', str(raised.exception))
        self.assertIn('配置中不存在的登记：oracle.old_float_speed', str(raised.exception))

    def test_optional_empty_collection_and_inherited_fields_are_checked_by_type(self):
        expected = {f'decals[].{name}' for name in (
            'enabled', 'image_path', 'image_name', 'offset_x', 'offset_y', 'opacity',
        )}
        self.assertEqual(schema_paths(OptionalDecals), expected)
        empty_default = make_dataclass('EmptyDecals', [
            ('decals', tuple[ExtraDecal, ...], field(default=())),
        ], frozen=True, slots=True)
        self.assertEqual(schema_paths(empty_default), expected)
        entries = {path: FieldScope.APPEARANCE for path in expected}
        validate_registry(entries, OptionalDecals)
        entries.pop('decals[].opacity')
        with self.assertRaisesRegex(ValueError, r'未登记字段：decals\[\]\.opacity'):
            validate_registry(entries, OptionalDecals)

    def test_scalar_lists_are_single_fields_but_object_lists_are_not(self):
        paths = schema_paths(AppConfig)
        self.assertIn('oracle.allowed_edges', paths)
        self.assertNotIn('oracle.allowed_edges[]', paths)
        self.assertIn('overseer.slots[].color', paths)
        self.assertNotIn('overseer.slots', paths)

    def test_duplicate_registration_is_rejected_even_with_the_same_scope(self):
        for second_scope in FieldScope:
            with self.subTest(scope=second_scope), self.assertRaisesRegex(
                ValueError, '重复登记字段：game_dir',
            ):
                build_registry((
                    ('', FieldScope.LOCAL, ('game_dir',)),
                    ('', second_scope, ('game_dir',)),
                ), schema=AppConfig)

    def test_invalid_scope_or_untyped_object_does_not_silently_pass(self):
        entries = dict(FIELD_SCOPES)
        entries['oracle.float_speed'] = 'typo'
        with self.assertRaisesRegex(ValueError, '无效字段归属：oracle.float_speed'):
            validate_registry(entries, AppConfig)
        opaque = make_dataclass('OpaqueConfig', [('options', dict)])
        with self.assertRaisesRegex(TypeError, '尚未支持的配置字段类型：options'):
            schema_paths(opaque)

    def test_registry_is_read_only_and_queries_have_stable_order(self):
        with self.assertRaises(TypeError):
            FIELD_SCOPES['game_dir'] = FieldScope.PROFILE
        paths = paths_for('appearance')
        self.assertEqual(paths, tuple(sorted(paths)))
        with self.assertRaises(ValueError):
            paths_for('unknown')

    def test_registry_import_and_validation_do_not_load_qt(self):
        code = (
            'from rw_creature_pet.config import AppConfig\n'
            'from rw_creature_pet.presets import FIELD_SCOPES, validate_registry\n'
            'validate_registry(FIELD_SCOPES, AppConfig)\n'
            'import sys\n'
            'assert not any(name.startswith("PySide6") for name in sys.modules)\n'
        )
        result = subprocess.run([sys.executable, '-c', code],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
