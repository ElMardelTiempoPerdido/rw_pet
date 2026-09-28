"""离屏检查设置窗口，并用真实本机资源完成一次临时用户配置保存。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QRect
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.settings import OracleSettingsDialog
from rw_creature_pet.settings_store import SettingsStore, absolute_paths


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    config = absolute_paths(AppConfig.load(ROOT/'config.toml'), ROOT/'config.toml')
    out = ROOT/'artifacts'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        store = SettingsStore(Path(temp)/'settings.json')
        dialog = OracleSettingsDialog(config, store, first_run=True)
        try:
            dialog.show()
            app.processEvents()
            for i, name in enumerate(('general', 'pearls', 'halo', 'activity')):
                dialog.tabs.setCurrentIndex(i)
                app.processEvents()
                dialog.grab().save(str(out/f'oracle-settings-{name}.png'))
            dialog.tabs.setCurrentIndex(0)
            dialog.controls['oracle.glow_enabled'].setChecked(True)
            app.processEvents()
            bar = dialog.tabs.currentWidget().verticalScrollBar()
            bar.setValue(bar.maximum())
            app.processEvents()
            dialog.grab().save(str(out/'oracle-settings-glow.png'))
            dialog.controls['oracle.glow_enabled'].setChecked(config.oracle.glow_enabled)
            dialog.tabs.setCurrentIndex(3)
            for edge, check in dialog.edge_checks.items():
                check.setChecked(edge in ('top', 'bottom'))
            dialog.save()
            assert '连续' in dialog.status.text()
            assert not store.path.exists()
            app.processEvents()
            dialog.grab().save(str(out/'oracle-settings-edges-invalid.png'))
            for edge, check in dialog.edge_checks.items():
                check.setChecked(edge in config.oracle.allowed_edges)
            dialog.fit_workarea(QRect(-800, 0, 800, 480))
            app.processEvents()
            dialog.grab().save(str(out/'oracle-settings-activity-small.png'))
            dialog.tabs.setCurrentIndex(1)
            app.processEvents()
            dialog.grab().save(str(out/'oracle-settings-small.png'))
            dialog.tabs.setCurrentIndex(0)
            dialog.game_dir.setText(str(config.game_dir/'invalid'))
            dialog.save()
            app.processEvents()
            dialog.grab().save(str(out/'oracle-settings-invalid.png'))
            dialog.game_dir.setText(str(config.game_dir))
            dialog.save()
            started = monotonic()
            while dialog.worker is not None and monotonic()-started < 120:
                QTest.qWait(20)
            assert dialog.result() == QDialog.DialogCode.Accepted, dialog.status.text()
            assert store.load() == config
            print('Real assets prepared and temporary user settings round-tripped in', round(monotonic()-started, 2), 'seconds')
            print('Asset status:', dialog.prepared_assets.message or 'atlas and pearl glyphs ready')
            print('Voice clips:', len(dialog.prepared_assets.voice_paths))
        finally:
            dialog.shutdown()


if __name__ == '__main__':
    main()
