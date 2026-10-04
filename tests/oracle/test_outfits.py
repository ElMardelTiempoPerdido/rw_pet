"""套装附件的原图倍率、像素间距、遮挡及外观设置保存。"""
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from math import cos, radians, sin
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager, tr
from rw_creature_pet.oracle.assets import OracleAssets
from rw_creature_pet.oracle.config import OracleColors, OracleConfig
from rw_creature_pet.oracle.appearance import OracleAppearance, perpendicular
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.input import PuppetHitMap
from rw_creature_pet.oracle.outfits import (MAID_LACE_OFFSETS, MAID_RIBBON_UP_OFFSETS, MAID_RIBBON_DOWN_OFFSETS,
                                           load_maid_head, load_maid_lace, maid_apron_layer,
                                           maid_head_layer, maid_lace_layers, maid_ribbon_up_layer,
                                           maid_ribbon_down_layer)
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.ui_config import UiConfig


class OutfitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def paint_head(self, renderer, scale, outfit, *, tilt=0, dpr=1, offset=Vec2(), gaze=Vec2()):
        image = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        direction = Vec2(sin(radians(tilt)), -cos(radians(tilt)))
        try:
            painter.scale(scale/dpr, scale/dpr)
            renderer.draw_head(painter, offset, offset-direction*14, direction, gaze,
                               pixelated=True, raster_scale=scale, outfit=outfit)
        finally:
            painter.end()
        return renderer._head_image

    def test_native_assets_and_exact_top_gaps_at_three_scales(self):
        renderer = OracleRenderer()
        crown = -50/11-renderer.HEAD_CROWN_RISE
        for scale, dimensions, gap in ((1., (11, 5), 3), (1.5, (18, 8), 4), (2., (24, 10), 5)):
            cap, rect = maid_head_layer(scale, crown)
            self.assertEqual((cap.width(), cap.height()), dimensions)
            self.assertAlmostEqual(rect.center().x(), 0.)
            self.assertAlmostEqual((crown-rect.top())*scale, gap)
            self.assertAlmostEqual(rect.width()*scale, cap.width())
            normal = self.paint_head(renderer, scale, 'normal')
            ribbon, rect = maid_ribbon_up_layer(scale, crown)
            transparent = ribbon.copy()
            transparent.fill(0)
            # 单独检查后方头巾；新增蝴蝶结按要求覆盖头部，另行验证其前景层。
            with patch('rw_creature_pet.oracle.render.maid_ribbon_up_layer', return_value=(transparent, rect)):
                maid = self.paint_head(renderer, scale, 'maid')
            points = lambda img: [(x, y) for x in range(img.width()) for y in range(img.height())
                                  if img.pixelColor(x, y).alpha()]
            self.assertEqual(min(y for x,y in points(normal))-min(y for x,y in points(maid)), gap)
            for x, y in points(normal):
                self.assertEqual(maid.pixelColor(x, y), normal.pixelColor(x, y), '头饰必须被原有头部遮挡')
            self.assertEqual(set(bytes(maid.constBits())[3::4]), {0, 255})

    def test_cache_dpi_rotation_and_return_to_normal(self):
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            normal = self.paint_head(renderer, scale, 'normal')
            cap = self.paint_head(renderer, scale, 'maid')
            self.assertIs(self.paint_head(renderer, scale, 'maid', dpr=1.5, offset=Vec2(5, 8)), cap)
            self.assertIs(load_maid_head(scale), load_maid_head(scale))
            for angle in range(-180, 181, 30):
                image = self.paint_head(renderer, scale, 'maid', tilt=angle, gaze=Vec2(.7, -.5))
                for i in range(image.width()):
                    self.assertEqual(image.pixelColor(i, 0).alpha(), 0)
                    self.assertEqual(image.pixelColor(i, image.height()-1).alpha(), 0)
                    self.assertEqual(image.pixelColor(0, i).alpha(), 0)
                    self.assertEqual(image.pixelColor(image.width()-1, i).alpha(), 0)
            restored = self.paint_head(renderer, scale, 'normal')
            self.assertEqual(bytes(restored.constBits()), bytes(normal.constBits()))

    def test_ribbon_offsets_and_head_ribbon_covers_head(self):
        renderer = OracleRenderer()
        crown = -50/11-renderer.HEAD_CROWN_RISE
        total_overlap = 0
        for scale in (1., 1.5, 2.):
            ribbon, rect = maid_ribbon_up_layer(scale, crown)
            right, rise = MAID_RIBBON_UP_OFFSETS[scale]
            self.assertAlmostEqual(rect.left()*scale, right)
            self.assertAlmostEqual((crown-rect.top())*scale, rise)
            self.assertAlmostEqual(rect.width()*scale, ribbon.width())
            self.assertIs(maid_ribbon_up_layer(scale, crown)[0], ribbon)
            down, chest_rect = maid_ribbon_down_layer(scale)
            self.assertEqual(chest_rect.center().x(), 0.)
            self.assertAlmostEqual(chest_rect.top()*scale, MAID_RIBBON_DOWN_OFFSETS[scale])
            self.assertAlmostEqual(chest_rect.width()*scale, down.width())
            normal = self.paint_head(renderer, scale, 'normal')
            actual = self.paint_head(renderer, scale, 'maid')
            overlay = QImage(actual.size(), actual.format())
            overlay.fill(0)
            painter = QPainter(overlay)
            try:
                painter.translate(overlay.width()/2, overlay.height()/2)
                painter.scale(scale, scale)
                painter.drawImage(rect, ribbon)
            finally:
                painter.end()
            overlap = 0
            for y in range(overlay.height()):
                for x in range(overlay.width()):
                    color = overlay.pixelColor(x, y)
                    if color.alpha() == 255:
                        self.assertEqual(actual.pixelColor(x, y), color)
                        overlap += normal.pixelColor(x, y).alpha() == 255
            total_overlap += overlap
        self.assertGreater(total_overlap, 0, '确实覆盖到头部原有像素')

    def test_chest_ribbon_is_above_head_and_reuses_its_rotated_image(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True, halo_enabled=False))
        renderer = OracleRenderer()
        def cover(painter, *args, **kwargs):
            painter.fillRect(QRectF(0, 0, 960, 600), QColor('#cc00ff'))
        for scale in (1., 1.5, 2.):
            for direct in (False, True):
                image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                try:
                    painter.scale(scale, scale)
                    # 故意让头部绘制覆盖整个画布，确保胸口配饰真正处于最终前景。
                    with patch.object(renderer, 'draw_head', side_effect=cover):
                        if direct:
                            renderer.draw_geometry(painter, scene, halo=False, arm=False, cords=False, pearl=False)
                        else:
                            renderer.draw(painter, scene)
                    overlay = renderer._chest_ribbon_image
                    target = renderer._chest_ribbon_target
                    for y in range(overlay.height()):
                        for x in range(overlay.width()):
                            color = overlay.pixelColor(x, y)
                            if color.alpha() == 255:
                                self.assertEqual(image.pixelColor(round(target.x()*scale)+x,
                                                                  round(target.y()*scale)+y), color)
                    renderer.draw_chest_ribbon(painter, scene)
                    self.assertIs(renderer._chest_ribbon_image, overlay)
                finally:
                    painter.end()

    def paint_chest_ribbon(self, renderer, scene, scale, angle, origin=Vec2(32, 32), dpr=1.):
        image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        image.setDevicePixelRatio(dpr)
        painter = QPainter(image)
        axis = Vec2(sin(radians(angle)), -cos(radians(angle)))
        try:
            painter.scale(scale/dpr, scale/dpr)
            with patch.object(renderer, 'gown_axis', return_value=(origin, axis)):
                renderer.draw_chest_ribbon(painter, scene)
        finally:
            painter.end()
        return image

    def test_chest_ribbon_near_front_keeps_pixels_with_stationary_collar(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True))
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            front = self.paint_chest_ribbon(renderer, scene, scale, 0)
            reference = bytes(front.constBits())
            # 顺逆序反复越过正面，领口不动；亚像素旋转不应引起整张配饰跳一格。
            for angle in (-.1, -.01, 0, .01, .1, -.1, .1, 0):
                with self.subTest(scale=scale, angle=angle):
                    actual = self.paint_chest_ribbon(renderer, scene, scale, angle)
                    self.assertEqual(bytes(actual.constBits()), reference)
            image = renderer._chest_ribbon_image
            actual = self.paint_chest_ribbon(renderer, scene, scale, 0, dpr=1.5)
            self.assertEqual(bytes(actual.constBits()), reference)
            self.assertIs(renderer._chest_ribbon_image, image)

    def test_chest_ribbon_full_rotation_and_translation_preserve_anchor_and_cache(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True))
        renderer = OracleRenderer()
        for scale in (1., 1.5, 2.):
            self.paint_chest_ribbon(renderer, scene, scale, 0)
            canvas_size = renderer._chest_ribbon_image.size()
            anchor_target = QRectF(renderer._chest_ribbon_target)
            source, rect = maid_ribbon_down_layer(scale)
            front = renderer._chest_ribbon_image
            # 正面时保留原图完整像素与领口下移量。
            left = (front.width()-source.width()+1)//2
            top = front.height()//2+round(rect.top()*scale)
            self.assertEqual(front.copy(left, top, source.width(), source.height()), source)
            for angle in range(-180, 181, 15):
                with self.subTest(scale=scale, angle=angle):
                    self.paint_chest_ribbon(renderer, scene, scale, angle)
                    rotated = renderer._chest_ribbon_image
                    self.assertEqual(rotated.size(), canvas_size)
                    self.assertEqual(renderer._chest_ribbon_target, anchor_target)
                    if angle % 90 == 0:
                        self.assertEqual(rotated, front.transformed(QTransform().rotate(angle)))
                    self.assertIn(255, bytes(rotated.constBits())[3::4])
                    for i in range(rotated.width()):
                        self.assertEqual(rotated.pixelColor(i, 0).alpha(), 0)
                        self.assertEqual(rotated.pixelColor(i, rotated.height()-1).alpha(), 0)
                        self.assertEqual(rotated.pixelColor(0, i).alpha(), 0)
                        self.assertEqual(rotated.pixelColor(rotated.width()-1, i).alpha(), 0)
                    offset = Vec2(5/scale, 3/scale)
                    self.paint_chest_ribbon(renderer, scene, scale, angle, Vec2(32, 32)+offset)
                    self.assertIs(renderer._chest_ribbon_image, rotated)
                    self.assertAlmostEqual((renderer._chest_ribbon_target.x()-anchor_target.x())*scale, 5.)
                    self.assertAlmostEqual((renderer._chest_ribbon_target.y()-anchor_target.y())*scale, 3.)

    def test_skin_changes_invalidate_head_and_hit_map_without_body_rebuild(self):
        scene, renderer = OracleScene(), OracleRenderer()
        hit = PuppetHitMap()
        first = hit.get(renderer, scene)
        original_head = renderer._head_image
        with patch.object(renderer, 'draw_body', wraps=renderer.draw_body) as body:
            scene.config = replace(scene.config, outfit='maid')
            second = hit.get(renderer, scene)
            self.assertIsNot(second, first)
            self.assertIsNot(renderer._head_image, original_head)
            body.assert_not_called()
            self.assertIs(hit.get(renderer, scene), second)

    def test_lace_native_pixels_offsets_and_mirror(self):
        renderer = OracleRenderer()
        # 选领口恰好落在显示像素网格的姿态，检查最终光栅而非只检查矩形参数。
        upper, direction, head = Vec2(32, 40), Vec2(0, -1), Vec2(32, 30.5)
        for scale, (gap, down) in MAID_LACE_OFFSETS.items():
            gap, down = int(gap), int(down)
            source, _ = load_maid_lace(scale)
            width, height = source.width(), source.height()
            image = QImage(round(64*scale), round(64*scale), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                painter.scale(scale, scale)
                renderer.draw_shoulder_lace(painter, upper, direction, head, scale)
            finally:
                painter.end()
            (left, rect), (right, mirrored) = maid_lace_layers(scale)
            self.assertEqual((left.width(), left.height()), (width, height))
            self.assertAlmostEqual(rect.right()*scale, -gap)
            self.assertAlmostEqual(mirrored.left()*scale, gap)
            self.assertAlmostEqual(rect.top()*scale, down)
            self.assertIs(load_maid_lace(scale)[1], right, '水平翻转只在首次加载时计算')
            mid, top = round(32*scale), round(37*scale)+down
            for y in range(height):
                for x in range(width):
                    self.assertEqual(image.pixelColor(mid-gap-width+x, top+y), left.pixelColor(x, y))
                    self.assertEqual(image.pixelColor(mid+gap+x, top+y), left.pixelColor(width-1-x, y))
            self.assertEqual(set(bytes(image.constBits())[3::4]), {0, 255})

    def test_lace_scale_and_outfit_invalidate_raster_but_reuse_body_geometry(self):
        scene = OracleScene(OracleConfig(hide_cords=True, halo_enabled=False))
        renderer = OracleRenderer()
        def paint(scale=1., dpr=1.):
            image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            image.setDevicePixelRatio(dpr)
            painter = QPainter(image)
            try:
                painter.scale(scale/dpr, scale/dpr)
                renderer.draw(painter, scene)
            finally:
                painter.end()
            return bytes(renderer._raster_image.constBits())
        normal = paint()
        body_frame = renderer._body_frame
        scene.config = replace(scene.config, outfit='maid', glow_enabled=True)
        previous = geometry = None
        for scale in (1., 1.5, 2.):
            paint(scale)
            raster, frame = renderer._raster_image, renderer._frame
            self.assertIsNot(raster, previous)
            self.assertIs(renderer._body_frame, body_frame)
            if geometry is not None:
                self.assertIs(renderer._apron_geometry, geometry, '缩放复用围裙裁剪几何')
            geometry = renderer._apron_geometry
            self.assertIsNotNone(renderer._body_glow.image)
            paint(scale, dpr=1.5)
            self.assertIs(renderer._raster_image, raster)
            self.assertIs(renderer._frame, frame)
            previous = raster
        scene.config = replace(scene.config, outfit='normal', glow_enabled=False)
        self.assertEqual(paint(), normal)

    def test_apron_native_size_center_and_collar_offsets(self):
        for scale, dimensions, down in ((1., (17, 33), 1), (1.5, (27, 50), 3), (2., (34, 66), 4)):
            image, rect = maid_apron_layer(scale)
            self.assertEqual((image.width(), image.height()), dimensions)
            self.assertEqual(rect.center().x(), 0.)
            self.assertAlmostEqual(rect.top()*scale, down)
            self.assertAlmostEqual(rect.width()*scale, image.width())
            self.assertAlmostEqual(rect.height()*scale, image.height())
            self.assertIs(maid_apron_layer(scale)[0], image)

    def test_maid_apron_cannot_cover_sleeves_and_direct_matches_cached_layers(self):
        scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True))
        renderer = OracleRenderer()
        def paint(scale, *, cached=True, sleeves_only=False):
            image = QImage(round(960*scale), round(600*scale), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            try:
                painter.scale(scale, scale)
                if sleeves_only:
                    renderer._sleeve_frame.replay(painter)
                else:
                    renderer.draw_geometry(painter, scene, cords=False, arm=False, pearl=False,
                                           halo=False, include_head=False, cache_body=cached)
            finally:
                painter.end()
            return bytes(image.constBits())
        for scale in (1., 1.5, 2.):
            with self.subTest(scale=scale):
                complete = paint(scale)
                self.assertEqual(complete, paint(scale, cached=False))
                # 隔离最上方的项链/花边，检查袖子和手掌的全部不透明像素。
                # 打开围裙不能覆盖这些像素，即使围裙与它们在衣袍范围内重叠。
                with patch.object(renderer, 'draw_shoulder_lace'), patch.object(renderer, 'draw_necklace'):
                    covered = paint(scale)
                    with patch.object(renderer, 'draw_apron'):
                        bare = paint(scale)
                    sleeves = paint(scale, sleeves_only=True)
                    self.assertNotEqual(covered, bare, '围裙确实显示')
                    for i in range(0, len(sleeves), 4):
                        if sleeves[i+3] == 255:
                            self.assertEqual(covered[i:i+4], bare[i:i+4])

    def test_apron_stays_inside_actual_clothes_when_tilted_and_swung(self):
        renderer = OracleRenderer(colors=OracleColors(inner_robe='#ffffff', robe_top='#ffffff',
                                                      robe_bottom='#ffffff', skin='#ff0000'))
        for angle, swing in ((0, 0), (35, 12), (90, -10), (180, 12)):
            scene = OracleScene(OracleConfig(outfit='maid', hide_cords=True))
            upper = Vec2(48, 48)
            direction = Vec2(sin(radians(angle)), -cos(radians(angle)))
            lower, head = upper-direction*9, upper+direction*14
            for part, position in zip((*scene.body.chunks, scene.head), (upper, lower, head)):
                part.position = part.previous_position = position
            scene.appearance = app = OracleAppearance(scene)
            n = app.CLOTH_DIVS
            for i, part in enumerate(app.cloth):
                part.position += perpendicular(direction)*(swing*(i//n)/(n-1))
                part.previous_position = part.position
            for scale in (1., 1.5, 2.):
                with self.subTest(angle=angle, swing=swing, scale=scale):
                    clothes = QImage(round(96*scale), round(96*scale), QImage.Format.Format_ARGB32_Premultiplied)
                    clothes.fill(0)
                    painter = QPainter(clothes)
                    try:
                        painter.scale(scale, scale)
                        renderer.draw_inner_robe(painter, upper, lower, direction, head)
                        opening, _, gown = renderer.draw_gown(painter, scene, 1.)
                    finally:
                        painter.end()
                    apron = QImage(clothes.size(), clothes.format())
                    apron.fill(0)
                    painter = QPainter(apron)
                    try:
                        painter.scale(scale, scale)
                        renderer.draw_apron(painter, scene, 1., upper, lower, direction, head,
                                            opening, gown, scale)
                    finally:
                        painter.end()
                    visible = [(x, y) for y in range(apron.height()) for x in range(apron.width())
                               if apron.pixelColor(x, y).alpha()]
                    self.assertGreater(len(visible), 30)
                    for x, y in visible:
                        self.assertEqual(clothes.pixelColor(x, y), QColor('#ffffff'), (x, y))
                    self.assertEqual(set(bytes(apron.constBits())[3::4]), {0, 255})
                    # 整张贴图的轴线必须通过衣袍中央列的两端，不能跟随固定的屏幕竖轴。
                    _, origin, drawn_angle = renderer._apron_geometry
                    axis = Vec2(sin(radians(drawn_angle)), -cos(radians(drawn_angle)))
                    top, bottom = app.cloth[n//2].position, app.cloth[-n+n//2].position
                    for p in (top, bottom):
                        delta = p-origin
                        self.assertAlmostEqual(delta.x*axis.y-delta.y*axis.x, 0.)

    def test_defaults_old_profile_radio_selection_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'RainWorld_Data').mkdir()
            (root/'RainWorld_Data/resources.assets').touch()
            store = SettingsStore(root/'settings.json')
            store.path.write_text(json.dumps({'version': 1, 'config': {'game_dir': str(root)}}), encoding='utf-8')
            config, _, _ = store.startup()
            self.assertEqual(config.oracle.outfit, 'normal')
            self.assertEqual(json.loads(store.path.read_text())['config']['oracle']['outfit'], 'normal')
            config = replace(config, ui=UiConfig('zh'))
            dialog = OracleSettingsDialog(config, store, first_run=True, assets=OracleAssets(OracleRenderer(), '', {}, ''))
            try:
                selector = dialog.controls['oracle.outfit']
                self.assertEqual(dialog.tabs.tabText(1), '外观')
                self.assertTrue(selector.buttons['normal'].isChecked())
                selector.buttons['maid'].click()
                self.assertFalse(selector.buttons['normal'].isChecked())
                self.assertEqual(dialog.candidate().oracle.outfit, 'maid')
                self.assertEqual(store.load().oracle.outfit, 'normal', '点击单选项不应提前保存')
                language_manager().set_language('en')
                self.assertEqual(dialog.tabs.tabText(1), tr('外观'))
                self.assertEqual(selector.buttons['maid'].text(), tr('女仆套装'))
                self.assertEqual(selector.value(), 'maid')
                dialog.save()
                self.assertEqual(store.load().oracle.outfit, 'maid')
                reopened = OracleSettingsDialog(store.load(), store)
                try:
                    self.assertEqual(reopened.controls['oracle.outfit'].value(), 'maid')
                finally:
                    reopened.close()
                    reopened.deleteLater()
            finally:
                dialog.close()
                dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                language_manager().set_language('zh')
        with self.assertRaises(ValueError):
            OracleConfig(outfit='invalid')

    def test_applying_only_outfit_preserves_scene_position_and_save_failure_keeps_outfit(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp)/'settings.json')
            config = AppConfig(ui=UiConfig('zh'))
            assets = OracleAssets(OracleRenderer(), '', {}, '')
            with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
                window = OracleDesktopWindow(config, config_store=store, assets=assets)
            window.timer.stop()
            try:
                scene = window.motion.scene
                appearance = scene.appearance
                position = scene.body.chunks[0].position
                updated = replace(config, oracle=replace(config.oracle, outfit='maid'))
                with patch.object(store, 'save', side_effect=OSError('locked')):
                    with self.assertRaises(OSError):
                        window.apply_settings(updated, assets)
                self.assertEqual(scene.config.outfit, 'normal')
                window.apply_settings(updated, assets)
                self.assertIs(window.motion.scene, scene)
                self.assertIs(scene.appearance, appearance)
                self.assertEqual(scene.body.chunks[0].position, position)
                self.assertEqual(scene.config.outfit, 'maid')
                self.assertEqual(store.load().oracle.outfit, 'maid')
            finally:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
