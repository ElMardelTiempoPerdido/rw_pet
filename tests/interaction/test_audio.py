"""不打开真实设备的异步播放、丢弃积压和配置边界回归。"""
from pathlib import Path
import tempfile
import unittest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.audio import VoicePlayer
from rw_creature_pet.interaction.config import AudioConfig
from rw_creature_pet.interaction.voice import VoiceCue, VoiceCueChannel
from rw_creature_pet.oracle.config import OracleConfig
from rw_creature_pet.oracle.voice import bell_voice_paths


class FakeSound:
    def __init__(self, parent=None):
        self.state = 'idle'
        self.paths = []
        self.stops = 0

    def play(self, path):
        self.paths.append(path)
        self.state = 'loading'

    def stop(self):
        self.state = 'idle'
        self.stops += 1

    def set_volume(self, volume):
        self.volume = volume


class VoicePlayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)/'bell.wav'
        self.path.write_bytes(b'test backend does not decode')
        self.sound = FakeSound()
        self.now = 0.
        self.player = VoicePlayer({'bell': self.path}, backend_factory=lambda _: self.sound,
                                  time_source=lambda: self.now)
        self.channel = VoiceCueChannel()
        self.cue = VoiceCue('bell', 2., 'drag')
        self.player.sync(self.channel)
        self.addCleanup(self.player.stop)

    def request(self):
        self.channel.cancel()
        self.channel.request(self.cue)
        self.player.sync(self.channel)

    def start(self):
        self.request()
        self.sound.state = 'playing'
        self.player.sync(self.channel)

    def test_idle_and_muted_never_create_device_and_unmute_drops_request(self):
        self.player.configure(enabled=False)
        self.request()
        self.assertIsNone(self.player._backend)
        self.channel.cancel()
        self.channel.request(self.cue)  # 开启声音前同一帧内产生的请求也丢弃。
        self.player.configure(enabled=True)
        self.player.sync(self.channel)
        self.assertIsNone(self.player._backend)
        self.request()
        self.assertEqual(len(self.sound.paths), 1)

    def test_normal_release_finishes_and_regrab_does_not_overlap_or_queue(self):
        self.start()
        self.channel.cancel()  # 正常松手只清除行为侧预占。
        self.player.sync(self.channel)
        self.assertIsNotNone(self.player.current)
        self.request()  # 快速再抓住，当前台词不被打断，新请求不排队。
        self.assertEqual(len(self.sound.paths), 1)
        self.sound.state = 'idle'
        self.player.sync(self.channel)
        self.assertIsNone(self.player.current)
        self.assertEqual(len(self.sound.paths), 1)
        self.request()
        self.assertEqual(len(self.sound.paths), 2)

    def test_actual_device_time_controls_overlap_not_simulation_ticks(self):
        self.start()
        self.channel.step(100.)
        self.channel.request(self.cue)
        self.player.sync(self.channel)
        self.assertEqual(len(self.sound.paths), 1)
        self.assertEqual(self.player.play_count, 1)
        self.assertIn('正在播放', self.player.status)

    def test_pause_and_channel_replacement_cancel_inflight_load(self):
        self.request()
        self.player.sync(self.channel, paused=True)
        self.assertEqual(self.sound.state, 'idle')
        self.assertIsNone(self.player.current)
        self.player.sync(self.channel)
        self.assertEqual(len(self.sound.paths), 1)
        self.request()
        fresh = VoiceCueChannel()
        self.player.sync(fresh)
        self.assertEqual(self.sound.state, 'idle')
        self.assertIsNone(self.channel.pending)
        self.assertEqual(len(self.sound.paths), 2)

    def test_volume_changes_live_and_zero_stops_without_replay(self):
        self.start()
        self.player.configure(volume=.3)
        self.assertAlmostEqual(self.sound.volume, .3)
        self.assertIsNotNone(self.player.current)
        self.player.configure(volume=0.)
        self.assertIsNone(self.player.current)
        self.request()
        self.player.configure(volume=.7)
        self.player.sync(self.channel)
        self.assertEqual(len(self.sound.paths), 1)

    def test_errors_timeout_missing_and_retry_do_not_leave_busy_channel(self):
        self.path.unlink()
        self.request()
        self.assertIn('缺少音频', self.player.status)
        self.assertIsNone(self.player._backend)
        self.path.touch()
        self.request()
        self.sound.state = 'error'
        self.player.sync(self.channel)
        self.assertIn('失败', self.player.status)
        self.assertIsNone(self.player.current)
        self.request()
        self.now = 6.
        self.player.sync(self.channel)
        self.assertIn('超时', self.player.status)
        self.start()
        self.assertFalse(self.player.error)
        self.now = 20.  # 拔出设备但底层仍报告 playing 的异常也有期限。
        self.player.sync(self.channel)
        self.assertIsNone(self.player.current)

    def test_no_output_device_is_nonfatal(self):
        def unavailable(_):
            raise RuntimeError('没有可用的音频输出设备')
        self.player._factory = unavailable
        self.request()
        self.assertIn('没有可用', self.player.status)
        self.assertIsNone(self.player.current)
        self.assertIsNone(self.channel.pending)


class AudioConfigTests(unittest.TestCase):
    def test_validation_and_old_config(self):
        for value in (-1, 1.01, float('nan'), True, '0.7'):
            with self.assertRaises(ValueError):
                AudioConfig(volume=value)
        with self.assertRaises(ValueError):
            AudioConfig(enabled=1)
        with self.assertRaises(ValueError):
            OracleConfig(voice_directory='')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.toml'
            path.write_text('[interaction]\ndrag_enabled=true\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).audio, AudioConfig())
            path.write_text('[audio]\nenabled=false\nvolume=0.25\n', encoding='utf-8')
            self.assertEqual(AppConfig.load(path).audio, AudioConfig(False, .25))

    def test_clip_directory_relative_to_config_not_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            clips = bell_voice_paths(OracleConfig(voice_directory='approved'), root/'pet.toml')
            self.assertEqual(clips['bell_04_02'], root/'approved'/'bell_04_02.wav')
            absolute = bell_voice_paths(OracleConfig(voice_directory=str(root)), root/'other'/'pet.toml')
            self.assertEqual(absolute['bell_05_01'], root/'bell_05_01.wav')


if __name__ == '__main__':
    unittest.main()
