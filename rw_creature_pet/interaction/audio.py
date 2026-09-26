"""窗口层的单声部语音播放；物理、随机行为和绘制不访问音频设备。"""
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QUrl, Signal
from .config import AudioConfig


class QtSoundBackend:
    """惰性创建一个 QSoundEffect；异步加载本地 WAV，停止会撤销尚未完成的加载播放。"""
    def __init__(self, parent):
        from PySide6.QtMultimedia import QMediaDevices, QSoundEffect
        if QMediaDevices.defaultAudioOutput().isNull():
            raise RuntimeError('没有可用的音频输出设备')
        self.effect = QSoundEffect(parent)
        self.effect.setLoopCount(1)
        self.requested = False
        self.effect.statusChanged.connect(self._ready)

    def _ready(self):
        if self.requested and self.effect.status() == self.effect.Status.Ready:
            self.requested = False
            self.effect.play()

    def play(self, path):
        self.stop()
        self.requested = True
        self.effect.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self._ready()  # 连续选择相同文件时，Qt 可直接复用已解码数据。

    def stop(self):
        self.requested = False
        self.effect.stop()

    def set_volume(self, volume):
        self.effect.setVolume(volume)

    @property
    def state(self):
        if self.effect.status() == self.effect.Status.Error:
            return 'error'
        if self.requested:
            return 'loading'
        return 'playing' if self.effect.isPlaying() else 'idle'


class VoicePlayer(QObject):
    """只消费即时请求，不排队、不打断正在说的话，也不依赖仿真时钟判断结束。"""
    status_changed = Signal(str)

    def __init__(self, clips, config=AudioConfig(), parent=None, *,
                 backend_factory=QtSoundBackend, time_source=monotonic, asset_error=''):
        super().__init__(parent)
        self.clips = {key: Path(path) for key, path in clips.items()}
        self.enabled, self.volume = config.enabled, config.volume
        self._factory, self._time = backend_factory, time_source
        self._backend = None
        self.channel = None
        self.current = None
        self.play_count = 0
        self.asset_error = asset_error
        self.error = asset_error
        self._deadline = 0.
        self._started = False
        self._last_status = ''

    @property
    def status(self):
        if not self.enabled or self.volume == 0:
            return '语音已静音'
        if self.error:
            return f'语音不可用：{self.error}'
        if self.current:
            return f'{"正在播放" if self._started else "正在加载"} {self.current.clip_id}'
        return '语音就绪'

    def _notify(self):
        status = self.status
        if status != self._last_status:
            self._last_status = status
            self.status_changed.emit(status)

    def stop(self):
        if self._backend is not None and self.current is not None:
            self._backend.stop()
        if self.channel is not None:
            self.channel.cancel()
        self.current = None
        self._started = False
        self._notify()

    def configure(self, *, enabled=None, volume=None):
        config = AudioConfig(self.enabled if enabled is None else enabled,
                             self.volume if volume is None else volume)
        was_audible = self.enabled and self.volume > 0
        audible = config.enabled and config.volume > 0
        if audible != was_audible:
            self.stop()  # 开关瞬间丢弃请求；取消静音不会补播。
        self.enabled, self.volume = config.enabled, config.volume
        if self._backend is not None:
            self._backend.set_volume(self.volume)
        self._notify()

    def _poll(self):
        if self.current is None:
            return
        state = self._backend.state
        if state == 'error':
            self.error = f'{self.current.clip_id} 加载或播放失败'
            self.stop()
        elif self._time() >= self._deadline:
            self.error = f'{self.current.clip_id} 音频设备响应超时'
            self.stop()
        elif state == 'playing':
            if not self._started:
                self._started = True
                self.play_count += 1
                self._deadline = self._time()+self.current.duration_seconds+3.
        elif state == 'idle' and self._started:
            self.current = None
            self._started = False

    def sync(self, channel, *, paused=False):
        # reset / 工作区重建会创建新通道；旧通道的异步加载必须失效。
        if channel is not self.channel:
            self.stop()
            self.channel = channel
        if paused:
            self.stop()
            return
        self._poll()
        cue = channel.take_pending() if channel is not None else None
        if cue and self.enabled and self.volume > 0 and self.current is None and not self.asset_error:
            path = self.clips.get(cue.clip_id)
            if path is None or not path.is_file():
                self.error = f'缺少音频 {path or cue.clip_id}'
            else:
                try:
                    if self._backend is None:
                        self._backend = self._factory(self)
                    self.current = cue
                    self._started = False
                    self._deadline = self._time()+5.
                    self._backend.set_volume(self.volume)
                    self._backend.play(path)
                    self.error = ''
                    self._poll()
                except (OSError, RuntimeError, ValueError) as exc:
                    self.error = str(exc)
                    self.stop()
        self._notify()
