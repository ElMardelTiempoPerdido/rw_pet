"""单文件包内的离屏自检；输出、设置与资源缓存均隔离到指定目录。"""
import json
import os
from pathlib import Path
import sys
from time import monotonic
import traceback


def main(argv):
    if len(argv) != 1:
        return 2
    output = Path(argv[0]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['LOCALAPPDATA'] = str(output/'profile')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False))}
    started = monotonic()
    try:
        from dataclasses import replace
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtMultimedia import QSoundEffect
        from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon
        from rw_creature_pet.settings_store import SettingsStore, default_template_path
        from rw_creature_pet.oracle.settings import OracleSettingsDialog
        from rw_creature_pet.oracle.numeric import compiled_rope_solver
        from rw_creature_pet.oracle.desktop import OracleDesktopWindow

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        app.setStyle('Fusion')
        store = SettingsStore()
        config, first_run, message = store.startup()
        report.update(template=str(default_template_path()), first_run=first_run)
        assert default_template_path().is_file(), '包内默认配置缺失'
        dialog = OracleSettingsDialog(config, store, first_run=first_run, message=message)
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(str(output/'settings.png'))
        dialog.save()
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if dialog.worker is None else None)
        timer.start(30)
        QTimer.singleShot(180000, loop.quit)
        loop.exec()
        timer.stop()
        assert dialog.result() == QDialog.DialogCode.Accepted, dialog.status.text()
        assets = dialog.prepared_assets
        assert assets.renderer.glyphs is not None, assets.message
        assert len(assets.voice_paths) == 10 and not assets.voice_error, assets.voice_error
        config = dialog.saved_config
        assert store.startup()[0] == config and store.startup()[1] is False
        report.update(atlas=True, glyphs=True, voice_clips=len(assets.voice_paths), settings_roundtrip=True)
        solver = compiled_rope_solver()  # 必须真实编译成功，不能悄悄回退到 Python。
        assert solver.signatures
        report['numba'] = True

        sound = QSoundEffect()
        sound.setSource(QUrl.fromLocalFile(str(next(iter(assets.voice_paths.values())))))
        sound_loop = QEventLoop()
        sound.statusChanged.connect(lambda: sound_loop.quit() if sound.status() in
                                    (QSoundEffect.Status.Ready, QSoundEffect.Status.Error) else None)
        QTimer.singleShot(10000, sound_loop.quit)
        if sound.status() == QSoundEffect.Status.Loading:
            sound_loop.exec()
        assert sound.status() == QSoundEffect.Status.Ready, f'Qt 音频解码失败：{sound.status()}'
        report['qt_audio_decoding'] = True
        sound.setVolume(0.)  # 静音验证实际播放通路，避免移除视频后端后只解码成功。
        sound.play()
        playback_loop = QEventLoop()
        QTimer.singleShot(250, playback_loop.quit)
        playback_loop.exec()
        assert sound.isPlaying() and sound.status() == QSoundEffect.Status.Ready
        sound.stop()
        report['qt_audio_playback'] = True

        # 离屏平台没有系统托盘，仅替代可用性检测，仍执行真实桌面窗口初始化。
        QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
        window = OracleDesktopWindow(config, config.desktop.scale, store.path,
                                     config_store=store, assets=assets)
        window.timer.stop()
        assert not window.tray.icon().isNull(), '托盘图标未打包'
        scene = window.motion.scene
        scene.config = replace(scene.config, glow_enabled=True)
        scene.start_lap()
        for _ in range(240):
            scene.step()
        image = QImage(round(scene.config.world_width), round(scene.config.world_height),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            window.renderer.draw(painter, scene, .5)
        finally:
            painter.end()
        assert image.save(str(output/'pet.png'))
        window.set_toolbar_visible(True)
        app.processEvents()
        assert window.action_toolbar is not None
        report.update(desktop=True, tray_icon=True, toolbar=True, glow=True, simulation_frames=240)
        window.open_debug()
        app.processEvents()
        assert window.debug_window is not None
        assert window.debug_window.grab().save(str(output/'debug.png'))
        report['debug_window'] = True
        window.cleanup()
        dialog.shutdown()
        report['ok'] = True
    except BaseException:
        report['error'] = traceback.format_exc()
    report['seconds'] = round(monotonic()-started, 2)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 0 if report['ok'] else 1
