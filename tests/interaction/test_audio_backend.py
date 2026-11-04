"""不更改系统设备，覆盖媒体加载取消和输出设备热切换"""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PySide6.QtMultimedia import QAudioFormat, QMediaPlayer

from rw_creature_pet.interaction.audio_backend import QtMediaBackend


def device(name='stereo', rate=44100, channels=2):
    result = Mock()
    result.isNull.return_value = not name
    result.id.return_value = name.encode()
    result.description.return_value = name
    fmt = QAudioFormat()
    fmt.setSampleRate(rate)
    fmt.setChannelCount(channels)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
    result.preferredFormat.return_value = fmt
    return result


class MediaBackendTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('rw_creature_pet.interaction.audio_backend.voice_event'))
        self.devices = Mock()
        self.default = device()
        self.devices.defaultAudioOutput.side_effect = lambda: self.default
        constructor = self.enterContext(patch('PySide6.QtMultimedia.QMediaDevices', return_value=self.devices))
        constructor.defaultAudioOutput.side_effect = lambda: self.default
        self.player = Mock()
        self.player.Error, self.player.MediaStatus = QMediaPlayer.Error, QMediaPlayer.MediaStatus
        self.player.error.return_value = QMediaPlayer.Error.NoError
        self.player.errorString.return_value = ''
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.NoMedia
        self.player.isPlaying.return_value = False
        self.factory = self.enterContext(patch('PySide6.QtMultimedia.QMediaPlayer', return_value=self.player))
        self.outputs = []

        def make_output(target, parent):
            output = Mock()
            output.device.return_value = target
            output.volume.return_value, output.isMuted.return_value = .4, True
            self.outputs.append(output)
            return output

        self.enterContext(patch('PySide6.QtMultimedia.QAudioOutput', side_effect=make_output))
        self.backend = QtMediaBackend(None)
        self.addCleanup(self.backend.close)
        self.path = Path('clip.wav').resolve()

    def start(self):
        self.backend.play(self.path)
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.BufferedMedia
        self.player.isPlaying.return_value = True

    def test_loading_is_not_counted_as_playback_and_end_is_terminal(self):
        self.backend.play(self.path)
        self.player.setPlaybackRate.assert_called_once_with(1.)
        self.player.setLoops.assert_called_once_with(1)
        self.player.isPlaying.return_value = True
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.LoadingMedia
        self.assertEqual(self.backend.state, 'loading')
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.BufferedMedia
        self.assertEqual(self.backend.state, 'playing')
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.EndOfMedia
        self.assertEqual(self.backend.state, 'idle')

    def test_cancel_loading_clears_source_and_no_late_event_replays(self):
        self.backend.play(self.path)
        self.backend.stop()
        self.assertTrue(self.player.setSource.call_args.args[0].isEmpty())
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.LoadedMedia
        self.backend._outputs_changed()
        self.assertEqual(self.backend.state, 'idle')
        self.assertEqual(self.player.play.call_count, 1)
        self.backend.play(self.path)  # 同一片段的新请求仍然能开始
        self.assertEqual(self.player.play.call_count, 2)

    def test_default_switch_keeps_progress_volume_and_mute_without_restarting(self):
        self.start()
        before = self.player.setSource.call_count
        old = self.backend.output
        self.default = device('hands-free', 16000, 1)
        self.backend._outputs_changed()
        self.assertEqual(self.backend.state, 'playing')
        self.assertEqual(self.player.setSource.call_count, before)
        self.assertEqual(self.player.play.call_count, 1)
        self.player.setPosition.assert_not_called()
        self.backend.output.setVolume.assert_called_once_with(.4)
        self.backend.output.setMuted.assert_called_once_with(True)
        old.deleteLater.assert_called_once()
        self.player.setAudioOutput.assert_called_with(self.backend.output)

    def test_same_device_format_change_recreates_output(self):
        self.default = device('stereo', 48000, 2)
        self.backend._outputs_changed()
        self.assertEqual(len(self.outputs), 2)
        self.player.play.assert_not_called()

    def test_unrelated_device_notifications_do_not_recreate_output(self):
        for _ in range(5):
            self.backend._outputs_changed()
        self.assertEqual(len(self.outputs), 1)
        self.player.play.assert_not_called()

    def test_disconnect_during_load_or_play_cancels_until_a_new_request(self):
        for loading in (True, False):
            with self.subTest(loading=loading):
                self.default = device()
                self.start()
                if loading:
                    self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.LoadingMedia
                plays = self.player.play.call_count
                self.default = device('')
                self.backend._outputs_changed()
                self.assertEqual(self.backend.state, 'error')
                self.assertFalse(self.backend.requested)
                self.assertTrue(self.player.setSource.call_args.args[0].isEmpty())
                self.default = device()
                self.backend._outputs_changed()
                self.assertEqual(self.player.play.call_count, plays)
                self.assertEqual(self.backend.state, 'error')
                self.backend.play(self.path)
                self.assertEqual(self.player.play.call_count, plays+1)
                self.assertNotEqual(self.backend.state, 'error')

    def test_play_refreshes_default_before_queued_device_notification(self):
        self.default = device('new-output', 48000)
        self.backend.play(self.path)
        self.assertIs(self.backend.output.device(), self.default)
        self.default = device('')
        with self.assertRaisesRegex(RuntimeError, '没有可用'):
            self.backend.play(self.path)
        self.assertFalse(self.backend.requested)

    def test_errors_are_not_misclassified_as_loading(self):
        self.start()
        self.player.error.return_value = QMediaPlayer.Error.FormatError
        self.player.errorString.return_value = 'decoder failed'
        self.assertEqual(self.backend.state, 'error')
        self.assertEqual(self.backend.diagnostics()['qt_error'], 'decoder failed')
        self.player.error.return_value = QMediaPlayer.Error.NoError
        self.player.mediaStatus.return_value = QMediaPlayer.MediaStatus.InvalidMedia
        self.assertEqual(self.backend.state, 'error')

    def test_output_switch_exception_is_reported_and_cancels_playback(self):
        self.start()
        self.default = device('new-output')
        self.player.setAudioOutput.side_effect = RuntimeError('device disappeared')
        self.backend._outputs_changed()
        self.assertEqual(self.backend.state, 'error')
        self.assertFalse(self.backend.requested)
        self.assertTrue(self.player.setSource.call_args.args[0].isEmpty())
        self.assertEqual(self.backend.diagnostics()['qt_error'], 'device disappeared')

    def test_no_output_is_nonfatal_and_does_not_allocate_a_player(self):
        self.default = device('')
        calls = self.factory.call_count
        with self.assertRaisesRegex(RuntimeError, '没有可用'):
            QtMediaBackend(None)
        self.assertEqual(self.factory.call_count, calls)

    def test_disposal_revokes_device_callback_and_releases_children(self):
        self.backend.play(self.path)
        self.backend.close()
        self.backend._outputs_changed()  # 已排入事件队列的通知也不能复活播放
        self.backend.close()
        self.devices.audioOutputsChanged.disconnect.assert_called_once_with(self.backend._outputs_changed)
        self.player.deleteLater.assert_called_once()
        self.assertEqual(self.player.play.call_count, 1)
        self.assertEqual(self.backend.state, 'idle')

    def test_disposal_still_deletes_player_if_stop_fails(self):
        self.player.stop.side_effect = RuntimeError('lost device')
        with self.assertRaises(RuntimeError):
            self.backend.close()
        self.backend._outputs_changed()
        self.player.deleteLater.assert_called_once()
        self.player.play.assert_not_called()


if __name__ == '__main__':
    unittest.main()
