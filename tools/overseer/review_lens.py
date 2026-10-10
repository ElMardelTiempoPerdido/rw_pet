"""本机图集的观察镜片四边预览/动画；离屏运行，不改变用户设置。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from math import sin
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
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Bounds, Vec2
from rw_creature_pet.overseer.model import Anchor, Edge, Overseer
from rw_creature_pet.overseer.graphics.render import OverseerRenderer
from rw_creature_pet.oracle.ui.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore


def paint(renderer, model):
    image = QImage(140, 140, QImage.Format.Format_RGBA8888)
    image.fill(QColor('#182129'))
    p = QPainter(image)
    try:
        center = model.root+model.normal*45
        p.translate(70-center.x, 70-center.y)
        p.setPen(QColor('#456072'))
        p.drawRect(0, 0, 640, 480)
        renderer.draw(p, model)
    finally:
        p.end()
    return Image.frombytes('RGBA', (140, 140), bytes(image.constBits()))


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    font = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font)[0], 10))
    config = AppConfig.load(ROOT/'config.toml')
    watcher = replace(config.overseer, observation_probability=1, observation_interval=.1)
    renderer = OverseerRenderer(Atlas(extract_atlas(config.game_dir)))
    out = ROOT/'artifacts/overseer'
    out.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGB', (1260, 1220), '#182129')
    labels = ImageDraw.Draw(sheet)
    for row, edge in enumerate(Edge):
        for column, target in enumerate((Vec2(0, 40), Vec2(350, 80), Vec2(0, 450))):
            model = Overseer(Bounds(0, 0, 640, 480), watcher)
            model.show(anchor=Anchor(edge, .5))
            for _ in range(125):
                model.step(model.root+model.local_vector(target))
            native = paint(renderer, model)
            x, y = column*420, row*305
            sheet.paste(native.resize((280, 280), Image.Resampling.NEAREST), (x, y+25))
            sheet.paste(native, (x+280, y+95))
            labels.text((x+5, y+5), f'{edge.value} / view {column+1} / 2x + 1x', fill='white')
    sheet.save(out/'lens-four-edges.png')
    models = [Overseer(Bounds(0, 0, 640, 480), watcher) for _ in Edge]
    for model, edge in zip(models, Edge):
        model.show(anchor=Anchor(edge, .5))
    frames = []
    for tick in range(400):
        frame = Image.new('RGB', (1120, 310), '#182129') if tick % 2 == 0 else None
        for i, model in enumerate(models):
            target = model.root+model.local_vector(Vec2(sin(tick/90)*350, 200))
            model.step(target, threat=model.root if 210 <= tick < 250 else None)
            if frame is not None:
                frame.paste(paint(renderer, model).resize((280, 280), Image.Resampling.NEAREST), (i*280, 30))
                ImageDraw.Draw(frame).text((i*280+5, 5), f'{model.anchor.edge.value} / lens {model.lens.up:.0%}', fill='white')
        if frame is not None:
            frames.append(frame)
    frames[0].save(out/'lens-observation.gif', save_all=True, append_images=frames[1:], duration=50, loop=0)
    with TemporaryDirectory() as temp:
        dialog = OracleSettingsDialog(config, SettingsStore(Path(temp)/'settings.json'))
        try:
            dialog.show()
            dialog.tabs.setCurrentIndex(next(i for i in range(dialog.tabs.count())
                                             if dialog.tabs.tabText(i) == '监视者'))
            dialog.controls['overseer.enabled'].setChecked(True)
            for language in ('zh', 'en'):
                language_manager().set_language(language)
                app.processEvents()
                area = dialog.tabs.currentWidget()
                area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
                app.processEvents()
                dialog.grab().save(str(out/f'lens-settings-{language}.png'))
            language_manager().set_language('zh')
            dialog.fit_workarea(QRect(0, 0, 800, 480))
            app.processEvents()
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
            app.processEvents()
            dialog.grab().save(str(out/'lens-settings-small.png'))
        finally:
            dialog.shutdown()
    print('Lens previews saved:', out)


if __name__ == '__main__':
    main()
