"""从真实 TOML 到启动配置、全部设置控件和保存文件的默认值链路。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import fields, replace, asdict, is_dataclass
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QDoubleSpinBox, QMessageBox, QSpinBox

from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.config import CUSTOM_COLOR_NAMES, OracleColors
from rw_creature_pet.oracle.characters import PRINCE_COLOR_NAMES
from rw_creature_pet.overseer.config import OverseerSlot
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.presets.common import replace_fields, set_value
from tests.oracle.character_fixture import isolate_characters


PERCENTAGES = {
    'audio.volume', 'oracle.projection_opacity', 'oracle.glow_opacity', 'oracle.edge_fraction', 'oracle.base_fraction',
    'oracle.arm_scale',
    'oracle.drag_projection_probability',
    'oracle.reading.start_probability',
    'oracle.drift.duration_variation', 'oracle.drift.long_bout_probability',
    'oracle.mouse_avoidance.probability', 'oracle.mouse_avoidance.move_probability',
    'oracle.mouse_avoidance.lean_move_probability',
    'oracle.cross_edge_probability', 'oracle.antigravity_probability', 'oracle.pearl_playback_probability',
    'overseer.appearance_probability', 'overseer.relocation_probability', 'overseer.observation_probability',
    'interaction.hover_probability', 'interaction.hover_open_probability',
    'oracle.drag_reactions.gesture_probability', 'oracle.drag_reactions.flutter_probability',
    'oracle.drag_reactions.alternating_probability', 'oracle.drag_reactions.eye_open_probability',
    'oracle.drag_reactions.voice_probability',
    'oracle.custom_appearance.robe_flare', 'oracle.custom_appearance.robe_hem_curve',
}


def write_toml(path, data):
    # 测试配置仅含字符串、布尔、数字、列表和表；JSON 的这些字面量也是合法 TOML。
    def literal(value):
        if is_dataclass(value):
            value = asdict(value)
        if isinstance(value, dict):
            return '{ ' + ', '.join(f'{k} = {literal(v)}' for k,v in value.items()) + ' }'
        if isinstance(value, (list, tuple)):
            return '[' + ', '.join(literal(v) for v in value) + ']'
        return json.dumps(value, ensure_ascii=False)
    def table(mapping, prefix=''):
        lines = [f'[{prefix}]'] if prefix else []
        lines.extend(f'{key} = {literal(value)}'
                     for key, value in mapping.items() if not isinstance(value, dict))
        for key, value in mapping.items():
            if isinstance(value, dict):
                lines.extend(['', *table(value, f'{prefix}.{key}' if prefix else key)])
        return lines
    path.write_text('\n'.join(table(data))+'\n', encoding='utf-8')


class SettingsDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.game = self.root/'游戏'
        (self.game/'RainWorld_Data').mkdir(parents=True)
        (self.game/'RainWorld_Data/resources.assets').touch()
        source = Path(__file__).resolve().parents[2]/'config.toml'
        self.data = tomllib.loads(source.read_text(encoding='utf-8'))
        self.data['game_dir'] = str(self.game)
        self.source = self.root/'config.toml'
        self.store = SettingsStore(self.root/'profile/settings.json')
        self.enterContext(patch('rw_creature_pet.settings_store.default_template_path', return_value=self.source))

    def audit(self, config):
        dialog = OracleSettingsDialog(config, self.store)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        for key, control in dialog.controls.items():
            with self.subTest(key=key):
                # 新增控件必须同时在发布 TOML 中声明，不能仅依赖代码默认值。
                template, expected = self.data, config
                for field in key.split('.'):
                    self.assertIn(field, template)
                    template, expected = template[field], getattr(expected, field)
                if key in PERCENTAGES:
                    expected *= 100
                elif key == 'oracle.custom_appearance.head_length':
                    expected *= 100/11+1
                elif key == 'oracle.custom_appearance.robe_length':
                    expected = expected*19.13725+8.41275
                if isinstance(control, QDoubleSpinBox):
                    expected = round(expected, control.decimals())
                elif isinstance(control, QSpinBox):
                    expected = round(expected)
                self.assertEqual(dialog.value(control), expected)
        self.assertEqual(dialog.game_dir.text(), str(config.game_dir))
        self.assertEqual(dialog.start_edge_group.checkedButton().property('edge'), config.oracle.base_side)
        self.assertEqual({edge for edge, box in dialog.edge_checks.items() if box.isChecked()},
                         set(config.oracle.allowed_edges))
        self.assertEqual(dialog.candidate(), config)
        return dialog

    def test_every_panel_field_has_a_toml_default_and_survives_unchanged_save(self):
        write_toml(self.source, self.data)
        config, first, _ = self.store.startup()
        self.assertTrue(first)
        dialog = self.audit(config)
        self.store.save(dialog.candidate())
        loaded, first, message = self.store.startup()
        self.assertFalse(first)
        self.assertEqual(message, '')
        self.assertEqual(loaded, config)
        self.audit(loaded)

    def test_all_controls_follow_changed_toml_values_instead_of_fixed_defaults(self):
        values = {
            'desktop.scale': 1.5, 'desktop.autonomous': False, 'desktop.screen': 'DISPLAY2',
            'interaction.drag_enabled': False,
            'interaction.hover_avoidance_enabled': False,
            'interaction.hover_radius': 210.5, 'interaction.hover_dwell_seconds': 2.7,
            'interaction.hover_probability': .723, 'interaction.hover_open_probability': .416,
            'audio.enabled': False, 'audio.volume': .31,
            'oracle.daily_activity.idle_min_seconds': 2.12345,
            'oracle.daily_activity.idle_max_seconds': 9.67891,
            'oracle.daily_activity.long_idle_min_seconds': 15.12345,
            'oracle.daily_activity.long_idle_max_seconds': 35.67891,
            'oracle.daily_activity.move_min_distance': 45.12345,
            'oracle.daily_activity.move_max_distance': 270.67891,
            'oracle.daily_activity.idle_weight': 0.,
            'oracle.daily_activity.move_weight': 65.12345,
            'oracle.daily_activity.meditate_weight': 34.87655,
            'oracle.daily_activity.meditate_min_seconds': 42.12345,
            'oracle.daily_activity.meditate_max_seconds': 90.67891,
            'oracle.daily_activity.cross_edge_cooldown_seconds': 0.,
            'oracle.daily_activity.cross_edge_check_seconds': 7.12345,
            'oracle.daily_activity.move_lean_degrees': 12.34567,
            'oracle.reading.start_probability': .456789,
            'oracle.drift.cooldown_seconds': 80.123456,
            'oracle.drift.duration_variation': .234567,
            'oracle.drift.entry_min_seconds': .123456,
            'oracle.drift.entry_max_seconds': 9.123456,
            'oracle.drift.resume_min_seconds': .234567,
            'oracle.drift.resume_max_seconds': 11.234567,
            'oracle.drift.short_pause_min_seconds': .123456,
            'oracle.drift.short_pause_max_seconds': 2.123456,
            'oracle.drift.normal_pause_min_seconds': 3.123456,
            'oracle.drift.normal_pause_max_seconds': 7.123456,
            'oracle.drift.long_pause_min_seconds': 9.123456,
            'oracle.drift.long_pause_max_seconds': 40.123456,
            'oracle.drift.short_pause_weight': 0.,
            'oracle.drift.normal_pause_weight': 73.123456,
            'oracle.drift.long_pause_weight': 26.876544,
            'oracle.drift.bout_min_seconds': 6.123456,
            'oracle.drift.bout_max_seconds': 20.123456,
            'oracle.drift.long_bout_min_seconds': 26.123456,
            'oracle.drift.long_bout_max_seconds': 80.123456,
            'oracle.drift.long_bout_probability': .765432,
            'oracle.drift.move_min_distance': 35.123456,
            'oracle.drift.move_max_distance': 180.123456,
            'oracle.drift.speed_min_factor': .456789,
            'oracle.drift.speed_max_factor': 1.456789,
            'oracle.mouse_avoidance.delay_min_seconds': .234567,
            'oracle.mouse_avoidance.delay_max_seconds': 12.345678,
            'oracle.mouse_avoidance.probability': .123456,
            'oracle.mouse_avoidance.enter_distance': 40.123456,
            'oracle.mouse_avoidance.exit_distance': 120.123456,
            'oracle.mouse_avoidance.leave_grace_seconds': 0.,
            'oracle.mouse_avoidance.pointer_lag_seconds': .678912,
            'oracle.mouse_avoidance.retry_min_seconds': .234567,
            'oracle.mouse_avoidance.retry_max_seconds': 1.234567,
            'oracle.mouse_avoidance.impatience_min_seconds': 4.123456,
            'oracle.mouse_avoidance.impatience_max_seconds': 9.123456,
            'oracle.mouse_avoidance.move_probability': .234567,
            'oracle.mouse_avoidance.move_min_distance': 7.123456,
            'oracle.mouse_avoidance.move_max_distance': 50.123456,
            'oracle.mouse_avoidance.speed_min': .678912,
            'oracle.mouse_avoidance.speed_max': 4.567891,
            'oracle.mouse_avoidance.lean_move_probability': .345678,
            'oracle.mouse_avoidance.lean_move_min_distance': 5.123456,
            'oracle.mouse_avoidance.lean_move_max_distance': 60.123456,
            'oracle.mouse_avoidance.lean_min_degrees': 13.123456,
            'oracle.mouse_avoidance.lean_max_degrees': 43.123456,
            'oracle.mouse_avoidance.lean_sample_power': 3.123456,
            'oracle.mouse_avoidance.lean_speed': 55.123456,
            'oracle.mouse_avoidance.move_angle_jitter': 12.345678,
            'oracle.hide_cords': True, 'oracle.glow_enabled': True,
            'oracle.outfit': 'maid', 'oracle.arm_scale': .67, 'oracle.coarse_pixels_4x': True,
            'oracle.body_appearance': 'custom',
            'oracle.custom_appearance.head_length': 1.23456,
            'oracle.custom_appearance.robe_length': .87654,
            'oracle.custom_appearance.robe_flare': 1.23456,
            'oracle.custom_appearance.robe_hem_curve': .67891,
            'oracle.custom_appearance.sleeve_root_width': 4.56789,
            'oracle.custom_appearance.sleeve_cuff_width': 12.34567,
            'oracle.custom_appearance.sleeve_cuff_radius': 1.23456,
            'oracle.custom_appearance.neck_width': 4.56789,
            'oracle.custom_appearance.inner_robe_enabled': False,
            'oracle.custom_appearance.inner_collar_enabled': False,
            'oracle.custom_appearance.inner_collar_height': 5.12345,
            'oracle.custom_appearance.inner_collar_top_width': 4.56789,
            'oracle.custom_appearance.inner_collar_bottom_width': 7.12345,
            'oracle.custom_appearance.neckline_shape': 'arc',
            'oracle.custom_appearance.chest_width': 14.23456,
            'oracle.custom_appearance.chest_height': 5.12345,
            'oracle.custom_appearance.shoulder_width': 10.23456,
            'oracle.custom_appearance.neckline_width': 11.23456,
            'oracle.custom_appearance.neckline_depth': 9.12345,
            'oracle.custom_appearance.neckline_height': -1.23456,
            'oracle.custom_appearance.neckline_roundness': .712345,
            'oracle.custom_appearance.neckline_tip_radius': 1.23456,
            'oracle.custom_appearance.neckline_trim_enabled': False,
            'oracle.custom_appearance.neckline_trim_width': 1.23456,
            'oracle.custom_appearance.neckline_trim_gap': 2.12345,
            'oracle.custom_appearance.eye_1': {'color': '#f0a123', 'visible': False, 'default_open': True},
            'oracle.custom_appearance.eye_2': {'color': '#23a1f0', 'visible': True, 'default_open': False},
            'oracle.custom_appearance.forehead': {'enabled': False, 'image_path': '', 'image_name': '',
                                                 'offset_x': 1.25, 'offset_y': -2.75},
            'oracle.custom_appearance.face': {'enabled': False, 'image_path': '', 'image_name': '',
                                             'offset_x': -.25, 'offset_y': .5},
            'oracle.colors.arm': '#234567', 'oracle.colors.arm_highlight': '#abcdef',
            'oracle.colors.joints': '#102030',
            'oracle.glow_color': '#123456', 'oracle.glow_radius': 9.5, 'oracle.glow_opacity': .63,
            'oracle.pearl_matrix_enabled': False, 'oracle.pearl_matrix_count': 13,
            'oracle.pearl_matrix_avoid_radius': 123, 'oracle.pearl_orbits_enabled': False,
            'oracle.pearl_inner_count': 8, 'oracle.pearl_outer_count': 5,
            'oracle.pearl_fixed_count': 6, 'oracle.pearl_satellite_count': 3,
            'oracle.pearl_playback_probability': .67, 'oracle.pearl_bubble_max_size': 19.5,
            'oracle.pearl_bubble_color': '#654321', 'oracle.projection_opacity': .37,
            'oracle.colors.pearl_glyph': '#123abc',
            'oracle.drag_projection_probability': .42, 'oracle.drag_projection_cooldown_seconds': 73.5,
            'oracle.halo_enabled': False, 'oracle.halo_scale': 1.15,
            'oracle.halo_arcs_enabled': False, 'oracle.halo_arc_max_count': 4,
            'oracle.base_fraction': .713, 'oracle.edge_fraction': .287,
            'oracle.float_speed': 1.23, 'oracle.cross_edge_probability': .123,
            'oracle.base_speed': 3.123456,
            'oracle.pearl_follow_width': 512.3456, 'oracle.pearl_follow_height': 384.5678,
            'oracle.drag_reactions.enabled': False,
            'oracle.drag_reactions.gesture_probability': .123456,
            'oracle.drag_reactions.flutter_probability': .234567,
            'oracle.drag_reactions.alternating_probability': .345678,
            'oracle.drag_reactions.eye_open_probability': .456789,
            'oracle.drag_reactions.voice_probability': .567891,
            'oracle.antigravity_probability': .234, 'oracle.drift_speed': .87,
            'oracle.antigravity_duration_seconds': 523.4,
            'overseer.enabled': True, 'overseer.appearance_mode': 'resident',
            'overseer.slots': [{'id': 1, 'color': '#abcdef', 'appearance': 'standard'}],
            'overseer.check_interval': 17.25, 'overseer.appearance_probability': .543,
            'overseer.duration_min': 31.25, 'overseer.duration_max': 54.5,
            'overseer.cooldown_min': 72.5, 'overseer.cooldown_max': 101.25,
            'overseer.withdraw_distance': 72.5, 'overseer.reemerge_distance': 141.5,
            'overseer.puppet_withdraw_distance': 121.5, 'overseer.puppet_reemerge_distance': 201.5,
            'overseer.relocation_probability': .678,
            'overseer.observation_probability': .456, 'overseer.observation_interval': 9.25,
        }
        values.update({'oracle.colors.' + field.name: f'#{index + 1:06x}'
                       for index, field in enumerate(fields(OracleColors))})
        values.update({'oracle.custom_appearance.cape.'+key: value for key, value in {
            'enabled': True, 'length': 28.12345, 'color': '#123456', 'neckline_shape': 'v',
            'neckline_width': 11.12345, 'neckline_depth': 5.12345, 'neckline_height': 2.12345,
            'neckline_roundness': .712345, 'neckline_tip_radius': 1.12345,
            'hem_trim_enabled': False, 'hem_trim_color': '#fedcba', 'hem_trim_width': 2.12345,
            'hem_trim_gap': 3.12345,
        }.items()})
        for part in ('head', 'lace', 'apron', 'ribbon_up', 'ribbon_down'):
            anchor, layer = {
                'head': ('body_collar', 'after_cape'),
                'lace': ('head_crown', 'behind_head'),
                'apron': ('body_collar', 'front'),
                'ribbon_up': ('gown_collar', 'before_sleeves'),
                'ribbon_down': ('head_crown', 'front_head'),
            }[part]
            values.update({'oracle.outfit_settings.maid.'+part+'.'+name: value for name, value in {
                'anchor': anchor, 'layer': layer,
                'enabled': False, 'mirror': part != 'lace', 'offset_x': 2.12345, 'offset_y': -3.6789,
                'hue': 45.1234, 'saturation': -35.1234, 'brightness': 20.1234,
            }.items()})
        for index, name in enumerate(('ear_body', 'ear_part_1', 'ear_part_2', 'ear_part_3')):
            values['oracle.custom_appearance.'+name] = {
                'enabled': True, 'kind': 'triangle', 'width': 2.12345+index, 'height': 5.6789,
                'offset_x': -1.23456, 'offset_y': index+1.5, 'rotation': 35.12345,
                'tone': 'highlight', 'image_path': '', 'image_name': ''}
        for index, name in enumerate(('soft_part_1', 'soft_part_2')):
            values['oracle.custom_appearance.'+name] = {
                'enabled': True, 'kind': 'trapezoid', 'layer': 'back', 'anchor': 'waist',
                'width': 6.12345+index, 'length': 40.6789, 'offset_x': -2.23456, 'offset_y': 1.34567,
                'angle': 34.56789, 'tip_width_ratio': .423456, 'softness': .812345,
                'damping': .612345, 'color': '#abcdef', 'image_path': '', 'image_name': ''}
        for index, name in enumerate(('clothing_decal_1', 'clothing_decal_2', 'clothing_decal_3')):
            values['oracle.custom_appearance.'+name] = {
                'enabled': False, 'part': 'right_sleeve', 'image_path': '', 'image_name': '',
                'offset_x': -2.12345-index, 'offset_y': 5.6789+index}
        values.update({'oracle.custom_colors.'+name: f'#{index+256:06x}'
                       for index, name in enumerate(CUSTOM_COLOR_NAMES)})
        values.update({'oracle.prince_colors.'+name: f'#{index+512:06x}'
                       for index, name in enumerate(PRINCE_COLOR_NAMES)})
        for key, value in values.items():
            target = self.data
            *path, field = key.split('.')
            for part in path:
                target = target[part]
            target[field] = value
        self.data['oracle'].update(base_side='left', allowed_edges=['top', 'left'])
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        dialog = self.audit(config)
        self.assertEqual(set(dialog.controls), set(values))

    def test_upgraded_profile_displays_user_values_and_missing_toml_defaults(self):
        write_toml(self.source, self.data)
        self.store.path.parent.mkdir()
        self.store.path.write_text(json.dumps({'version': 1, 'config': {
            'game_dir': str(self.game), 'desktop': {'scale': 2.}, 'audio': {'enabled': False, 'volume': 0},
            'oracle': {'pearl_matrix_count': 0, 'base_side': 'left', 'base_fraction': .271},
            'overseer': {'color': '#102030'},
        }}), encoding='utf-8')
        config, first, message = self.store.startup()
        self.assertFalse(first)
        self.assertEqual(message, '')
        dialog = self.audit(config)
        self.assertEqual(dialog.controls['desktop.scale'].currentData(), 2.)
        self.assertEqual(dialog.controls['audio.volume'].value(), 0)
        self.assertEqual(dialog.controls['oracle.pearl_matrix_count'].value(), 0)
        self.assertEqual(dialog.controls['overseer.slots'].colors[1].value(), '#102030')
        self.assertEqual(config.overseer.size, self.data['overseer']['size'])
        self.assertEqual(config.oracle.pearl_bubble_color, self.data['oracle']['pearl_bubble_color'])
        self.assertEqual(config.oracle.glow_opacity, .4)
        self.assertEqual(dialog.controls['oracle.glow_opacity'].value(), 40)
        saved = json.loads(self.store.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['config']['oracle']['glow_opacity'], .4)
        self.assertFalse(saved['config']['oracle']['coarse_pixels_4x'])
        self.assertEqual(config.oracle.colors.pearl_glyph, self.data['oracle']['colors']['pearl_glyph'])
        self.assertEqual(saved['config']['oracle']['colors']['pearl_glyph'], config.oracle.colors.pearl_glyph)
        self.assertEqual(config.oracle.body_appearance, 'bell')
        self.assertEqual(saved['config']['oracle']['body_appearance'], 'bell')
        for name in ('sleeve_cuff_radius', 'neck_width', 'inner_robe_enabled', 'inner_collar_enabled',
                     'inner_collar_height', 'inner_collar_top_width', 'inner_collar_bottom_width',
                     'chest_width', 'chest_height', 'shoulder_width'):
            self.assertEqual(saved['config']['oracle']['custom_appearance'][name],
                             self.data['oracle']['custom_appearance'][name])

    def test_hidden_custom_neck_and_cuff_reset_from_current_template(self):
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        self.store.save(config)
        dialog = self.audit(config)
        for name, edited, default in (('sleeve_cuff_radius', 0., 1.2), ('neck_width', 7., 4.5),
                                      ('chest_width', 18., 11.), ('chest_height', 10., 6.),
                                      ('shoulder_width', 18., 9.)):
            dialog.controls['oracle.custom_appearance.'+name].setValue(edited)
            self.data['oracle']['custom_appearance'][name] = default
        write_toml(self.source, self.data)
        dialog.restore_defaults(dialog.tabs.indexOf(dialog.pages['appearance']))
        self.assertEqual(dialog.candidate().oracle.custom_appearance,
                         replace(config.oracle.custom_appearance, sleeve_cuff_radius=1.2, neck_width=4.5,
                                 chest_width=11., chest_height=6., shoulder_width=9.))
        self.assertEqual(self.store.load().oracle.custom_appearance, config.oracle.custom_appearance)

    def test_missing_shoulder_width_preserves_old_root_spacing_before_defaults_merge(self):
        from rw_creature_pet.oracle.config import CustomAppearance
        write_toml(self.source, self.data)
        self.store.path.parent.mkdir()
        for shape, expected in (({'chest_width': 14.}, 28/3),
                                ({'chest_width': 14., 'shoulder_width': 10.5}, 10.5),
                                ({}, self.data['oracle']['custom_appearance']['shoulder_width'])):
            with self.subTest(shape=shape):
                original = json.dumps({'version': 1, 'config': {
                    'game_dir': str(self.game), 'oracle': {'body_appearance': 'custom',
                                                         'custom_appearance': shape}}})
                self.store.path.write_text(original, encoding='utf-8')
                self.assertEqual(CustomAppearance.from_mapping(shape).shoulder_width, expected)
                loaded = self.store.load()
                self.assertEqual(loaded.oracle.custom_appearance.shoulder_width, expected)
                self.assertEqual(self.store.path.read_text(encoding='utf-8'), original)
                config, first, message = self.store.startup()
                self.assertFalse(first)
                self.assertEqual(message, '')
                self.assertEqual(config, loaded)
                self.assertEqual(self.store.path.with_suffix('.json.bak').read_text(encoding='utf-8'), original)
                # 不编辑输入框时保存仍保留完整精度，不能把 9.333… 反复舍入成 9.3
                self.assertEqual(self.audit(config).candidate(), config)
                saved = json.loads(self.store.path.read_text(encoding='utf-8'))
                self.assertEqual(saved['config']['oracle']['custom_appearance']['shoulder_width'], expected)
                with patch.object(self.store, '_write') as write:
                    self.assertEqual(self.store.startup()[0], config)
                    write.assert_not_called()

    def test_palette_reset_uses_template_and_preserves_other_tabs_and_drafts(self):
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        colors = replace(config.oracle.colors, skin='#123456', pearl_glyph='#fedcba',
                         arm='#234567', arm_highlight='#abcdef', joints='#102030')
        config = replace(config, oracle=replace(config.oracle, colors=colors))
        dialog = self.audit(config)
        dialog.controls['audio.volume'].setValue(19)
        dialog.controls['oracle.colors.pearl_glyph'].setValue('#abcdef')
        self.data['oracle']['colors']['pearl_glyph'] = '#654321'
        write_toml(self.source, self.data)
        dialog.restore_defaults(dialog.tabs.indexOf(dialog.pages['projection']))
        candidate = dialog.candidate()
        self.assertEqual(candidate.oracle.colors, replace(colors, pearl_glyph='#654321'))
        self.assertEqual(candidate.audio.volume, .19)
        self.assertFalse(self.store.path.exists())
        dialog.restore_defaults(dialog.tabs.indexOf(dialog.pages['appearance']))
        self.assertEqual(dialog.candidate().oracle.colors, OracleColors(**self.data['oracle']['colors']))
        self.assertTrue(all(editor.value() == '#654321'
                            for editor in dialog.color_editors['oracle.colors.pearl_glyph']))
        self.assertEqual(dialog.candidate().audio.volume, .19)
        self.assertFalse(self.store.path.exists())

    def test_valid_advanced_toml_values_are_not_clamped_to_ui_convenience_limits(self):
        self.data['oracle'].update(pearl_follow_width=8000.1234, pearl_follow_height=6000.2345)
        self.data['overseer'].update(check_interval=90000., duration_min=.01, duration_max=90001.,
                                     cooldown_max=100000., withdraw_distance=.5, reemerge_distance=10001.)
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        self.audit(config)

    def test_bulk_reset_requires_confirmation(self):
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        dialog = self.audit(config)
        before = dialog.candidate()
        page = dialog.pages['behavior']
        page_button = next(button for button in dialog.reset_tab_buttons if page.isAncestorOf(button))
        for button, index in ((page_button, dialog.tabs.indexOf(page)), (dialog.reset_all_button, None)):
            for answer in (QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Ok):
                def respond(box):
                    self.assertIs(box.defaultButton(), box.button(QMessageBox.StandardButton.Cancel))
                    self.assertIs(box.escapeButton(), box.button(QMessageBox.StandardButton.Cancel))
                    if index is not None:
                        self.assertIn(dialog.tabs.tabText(index), box.text())
                    return answer
                with patch.object(QMessageBox, 'exec', respond), patch.object(dialog, 'restore_defaults') as restore:
                    button.click()
                    if answer == QMessageBox.StandardButton.Ok:
                        restore.assert_called_once_with(index)
                    else:
                        restore.assert_not_called()
                    self.assertEqual(dialog.candidate(), before)

    @patch.object(QMessageBox, 'exec', lambda self: QMessageBox.StandardButton.Ok)
    def test_each_tab_restores_its_defaults_and_preserves_other_unsaved_edits(self):
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        self.store.save(config)
        saved = self.store.path.read_bytes()
        per_tab = {
            'general': {'desktop.scale': 1.5, 'audio.enabled': False, 'audio.volume': .33333,
             'oracle.coarse_pixels_4x': True,
             'oracle.glow_enabled': True, 'oracle.glow_color': '#123456', 'oracle.glow_opacity': .654321},
            'screen': {'oracle.arm_scale': .623456, 'oracle.edge_fraction': .234567,
                       'oracle.base_side': 'left', 'oracle.allowed_edges': ('top', 'left'),
                       'oracle.base_fraction': .713456},
            'behavior': {'oracle.float_speed': 1.23456, 'oracle.base_speed': 3.123456,
                         'oracle.daily_activity.idle_min_seconds': 1.234567,
                         'oracle.daily_activity.idle_max_seconds': 13.456789,
                         'oracle.daily_activity.move_weight': 0.,
                         'oracle.daily_activity.move_lean_degrees': 0.,
                         'oracle.reading.start_probability': .456789,
                         'oracle.drift.cooldown_seconds': 0.,
                         'oracle.drift.duration_variation': .234567,
                         'oracle.drift.long_bout_probability': .123456,
                         'oracle.mouse_avoidance.leave_grace_seconds': 0.,
                         'oracle.mouse_avoidance.lean_sample_power': 3.123456,
                         'oracle.mouse_avoidance.lean_move_probability': .345678,
                         'interaction.hover_probability': .234567,
                         'oracle.drag_reactions.gesture_probability': .345678,
                         'oracle.drag_reactions.voice_probability': .456789,
                         'oracle.drag_projection_probability': .567891,
                         'oracle.pearl_playback_probability': .123456,
                         'oracle.pearl_matrix_avoid_radius': 111.,
                         'oracle.pearl_follow_width': 512.3456, 'oracle.pearl_follow_height': 384.5678},
            'pearls': {'oracle.pearl_matrix_count': 13,
             'oracle.pearl_bubble_color': '#654321'},
            'projection': {'oracle.halo_enabled': False, 'oracle.halo_scale': 1.15, 'oracle.projection_opacity': .334455},
            'overseer': {'overseer.enabled': True, 'overseer.check_interval': 90000.,
             'overseer.slots': (OverseerSlot(color='#abcdef'),), 'overseer.appearance_probability': .54321},
            'appearance': {'oracle.outfit': 'maid', 'oracle.body_appearance': 'custom',
                           'oracle.pearl_bubble_color': '#654321'},
        }
        for values in per_tab.values():
            for key, value in values.items():
                set_value(self.data, key, value)
        # 打开窗口后再修改模板，按钮必须读取当前 TOML，而非用户文件或代码默认值。
        for page_key, defaults in per_tab.items():
            with self.subTest(tab=page_key):
                dialog = self.audit(config)
                dialog.controls['audio.volume'].setValue(19)
                dialog.controls['oracle.arm_scale'].setValue(70)
                dialog.controls['oracle.pearl_matrix_count'].setValue(23)
                dialog.controls['oracle.halo_scale'].setValue(.9)
                dialog.controls['oracle.float_speed'].setValue(1.4)
                dialog.controls['oracle.drag_reactions.voice_probability'].setValue(12)
                dialog.controls['overseer.check_interval'].setValue(99)
                before = dialog.candidate()
                write_toml(self.source, self.data)
                page = dialog.pages[page_key]
                dialog.tabs.setCurrentWidget(page)
                self.app.processEvents()
                bar = dialog.tabs.currentWidget().verticalScrollBar()
                bar.setValue(15)
                scroll = bar.value()
                next(button for button in dialog.reset_tab_buttons if page.isAncestorOf(button)).click()
                changes = {}
                for key, value in defaults.items():
                    if key == 'oracle.body_appearance':
                        continue  # 程序默认值不切换当前角色的类型
                    set_value(changes, key, value)
                expected = replace_fields(before, changes)
                self.assertEqual(dialog.candidate(), expected)
                self.assertIs(dialog.tabs.currentWidget(), page)
                self.assertEqual(bar.value(), scroll)
                self.assertEqual(self.store.path.read_bytes(), saved)
                if page_key == 'general':
                    self.assertFalse(dialog.controls['audio.volume'].isEnabled())
                    self.assertTrue(dialog.controls['oracle.glow_opacity'].isEnabled())
                elif page_key == 'projection':
                    self.assertFalse(dialog.controls['oracle.halo_arc_max_count'].isEnabled())
                dialog.close()

    @patch.object(QMessageBox, 'exec', lambda self: QMessageBox.StandardButton.Ok)
    def test_reset_all_is_a_draft_and_preserves_hidden_settings_then_saves_exact_defaults(self):
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        config = replace(config, oracle=replace(config.oracle, world_width=1234., base_speed=3.1, colors=replace(
            config.oracle.colors, skin='#123456', pearl_glyph='#fedcba',
            arm='#234567', arm_highlight='#abcdef', joints='#102030')))
        self.store.save(config)
        saved = self.store.path.read_bytes()
        dialog = self.audit(config)
        dialog.game_dir.setText('missing directory')
        dialog.controls['desktop.scale'].setCurrentIndex(2)
        self.data['audio']['volume'] = .701234  # 与旧值显示相同，仍须替换成新的精确默认值。
        self.data['oracle'].update(arm_scale=.623456, glow_opacity=.401234,
                                   coarse_pixels_4x=True,
                                   base_side='left', allowed_edges=['left'], base_fraction=.713456)
        self.data['oracle']['colors']['pearl_glyph'] = '#654321'
        write_toml(self.source, self.data)
        template_bytes = self.source.read_bytes()
        from rw_creature_pet.settings_store import load_defaults
        defaults = load_defaults()
        expected = replace(defaults, oracle=replace(defaults.oracle, world_width=1234.), ui=config.ui)
        dialog.reset_all_button.click()
        self.assertEqual(dialog.candidate(), expected)
        self.assertEqual(self.store.path.read_bytes(), saved)
        self.assertEqual(dialog.original, config)
        dialog.reject()
        self.assertEqual(self.store.path.read_bytes(), saved)

        dialog = self.audit(config)
        dialog.reset_all_button.click()
        # 重置后继续编辑；其余默认字段保留精度，保存失败时也不清空草稿。
        dialog.controls['audio.volume'].setValue(23)
        expected = replace(expected, audio=replace(expected.audio, volume=.23))
        dialog.assets = object()
        with patch.object(self.store, 'save', side_effect=PermissionError('locked')):
            dialog.save()
        self.assertEqual(dialog.candidate(), expected)
        self.assertEqual(self.store.path.read_bytes(), saved)
        dialog.save()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.store.load(), expected)
        self.assertEqual(self.source.read_bytes(), template_bytes)
        self.audit(expected)

    @patch.object(QMessageBox, 'exec', lambda self: QMessageBox.StandardButton.Ok)
    def test_bad_template_preserves_draft_and_reset_buttons_are_disabled_while_saving(self):
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        dialog = self.audit(config)
        dialog.controls['audio.volume'].setValue(27)
        before = dialog.candidate()
        self.source.write_text('[broken', encoding='utf-8')
        for button in (dialog.reset_all_button, *dialog.reset_tab_buttons):
            button.click()
            self.assertEqual(dialog.candidate(), before)
            self.assertEqual(dialog._status_message.source, '无法读取默认设置：{error}')
        self.assertFalse(self.store.path.exists())
        dialog.busy(True)
        self.assertTrue(all(not button.isEnabled() for button in (dialog.reset_all_button, *dialog.reset_tab_buttons)))
        dialog.busy(False)
        self.assertTrue(all(button.isEnabled() for button in (dialog.reset_all_button, *dialog.reset_tab_buttons)))


if __name__ == '__main__':
    unittest.main()
