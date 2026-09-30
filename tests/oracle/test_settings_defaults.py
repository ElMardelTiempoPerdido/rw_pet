"""从真实 TOML 到启动配置、全部设置控件和保存文件的默认值链路。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox

from rw_creature_pet.oracle.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore


PERCENTAGES = {
    'audio.volume', 'oracle.projection_opacity', 'oracle.edge_fraction', 'oracle.base_fraction',
    'oracle.cross_edge_probability', 'oracle.antigravity_probability', 'oracle.pearl_playback_probability',
    'overseer.appearance_probability', 'overseer.relocation_probability',
}


def write_toml(path, data):
    # 测试配置仅含字符串、布尔、数字、列表和表；JSON 的这些字面量也是合法 TOML。
    def table(mapping, prefix=''):
        lines = [f'[{prefix}]'] if prefix else []
        lines.extend(f'{key} = {json.dumps(value, ensure_ascii=False)}'
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
                group, field = key.split('.')
                # 新增控件必须同时在发布 TOML 中声明，不能仅依赖代码默认值。
                self.assertIn(field, self.data[group])
                expected = getattr(getattr(config, group), field)
                if key in PERCENTAGES:
                    expected *= 100
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
            'desktop.scale': 1.5, 'desktop.autonomous': False, 'interaction.drag_enabled': False,
            'audio.enabled': False, 'audio.volume': .31,
            'oracle.hide_cords': True, 'oracle.glow_enabled': True,
            'oracle.glow_color': '#123456', 'oracle.glow_radius': 9.5,
            'oracle.pearl_matrix_enabled': False, 'oracle.pearl_matrix_count': 13,
            'oracle.pearl_matrix_avoid_radius': 123, 'oracle.pearl_orbits_enabled': False,
            'oracle.pearl_inner_count': 8, 'oracle.pearl_outer_count': 5,
            'oracle.pearl_fixed_count': 6, 'oracle.pearl_satellite_count': 3,
            'oracle.pearl_playback_probability': .67, 'oracle.pearl_bubble_max_size': 19.5,
            'oracle.pearl_bubble_color': '#654321', 'oracle.projection_opacity': .37,
            'oracle.halo_enabled': False, 'oracle.halo_scale': 1.15,
            'oracle.halo_arcs_enabled': False, 'oracle.halo_arc_max_count': 4,
            'oracle.base_fraction': .713, 'oracle.edge_fraction': .287,
            'oracle.float_speed': 1.23, 'oracle.cross_edge_probability': .123,
            'oracle.antigravity_probability': .234, 'oracle.drift_speed': .87,
            'oracle.antigravity_duration_seconds': 523.4,
            'overseer.enabled': True, 'overseer.color': '#abcdef',
            'overseer.check_interval': 17.25, 'overseer.appearance_probability': .543,
            'overseer.duration_min': 31.25, 'overseer.duration_max': 54.5,
            'overseer.cooldown_min': 72.5, 'overseer.cooldown_max': 101.25,
            'overseer.withdraw_distance': 72.5, 'overseer.reemerge_distance': 141.5,
            'overseer.puppet_withdraw_distance': 121.5, 'overseer.puppet_reemerge_distance': 201.5,
            'overseer.relocation_probability': .678,
        }
        for key, value in values.items():
            group, field = key.split('.')
            self.data[group][field] = value
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
        self.assertEqual(dialog.controls['overseer.color'].value(), '#102030')
        self.assertEqual(config.overseer.size, self.data['overseer']['size'])
        self.assertEqual(config.oracle.pearl_bubble_color, self.data['oracle']['pearl_bubble_color'])

    def test_valid_advanced_toml_values_are_not_clamped_to_ui_convenience_limits(self):
        self.data['overseer'].update(check_interval=90000., duration_min=.01, duration_max=90001.,
                                     cooldown_max=100000., withdraw_distance=.5, reemerge_distance=10001.)
        write_toml(self.source, self.data)
        config, _, _ = self.store.startup()
        self.audit(config)


if __name__ == '__main__':
    unittest.main()
