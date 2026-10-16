"""按实际渲染像素检查边框，并验证中英文使用随程序提供的字体。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from contextlib import chdir
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtGui import QFont, QImage, QPainter, QTextLayout
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from tests.oracle.character_fixture import isolate_characters
from rw_creature_pet.oracle.ui.settings_style import INK, PAPER, pixel_box, pixel_rule, settings_font, settings_font_family
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.ui_config import UiConfig


def run_lengths(indices):
    groups = []
    for index in indices:
        if groups and index == groups[-1][-1] + 1:
            groups[-1].append(index)
        else:
            groups.append([index])
    return [len(group) for group in groups]


class SettingsStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_outline_has_equal_physical_width_on_all_sides_at_fractional_dpi(self):
        # 同时覆盖奇偶尺寸、控件位置及来自父控件的非整数设备偏移。
        for dpr in (1., 1.25, 1.5, 1.75, 2.):
            for size in (100, 101):
                for origin in (10, 11):
                    for translation in (0., .5, 1.):
                        with self.subTest(dpr=dpr, size=size, origin=origin, translation=translation):
                            image = QImage(round(140*dpr), round(100*dpr),
                                           QImage.Format.Format_ARGB32_Premultiplied)
                            image.setDevicePixelRatio(dpr)
                            image.fill(PAPER)
                            painter = QPainter(image)
                            painter.translate(translation, translation)
                            pixel_box(painter, QRect(origin, origin, size, 60))
                            painter.end()
                            x = round((origin+translation+size/2)*dpr)
                            y = round((origin+translation+30)*dpr)
                            sides = run_lengths([col for col in range(image.width())
                                                 if image.pixelColor(col, y) == INK])
                            ends = run_lengths([row for row in range(image.height())
                                                if image.pixelColor(x, row) == INK])
                            self.assertEqual(sides, [1, 1])
                            self.assertEqual(ends, [1, 1])

    def test_rule_dots_keep_fixed_physical_dimensions_at_fractional_dpi(self):
        for dpr in (1., 1.25, 1.5, 1.75, 2.):
            for thickness in (1, 2):
                for translation in (0., .5, 1.):
                    with self.subTest(dpr=dpr, thickness=thickness, translation=translation):
                        image = QImage(round(140*dpr), round(24*dpr), QImage.Format.Format_ARGB32_Premultiplied)
                        image.setDevicePixelRatio(dpr)
                        image.fill(PAPER)
                        painter = QPainter(image)
                        painter.translate(translation, translation)
                        pixel_rule(painter, QRect(10, 10, 100, 3), thickness=thickness)
                        painter.end()
                        rows = []
                        for y in range(image.height()):
                            columns = [x for x in range(image.width()) if image.pixelColor(x, y) == INK]
                            if columns:
                                rows.append(columns)
                        self.assertEqual(len(rows), thickness)
                        self.assertTrue(all(columns == rows[0] for columns in rows))
                        lengths = run_lengths(rows[0])
                        self.assertTrue(all(length == 2 for length in lengths[:-1]))
                        self.assertIn(lengths[-1], (1, 2))  # 最右端的一点可被窗口边界裁去 1px。
                        starts = [x for i, x in enumerate(rows[0]) if i == 0 or x != rows[0][i-1]+1]
                        self.assertTrue(all(b-a == 6 for a, b in zip(starts, starts[1:])))

    def test_font_raster_has_no_antialias_pixels_while_text_scales_with_dpi(self):
        widths = []
        for dpr in (1., 1.25, 1.5, 2.):
            with self.subTest(dpr=dpr):
                image = QImage(round(300*dpr), round(40*dpr), QImage.Format.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.fill(PAPER)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                painter.setFont(settings_font())
                painter.setPen(INK)
                painter.drawText(QRect(4, 4, 280, 30), 0, '桌宠设置 Settings 150%')
                painter.end()
                colors, ink_columns = set(), []
                for x in range(image.width()):
                    for y in range(image.height()):
                        color = image.pixelColor(x, y).rgba()
                        colors.add(color)
                        if color == INK.rgba():
                            ink_columns.append(x)
                self.assertEqual(colors, {INK.rgba(), PAPER.rgba()})
                widths.append(max(ink_columns)-min(ink_columns))
        self.assertTrue(all(b > a for a, b in zip(widths, widths[1:])))

    def test_bundled_font_survives_language_changes_and_different_working_directory(self):
        settings_font_family.cache_clear()
        with tempfile.TemporaryDirectory() as temporary, chdir(temporary):
            config = replace(AppConfig(), ui=UiConfig('zh'))
            isolate_characters(self, Path(temporary))
            dialog = OracleSettingsDialog(config, SettingsStore(Path(temporary)/'settings.json'))
            try:
                dialog.show()
                dialog.controls['audio.volume'].setValue(43)
                for language in ('zh', 'en', 'zh'):
                    language_manager().set_language(language)
                    for _ in range(3):
                        self.app.processEvents()
                    for widget in (dialog, dialog.directory_hint, dialog.status,
                                   dialog.save_button, dialog.controls['audio.volume']):
                        font = widget.font()
                        self.assertFalse(font.styleStrategy() & QFont.StyleStrategy.PreferAntialias)
                        self.assertTrue(font.styleStrategy() & QFont.StyleStrategy.NoAntialias)
                        layout = QTextLayout('桌宠设置 Settings 150%', font)
                        layout.beginLayout()
                        layout.createLine()
                        layout.endLayout()
                        families = {run.rawFont().familyName() for run in layout.glyphRuns()}
                        self.assertTrue(families)
                        self.assertLessEqual(families, {'WenQuanYi Bitmap Song 14px', '文泉驿点阵宋体14px'})
                    self.assertEqual(dialog.font().pixelSize(), 14)
                    self.assertEqual(dialog.directory_hint.font().pixelSize(), 12)
                    self.assertEqual(dialog.controls['audio.volume'].value(), 43)
            finally:
                dialog.shutdown()
                dialog.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
