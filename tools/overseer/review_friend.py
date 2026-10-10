"""朋友？外观四边、注视透视与槽位设置预览，不写入用户配置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.overseer.config import OverseerSlot
from rw_creature_pet.overseer.group import OverseerGroup
from rw_creature_pet.overseer.model import Anchor, Edge
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.geometry import Bounds, Vec2


OUT = ROOT/'artifacts/overseer'


def paint(renderer, model, background):
    image = QImage(100, 100, QImage.Format.Format_RGBA8888)
    image.fill(QColor(background))
    p = QPainter(image)
    try:
        center = model.root+model.normal*30
        p.translate(50-center.x, 50-center.y)
        p.setPen(QColor('#9a9a9a'))
        p.drawRect(0, 0, 640, 480)
        renderer.draw(p, model)
    finally:
        p.end()
    return Image.frombytes('RGBA', (100, 100), bytes(image.constBits()))


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    font = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font)[0], 10))
    OUT.mkdir(parents=True, exist_ok=True)
    config = AppConfig.load(ROOT/'config.toml')
    cfg = replace(config.overseer, observation_probability=0, slots=(OverseerSlot(appearance='friend'),))
    sheet = Image.new('RGB', (1200, 690), '#dddddd')
    for row, target in enumerate((Vec2(0, 60), Vec2(220, 350))):
        for column, edge in enumerate(Edge):
            group = OverseerGroup(cfg, Bounds(0, 0, 640, 480), seed=3)
            model = group.entries[1].model
            model.show(anchor=Anchor(edge, .5))
            for _ in range(120):
                model.step(model.root+model.local_vector(target))
            native = paint(OverseerRenderer(), model, '#dddddd')
            x, y = column*300, row*345
            sheet.paste(native.resize((300, 300), Image.Resampling.NEAREST), (x, y+25))
            sheet.paste(native, (x+200, y+235))
            ImageDraw.Draw(sheet).text((x+5, y+5), f'{edge.value} / gaze {row+1} / 3x + 1x', fill='#333333')
    sheet.save(OUT/'friend-four-edges.png')

    group = OverseerGroup(cfg, Bounds(0, 0, 640, 480), seed=3)
    model = group.entries[1].model
    model.show(anchor=Anchor(Edge.TOP, .5))
    renderer, frames = OverseerRenderer(), []
    for tick in range(240):
        if tick == 155:
            model.request_withdraw()
        if tick == 190:
            model.request_emerge()
        model.step(model.root+model.local_vector(Vec2(100 if tick < 95 else -180, 220)))
        if tick % 2 == 0:
            frames.append(paint(renderer, model, '#dddddd').resize((400, 400), Image.Resampling.NEAREST))
    frames[0].save(OUT/'friend-motion.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)

    slots = (OverseerSlot(1, appearance='friend'), OverseerSlot(2, '#ff557f'),
             OverseerSlot(3, '#4baa97', 'friend'), OverseerSlot(4))
    config = replace(config, overseer=replace(config.overseer, enabled=True, slots=slots))
    with TemporaryDirectory() as temp:
        dialog = OracleSettingsDialog(config, SettingsStore(Path(temp)/'settings.json'))
        try:
            dialog.show()
            dialog.tabs.setCurrentIndex(next(i for i in range(dialog.tabs.count())
                                             if dialog.tabs.tabText(i) in ('监视者', 'Overseer')))
            for lang in ('zh', 'en'):
                language_manager().set_language(lang)
                app.processEvents()
                dialog.tabs.currentWidget().verticalScrollBar().setValue(0)
                app.processEvents()
                dialog.grab().save(str(OUT/f'friend-settings-{lang}.png'))
            language_manager().set_language('zh')
            dialog.fit_workarea(QRect(0, 0, 800, 480))
            app.processEvents()
            dialog.grab().save(str(OUT/'friend-settings-small.png'))
        finally:
            dialog.shutdown()
    print('Previews:', OUT)


if __name__ == '__main__':
    main()
