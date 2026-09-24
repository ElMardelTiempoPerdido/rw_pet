"""独立进程验证 Qt DPI 下固定倍率的真实像素尺寸，并保存调试窗口预览。"""
import os
from pathlib import Path
import sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = sys.argv[1] if len(sys.argv) > 1 else '1'

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

import json
from PIL import Image, ImageChops
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow


class PixelMarker:
    def draw(self, painter, scene, *args):
        center = scene.appearance.upper
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#f400fa'))
        painter.drawRect(QRectF(center.x-6, center.y-4, 12, 8))
        painter.restore()


def main():
    app = QApplication([])
    app.setStyle('Fusion')
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    window = OracleDebugWindow(AppConfig.load(ROOT/'config.toml'), ROOT/'config.toml')
    window.timer.stop()
    window.pause_button.setChecked(True)
    window.zoom_box.setChecked(False)
    canvas = window.canvas
    renderer = canvas.renderer
    canvas.renderer = PixelMarker()
    window.show()
    rows = []
    try:
        for scale in (1., 2., 4.):
            window.scale_input.setCurrentIndex(window.scale_input.findData(scale))
            window.focus_button.click()
            for size in ((1220, 830), (1820, 1030)):
                window.resize(*size)
                app.processEvents()
                image = canvas.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                pixels = Image.frombytes('RGBA', (image.width(), image.height()), bytes(image.constBits())).convert('RGB')
                difference = ImageChops.difference(pixels, Image.new('RGB', pixels.size, '#f400fa'))
                mask = difference.convert('L').point(lambda v: 255 if v == 0 else 0)
                box = mask.getbbox()
                measured = (box[2]-box[0], box[3]-box[1])
                assert measured == (12*scale, 8*scale), (scale, measured)
                rows.append(dict(window=size, scale=scale, marker_pixels=measured))
        canvas.renderer = renderer
        window.scale_input.setCurrentIndex(window.scale_input.findData(1.))
        canvas.set_view_scale(1.)
        window.zoom_box.setChecked(True)
        window.resize(1220, 830)
        app.processEvents()
        label = f'{canvas.devicePixelRatioF()*100:g}'
        window.grab().save(str(ROOT/f'artifacts/oracle-zoom-dpi{label}.png'))
        result = dict(dpr=canvas.devicePixelRatioF(), measurements=rows)
        (ROOT/f'artifacts/oracle-zoom-dpi{label}.json').write_text(
            json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result), flush=True)
    finally:
        window.close()


if __name__ == '__main__':
    main()
