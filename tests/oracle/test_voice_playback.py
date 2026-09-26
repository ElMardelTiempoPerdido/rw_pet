"""调试/桌面窗口确实消费拖动请求，且生命周期不会留下异步播放。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import tempfile
from time import perf_counter
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.oracle.config import DragReactionConfig, OracleConfig
from rw_creature_pet.oracle.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.voice import BELL_VOICE_CLIPS
from tests.interaction.test_audio import FakeSound


class VoiceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for clip in BELL_VOICE_CLIPS:
            (Path(self.directory.name)/clip.filename).touch()
        self.config = AppConfig(interaction=InteractionConfig(True), oracle=OracleConfig(
            halo_enabled=False, pearl_fixed_count=0, voice_directory=self.directory.name,
            drag_reactions=DragReactionConfig(voice_probability=1.)))

    def attach_sound(self, window):
        window.timer.stop()
        sound = FakeSound()
        window.voice_player._factory = lambda _: sound
        return sound

    def grab(self, scene):
        self.assertTrue(scene.drag.press(scene.head.position, lambda _: True))

    def wait_for_voice(self, window):
        scene = window.scene if isinstance(window, OracleDebugWindow) else window.motion.scene
        advance = window.on_timer if isinstance(window, OracleDebugWindow) else window.advance
        # 驱动真实窗口时钟，无需让测试等待三秒，也不跳过新加入的延迟逻辑。
        for _ in range(122):
            with patch(window.__module__+'.perf_counter', return_value=window.last_time+.025001):
                advance()
            if window.voice_player.current is not None:
                window.last_time = perf_counter()
                return
        self.fail('成功抽中语音后，三秒等待内应生成并消费播放请求')

    def test_tray_voice_status_updates_without_dynamic_qaction_warning(self):
        messages = []
        previous = qInstallMessageHandler(lambda kind, context, text: messages.append(text))
        try:
            with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
                w = OracleDesktopWindow(self.config, renderer=OracleRenderer())
            try:
                w.timer.stop()
                for enabled in (False, True, False):
                    w.voice_player.configure(enabled=enabled)
                    self.assertEqual(w.voice_status.text(), w.voice_player.status)
                self.assertGreaterEqual(w.metaObject().indexOfSlot('set_voice_status(QString)'), 0)
            finally:
                w.close()
                self.app.processEvents()
        finally:
            qInstallMessageHandler(previous)
        self.assertFalse([text for text in messages if 'addMetaMethod' in text], messages)

    def test_debug_release_pause_reset_mute_close(self):
        w = OracleDebugWindow(self.config, load_atlas=False)
        self.addCleanup(w.close)
        sound = self.attach_sound(w)
        self.grab(w.scene)
        self.assertIsNone(w.scene.drag_reactions.voice.pending)
        self.wait_for_voice(w)
        self.assertEqual(len(sound.paths), 1)
        sound.state = 'playing'
        w.on_timer()
        w.scene.drag.release()
        w.on_timer()
        self.assertIsNotNone(w.voice_player.current)
        w.voice_volume.setValue(30)
        self.assertAlmostEqual(sound.volume, .3)
        w.set_paused(True)
        self.assertIsNone(w.voice_player.current)
        w.set_paused(False)
        self.grab(w.scene)
        self.wait_for_voice(w)
        w.reset_scene()
        self.assertEqual(sound.state, 'idle')
        w.on_timer()
        self.assertEqual(len(sound.paths), 2)
        self.grab(w.scene)
        self.wait_for_voice(w)
        w.voice_box.setChecked(False)
        self.assertEqual(sound.state, 'idle')
        w.voice_box.setChecked(True)
        w.on_timer()
        self.assertEqual(len(sound.paths), 3)
        w.close()
        self.assertIsNone(w.voice_player.current)

    def test_desktop_rebuild_disable_pause_and_debug_handoff(self):
        with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
            w = OracleDesktopWindow(self.config, renderer=OracleRenderer())
        self.addCleanup(w.close)
        sound = self.attach_sound(w)
        w.sync_drag_input()
        self.grab(w.motion.scene)
        self.wait_for_voice(w)
        self.assertEqual(len(sound.paths), 1)
        w.set_paused(True)
        self.assertEqual(sound.state, 'idle')
        w.set_paused(False)
        self.grab(w.motion.scene)
        self.wait_for_voice(w)
        w.change_scale(2.)
        self.assertIsNone(w.voice_player.current)
        w.sync_drag_input()
        self.grab(w.motion.scene)
        self.wait_for_voice(w)
        w.drag_action.setChecked(False)
        self.assertIsNone(w.voice_player.current)
        w.drag_action.setChecked(True)
        self.grab(w.motion.scene)
        self.wait_for_voice(w)
        w.voice_player.configure(volume=.25)
        w.open_debug()
        self.assertIsNone(w.voice_player.current)
        debug = w.debug_window
        debug_sound = self.attach_sound(debug)
        self.assertEqual(debug.voice_volume.value(), 25)
        self.grab(debug.scene)
        self.wait_for_voice(debug)
        self.assertEqual(len(debug_sound.paths), 1)
        debug.close()
        self.assertEqual(debug_sound.state, 'idle')
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertIsNone(w.debug_window)
        self.assertFalse(w.clock.paused)
        w.advance()
        self.assertIsNone(w.voice_player.current)
        w.close()


if __name__ == '__main__':
    unittest.main()
