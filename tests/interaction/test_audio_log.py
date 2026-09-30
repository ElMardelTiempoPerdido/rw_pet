"""验证日志有界、UTF-8 编码，以及磁盘错误不影响语音调用。"""
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rw_creature_pet.interaction import audio_log


class AudioLogTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, LOCALAPPDATA=self.directory))

    def make_logger(self):
        logger = audio_log._logger.__wrapped__()
        for handler in logger.handlers:
            self.addCleanup(handler.close)
        return logger

    def test_utf8_events_rotate_with_bounded_backups(self):
        logger = self.make_logger()
        handler = logger.handlers[0]
        self.assertEqual(handler.maxBytes, 512*1024)
        self.assertEqual(handler.backupCount, 2)
        handler.maxBytes = 180
        with patch.object(audio_log, '_logger', return_value=logger):
            for i in range(20):
                audio_log.voice_event('playback_error', clip='bell_01', error='音频设备响应超时', count=i)
        handler.close()
        path = audio_log.audio_log_path()
        self.assertEqual(path, Path(self.directory)/'rw_creature_pet/logs/voice.log')
        self.assertEqual(len(list(path.parent.glob('voice.log*'))), 3)
        content = path.read_text(encoding='utf-8')
        self.assertIn('音频设备响应超时', content)
        self.assertIn('count=19', content)
        self.assertIn('pid=', content)

    def test_unwritable_directory_falls_back_without_raising(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('read only')):
            logger = self.make_logger()
        self.assertIsInstance(logger.handlers[0], logging.NullHandler)
        logger.info('request_received')

    def test_later_disk_failure_is_nonfatal(self):
        logger = self.make_logger()
        with patch.object(logger.handlers[0], '_open', side_effect=OSError('disk full')):
            with patch.object(audio_log, '_logger', return_value=logger):
                audio_log.voice_event('request_received', clip='bell_01')


if __name__ == '__main__':
    unittest.main()
