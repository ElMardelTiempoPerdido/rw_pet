"""离屏检查四槽设置和四只监视者的局部显示，不写用户设置"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.i18n import language_manager
from rw_creature_pet.oracle.settings import OracleSettingsDialog
from rw_creature_pet.overseer.config import OverseerSlot
from rw_creature_pet.overseer.events import SpawnContext
from rw_creature_pet.overseer.group import OverseerGroup
from rw_creature_pet.overseer.render import OverseerRenderer
from rw_creature_pet.settings_store import SettingsStore
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Bounds, Vec2


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    config = AppConfig.load(ROOT/'config.toml')
    slots = tuple(OverseerSlot(i, color) for i, color in enumerate(
        ('#ff557f', '#72e6c4', '#f3cf74', '#b897ef'), 1))
    config = replace(config, overseer=replace(config.overseer, enabled=True,
                     appearance_mode='resident', slots=slots))
    output = ROOT/'artifacts/overseer'
    output.mkdir(parents=True, exist_ok=True)
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
                dialog.grab().save(str(output/f'multiple-settings-{lang}.png'))
            language_manager().set_language('zh')
            dialog.fit_workarea(QRect(0, 0, 800, 480))
            app.processEvents()
            dialog.grab().save(str(output/'multiple-settings-small.png'))
        finally:
            dialog.shutdown()
    atlas = Atlas(extract_atlas(config.game_dir))
    group = OverseerGroup(config.overseer, Bounds(0, 0, 960, 540), seed=122)
    context = SpawnContext(group.bounds, mouse=Vec2(480, 270))
    for _ in range(100):
        group.step(context.mouse, context_factory=lambda: context)
    image = QImage(960, 540, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#19212a'))
    painter = QPainter(image)
    try:
        for entry in group.entries.values():
            OverseerRenderer(atlas).draw(painter, entry.model)
    finally:
        painter.end()
    image.save(str(output/'multiple-resident.png'))
    print(output)


if __name__ == '__main__':
    main()
