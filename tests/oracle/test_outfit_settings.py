"""附加外观的真实绘制、颜色缓存和角色保存链路"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager, tr
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.outfit_config import OutfitPartSettings, OutfitSettings
from rw_creature_pet.oracle.outfit_layout import Anchor, Slot, allowed_slots
from rw_creature_pet.oracle.graphics.outfit_definition import MAID, outfit_definition
from rw_creature_pet.oracle.graphics.outfits import adjusted_outfit_image, component_layers, load_outfit_image
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.interaction.input import PuppetHitMap
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.oracle.ui.desktop import OracleDesktopWindow
from rw_creature_pet.presets.appearance import apply_appearance
from rw_creature_pet.presets.fields import scope_for
from rw_creature_pet.presets.library import AppearanceLibrary
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from tests.oracle.character_fixture import isolate_characters


def change_part(settings, name, **values):
    return replace(settings, maid=replace(settings.maid, **{
        name: replace(getattr(settings.maid, name), **values)}))


class OutfitSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        isolate_characters(self, self.root)
        self.enterContext(patch('rw_creature_pet.presets.library.default_appearance_directory',
                                return_value=self.root/'appearances'))
        game = self.root/'game'
        (game/'RainWorld_Data').mkdir(parents=True)
        (game/'RainWorld_Data/resources.assets').touch()
        self.config = AppConfig(game_dir=game, oracle=OracleConfig(outfit='maid'))
        self.store = SettingsStore(self.root/'user/settings.json')
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.preset_workflow.timer.stop()
            dialog.preset_workflow.state.autosave = False
            dialog.close()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        language_manager().set_language('zh')

    def dialog(self):
        dialog = OracleSettingsDialog(self.config, self.store, assets=object())
        self.dialogs.append(dialog)
        self.enterContext(patch.object(dialog, 'space_assessment', return_value=None))
        return dialog

    def test_partial_configs_and_explicit_field_scope(self):
        config = OracleConfig.from_mapping({'outfit_settings': {'maid': {'lace': {'offset_x': 2.5}}}})
        self.assertTrue(config.outfit_settings.maid.lace.mirror)
        self.assertEqual(config.outfit_settings.maid.head, OutfitPartSettings())
        self.assertEqual(config.outfit_settings.maid.lace.offset_x, 2.5)
        for part in MAID.components:
            for field in ('enabled', 'anchor', 'layer', 'mirror', 'offset_x', 'offset_y', 'hue', 'saturation', 'brightness'):
                self.assertEqual(scope_for('oracle.outfit_settings.maid.'+part.id+'.'+field).value, 'appearance')
        for values in ({'enabled': 0}, {'mirror': 'yes'}, {'offset_x': 33}, {'hue': float('nan')},
                       {'saturation': -101}, {'brightness': True}, {'anchor': 'other'}, {'layer': 'other'}):
            with self.assertRaises(ValueError):
                OutfitPartSettings(**values)

    def test_anchor_layer_selection_save_reset_and_role_isolation(self):
        d = self.dialog()
        prefix = 'oracle.outfit_settings.maid.apron.'
        anchor, layer = (d.controls[prefix+field] for field in ('anchor', 'layer'))
        def choose(control, value):
            control.setCurrentIndex(control.findData(value))
        def available():
            return tuple(layer.itemData(i) for i in range(layer.count()) if not layer.view().isRowHidden(i))
        self.assertEqual(available(), allowed_slots(Anchor.GOWN_COLLAR))
        d.controls[prefix+'offset_x'].setValue(5)
        choose(layer, Slot.AFTER_CAPE)
        choose(anchor, Anchor.BODY_COLLAR)
        self.assertEqual(layer.currentData(), Slot.AFTER_CAPE)
        choose(anchor, Anchor.HEAD_CROWN)
        self.assertEqual(available(), allowed_slots(Anchor.HEAD_CROWN))
        self.assertEqual(layer.currentData(), Slot.FRONT_HEAD)
        self.assertEqual(d.controls[prefix+'offset_x'].value(), 5)
        choose(layer, Slot.BEHIND_HEAD)
        self.assertTrue(d.preset_workflow.flush())
        saved = self.store.load().oracle.outfit_settings.maid.apron
        self.assertEqual((saved.anchor, saved.layer), (Anchor.HEAD_CROWN, Slot.BEHIND_HEAD))
        initial = d.profile_presets.loaded
        exported = AppearanceLibrary(self.root/'export').export(d.profile_draft(), 'Moved apron')
        applied = apply_appearance(self.config, exported, self.root/'images')
        self.assertEqual(applied.oracle.outfit_settings.maid.apron, saved)
        other = ProfileLibrary().export(self.config, 'Other')
        d.preset_workflow.activate('profile', other)
        self.assertEqual((anchor.currentData(), layer.currentData()),
                         (Anchor.GOWN_COLLAR, Slot.BEFORE_SLEEVES))
        d.preset_workflow.activate('profile', initial)
        self.assertEqual((anchor.currentData(), layer.currentData()),
                         (Anchor.HEAD_CROWN, Slot.BEHIND_HEAD))
        # 单独恢复层级不会产生跨部位非法配置；恢复锚点后可再恢复原层级
        d.preset_workflow.reset_parameter(prefix+'layer')
        self.assertIn(layer.currentData(), allowed_slots(anchor.currentData()))
        d.preset_workflow.reset_parameter(prefix+'anchor')
        d.preset_workflow.reset_parameter(prefix+'layer')
        self.assertEqual((anchor.currentData(), layer.currentData()),
                         (Anchor.GOWN_COLLAR, Slot.BEFORE_SLEEVES))
        language_manager().set_language('en')
        self.assertEqual(anchor.currentText(), 'Gown collar')
        self.assertEqual(layer.itemText(layer.findData(Slot.AFTER_CAPE)), 'Above cape, below necklace')

    def test_offsets_are_logical_pixels_and_mirrored_after_adjusting(self):
        settings = change_part(OutfitSettings(), 'lace', offset_x=-3.5, offset_y=2.5)
        part = outfit_definition('maid', settings).component('lace')
        for density in (1., 1.5, 2.):
            _, base = component_layers(MAID.component('lace'), density)[0]
            (_, left), (_, right) = component_layers(part, density)
            self.assertAlmostEqual(left.x()-base.x(), -3.5)
            self.assertAlmostEqual(left.y()-base.y(), 2.5)
            self.assertAlmostEqual(right.left(), -left.right())
            self.assertEqual(right.top(), left.top())
        disabled = change_part(settings, 'lace', enabled=False)
        self.assertNotIn('lace', [p.id for p in outfit_definition('maid', disabled).components])

    def test_hsv_preserves_alpha_original_and_cached_results(self):
        path = self.root/'colors.png'
        original = QImage(3, 1, QImage.Format.Format_ARGB32)
        original.setPixelColor(0, 0, QColor(255, 0, 0, 96))
        original.setPixelColor(1, 0, QColor(200, 200, 200, 255))
        original.setPixelColor(2, 0, QColor(0, 0, 0, 0))
        original.save(str(path))
        source = load_outfit_image(str(path))
        snapshot = source.copy()
        adjusted = adjusted_outfit_image(str(path), (120, 30, -20))
        self.assertEqual([adjusted.pixelColor(x, 0).alpha() for x in range(3)], [96, 255, 0])
        self.assertGreater(adjusted.pixelColor(0, 0).green(), 190)
        self.assertEqual(adjusted.pixelColor(0, 0).red(), 0)
        gray = adjusted.pixelColor(1, 0)
        self.assertEqual(gray.red(), gray.green())
        self.assertLess(gray.red(), 200)
        self.assertEqual(source, snapshot)
        self.assertIs(adjusted_outfit_image(str(path), (0, 0, 0)), source)
        self.assertIs(adjusted_outfit_image(str(path), (120, 30, -20)), adjusted)

    def test_shifted_head_is_not_clipped_and_hit_map_invalidates(self):
        renderer = OracleRenderer()
        scene = OracleScene(self.config.oracle)
        hit = PuppetHitMap()
        before = hit.get(renderer, scene)
        settings = change_part(OutfitSettings(), 'ribbon_up', offset_x=32, offset_y=-32, mirror=True)
        scene.config = replace(scene.config, outfit_settings=settings)
        self.assertIsNot(hit.get(renderer, scene), before)
        for density in (1., 1.5, 2.):
            image = QImage(300, 300, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                renderer.draw_head(painter, Vec2(150, 150), Vec2(150, 164), Vec2(0, -1), Vec2(),
                                   outfit='maid', outfit_settings=settings, raster_scale=density)
            finally:
                painter.end()
            head = renderer._head_image
            self.assertGreater(head.width(), renderer.HEAD_PIXELS*density)
            for i in range(head.width()):
                for x, y in ((i, 0), (i, head.height()-1), (0, i), (head.width()-1, i)):
                    self.assertEqual(head.pixelColor(x, y).alpha(), 0)

    def test_autosave_restore_export_and_role_switch(self):
        d = self.dialog()
        d.tabs.setCurrentWidget(d.pages['appearance'])
        d.show()
        self.app.processEvents()
        prefix = 'oracle.outfit_settings.maid.head.'
        self.assertFalse(d.outfit_parameter_panels['maid'].isHidden())
        with patch.object(self.store, 'save', wraps=self.store.save) as save:
            d.controls[prefix+'offset_x'].setValue(3.5)
            d.controls[prefix+'brightness'].setValue(-25)
            d.controls[prefix+'mirror'].setChecked(True)
            QTest.qWait(800)
            self.assertEqual(save.call_count, 1)
        saved = self.store.load()
        self.assertEqual(saved.oracle.outfit_settings.maid.head.offset_x, 3.5)
        self.assertEqual(saved.oracle.outfit_settings.maid.head.brightness, -25)
        d.controls[prefix+'enabled'].setChecked(False)
        self.assertFalse(d.controls[prefix+'offset_x'].isEnabled())
        self.assertTrue(d.preset_workflow.flush())
        d.controls['oracle.outfit'].buttons['normal'].click()
        self.assertTrue(d.outfit_parameter_panels['maid'].isHidden())
        d.controls['oracle.outfit'].buttons['maid'].click()
        self.assertEqual(d.controls[prefix+'offset_x'].value(), 3.5)
        self.assertFalse(d.controls[prefix+'enabled'].isChecked())
        d.preset_workflow.reset_parameter(prefix+'enabled')
        self.assertTrue(d.controls[prefix+'enabled'].isChecked())
        self.assertEqual(d.controls[prefix+'offset_x'].value(), 3.5)
        self.assertTrue(d.preset_workflow.flush())
        initial = d.profile_presets.loaded
        current = d.profile_draft()
        exported = AppearanceLibrary(self.root/'export').export(current, 'Outfit')
        applied = apply_appearance(self.config, exported, self.root/'images')
        self.assertEqual(applied.oracle.outfit_settings, current.oracle.outfit_settings)
        other = ProfileLibrary().export(self.config, 'Other')
        d.preset_workflow.activate('profile', other)
        self.assertEqual(d.controls[prefix+'offset_x'].value(), 0)
        d.preset_workflow.activate('profile', initial)
        self.assertEqual(d.controls[prefix+'offset_x'].value(), 3.5)
        language_manager().set_language('en')
        self.assertEqual(d.controls[prefix+'enabled'].text(), tr('显示头饰'))
        self.assertEqual(d.controls[prefix+'enabled'].text(), 'Show headdress')

    def test_auto_save_off_discards_on_reopen(self):
        d = self.dialog()
        d.personal_controls.autosave.setChecked(False)
        d.controls['oracle.outfit_settings.maid.apron.offset_y'].setValue(8)
        d.reject()
        again = self.dialog()
        self.assertEqual(again.controls['oracle.outfit_settings.maid.apron.offset_y'].value(), 0)

    def test_old_cached_roles_keep_outfit_parts_separate_after_switch_and_reopen(self):
        d = self.dialog()
        initial = d.profile_presets.loaded
        other = ProfileLibrary().export(replace(self.config,
            oracle=replace(self.config.oracle, outfit='normal')), 'Other')
        d.preset_workflow.activate('profile', other)
        d.preset_workflow.activate('profile', initial)
        d.reject()
        # 模拟部件设置加入前就已使用过的两个角色，而非首次读取新导出的文件
        document = self.store.read_document()
        for entry in document['preset_state']['entries'].values():
            for name in ('defaults', 'overrides'):
                entry[name] = {key: value for key, value in entry[name].items()
                               if not key.startswith('oracle.outfit_settings.')}
        self.store._write(document)
        again = self.dialog()
        prefix = 'oracle.outfit_settings.maid.head.'
        again.controls[prefix+'offset_x'].setValue(3.5)
        again.controls[prefix+'brightness'].setValue(-25)
        again.controls[prefix+'enabled'].setChecked(False)
        self.assertTrue(again.preset_workflow.flush())
        again.preset_workflow.activate('profile', other)
        self.assertEqual(again.candidate().oracle.outfit, 'normal')
        self.assertEqual(again.candidate().oracle.outfit_settings, OutfitSettings())
        again.controls['oracle.outfit'].buttons['maid'].click()
        again.controls[prefix+'offset_x'].setValue(-2)
        self.assertTrue(again.preset_workflow.flush())
        again.preset_workflow.activate('profile', initial)
        self.assertEqual(again.controls[prefix+'offset_x'].value(), 3.5)
        self.assertEqual(again.controls[prefix+'brightness'].value(), -25)
        self.assertFalse(again.controls[prefix+'enabled'].isChecked())
        again.controls['oracle.outfit'].buttons['normal'].click()
        self.assertTrue(again.preset_workflow.flush())
        again.reject()
        reopened = self.dialog()
        self.assertEqual(reopened.candidate().oracle.outfit, 'normal')
        self.assertEqual(reopened.controls[prefix+'offset_x'].value(), 3.5)
        reopened.preset_workflow.activate('profile', other)
        self.assertEqual(reopened.candidate().oracle.outfit, 'maid')
        self.assertEqual(reopened.controls[prefix+'offset_x'].value(), -2)
        self.assertTrue(reopened.controls[prefix+'enabled'].isChecked())
        reopened.preset_workflow.reset_parameter(prefix+'offset_x')
        self.assertEqual(reopened.controls[prefix+'offset_x'].value(), 0)
        reopened.preset_workflow.activate('profile', initial)
        self.assertEqual(reopened.controls[prefix+'offset_x'].value(), 3.5)

    def test_applying_adjustments_keeps_the_running_puppet(self):
        assets = OracleAssets(OracleRenderer(), '', {}, '')
        with patch('rw_creature_pet.oracle.ui.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            window = OracleDesktopWindow(self.config, config_store=self.store, assets=assets)
        window.timer.stop()
        try:
            scene = window.motion.scene
            appearance = scene.appearance
            position = scene.body.chunks[0].position
            adjustments = change_part(scene.config.outfit_settings, 'head', offset_x=8, hue=75)
            updated = replace(self.config, oracle=replace(self.config.oracle, outfit_settings=adjustments))
            window.apply_settings(updated, assets)
            self.assertIs(window.motion.scene, scene)
            self.assertIs(scene.appearance, appearance)
            self.assertEqual(scene.body.chunks[0].position, position)
            self.assertEqual(scene.config.outfit_settings, adjustments)
            self.assertEqual(self.store.load().oracle.outfit_settings, adjustments)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
