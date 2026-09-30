"""语音事件诊断；不记录逐帧状态，日志不可写时不影响桌宠运行。"""
from functools import lru_cache
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path


class _QuietRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record):
        # 磁盘已满、权限变化等日志故障不能中断音频，也不依赖打包版的 stderr。
        pass


def audio_log_path():
    root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))
    return root/'rw_creature_pet'/'logs'/'voice.log'


@lru_cache(maxsize=1)
def _logger():
    logger = logging.Logger('rw_creature_pet.voice', level=logging.INFO)
    logger.propagate = False
    try:
        path = audio_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = _QuietRotatingFileHandler(
            path, maxBytes=512*1024, backupCount=2, encoding='utf-8', delay=True)
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s pid=%(process)d %(message)s'))
    logger.addHandler(handler)
    return logger


def voice_event(event, **fields):
    _logger().info('%s %s', event, ' '.join(f'{key}={value!r}' for key, value in fields.items()))
