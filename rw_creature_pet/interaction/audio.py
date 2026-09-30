"""窗口层的单声部语音播放；物理、随机行为和绘制不访问音频设备。"""
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QUrl, Signal
from .audio_log import voice_event
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
        if self.effect is not None and self.requested and self.effect.status() == self.effect.Status.Ready:
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

    def close(self):
        """撤销延迟播放、断开回调并释放 Qt 对象；异常恢复不能留下旧实例。"""
        self.requested = False
        effect, self.effect = self.effect, None
        if effect is None:
            return
        try:
            effect.statusChanged.disconnect(self._ready)
            effect.stop()
        finally:
            effect.deleteLater()

    def diagnostics(self):
        from PySide6.QtMultimedia import QMediaDevices
        return dict(device=self.effect.audioDevice().description(),
                    default_device=QMediaDevices.defaultAudioOutput().description(),
                    qt_status=self.effect.status().name, playing=self.effect.isPlaying())

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
        self._log('player_created', enabled=self.enabled, volume=self.volume, asset_error=asset_error)

    def _log(self, event, **fields):
        voice_event(event, player=f'{id(self):x}', **fields)

    def _diagnostics(self):
        read = getattr(self._backend, 'diagnostics', None)
        try:
            return read() if read is not None else {}
        except (OSError, RuntimeError, ValueError) as exc:
            return {'diagnostics_error': str(exc)}

    def _discard_backend(self):
        backend, self._backend = self._backend, None
        if backend is not None:
            try:
                getattr(backend, 'close', backend.stop)()
            except (OSError, RuntimeError, ValueError) as exc:
                self._log('backend_cleanup_error', error=str(exc))
            self._log('backend_discarded')

    def _fail(self, message, reason, **fields):
        self.error = message
        self._log('playback_error', reason=reason, error=message,
                  clip=self.current.clip_id if self.current else None,
                  **fields, **self._diagnostics())
        self._discard_backend()
        self.stop()  # 同时丢弃旧请求；仅下一个新请求能够创建播放器。

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
        current, self.current = self.current, None
        self._started = False
        if self.channel is not None:
            if self.channel.pending is not None:
                self._log('request_dropped', clip=self.channel.pending.clip_id, reason='stopped')
            self.channel.cancel()
        if current is not None:
            self._log('playback_stopped', clip=current.clip_id)
            if self._backend is not None:
                try:
                    self._backend.stop()
                except (OSError, RuntimeError, ValueError) as exc:
                    self._fail(str(exc), 'stop_exception')
        self._notify()

    def configure(self, *, enabled=None, volume=None):
        config = AudioConfig(self.enabled if enabled is None else enabled,
                             self.volume if volume is None else volume)
        was_audible = self.enabled and self.volume > 0
        audible = config.enabled and config.volume > 0
        if audible != was_audible:
            self.stop()  # 开关瞬间丢弃请求；取消静音不会补播。
        changed = (self.enabled, self.volume) != (config.enabled, config.volume)
        self.enabled, self.volume = config.enabled, config.volume
        if changed:
            self._log('configured', enabled=self.enabled, volume=self.volume)
        if self._backend is not None:
            try:
                self._backend.set_volume(self.volume)
            except (OSError, RuntimeError, ValueError) as exc:
                self._fail(str(exc), 'volume_exception')
        self._notify()

    def _poll(self):
        if self.current is None:
            return
        try:
            state = self._backend.state
        except (OSError, RuntimeError, ValueError) as exc:
            self._fail(str(exc), 'state_exception')
            return
        if state == 'error':
            self._fail(f'{self.current.clip_id} 加载或播放失败', 'backend_error', state=state)
        elif self._time() >= self._deadline:
            self._fail(f'{self.current.clip_id} 音频设备响应超时',
                       'playback_timeout' if self._started else 'load_timeout', state=state)
        elif state == 'playing':
            if not self._started:
                self._started = True
                self.play_count += 1
                self._deadline = self._time()+self.current.duration_seconds+3.
                self._log('playback_started', clip=self.current.clip_id)
        elif state == 'idle' and self._started:
            self._log('playback_finished', clip=self.current.clip_id)
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
        if cue:
            self._log('request_received', clip=cue.clip_id, reason=cue.reason,
                      enabled=self.enabled, volume=self.volume)
            blocked = ('muted' if not self.enabled or self.volume == 0 else
                       'busy' if self.current is not None else 'asset_error' if self.asset_error else '')
            if blocked:
                self._log('request_dropped', clip=cue.clip_id, reason=blocked)
                self._notify()
                return
            path = self.clips.get(cue.clip_id)
            if path is None or not path.is_file():
                self.error = f'缺少音频 {path or cue.clip_id}'
                self._log('asset_missing', clip=cue.clip_id, path=str(path))
            else:
                self.current = cue
                self._started = False
                self._deadline = self._time()+5.
                try:
                    if self._backend is None:
                        self._backend = self._factory(self)
                        self._log('backend_created', **self._diagnostics())
                    self._backend.set_volume(self.volume)
                    self._log('load_started', clip=cue.clip_id, path=str(path))
                    self._backend.play(path)
                    self.error = ''
                    self._poll()
                except (OSError, RuntimeError, ValueError) as exc:
                    self._fail(str(exc), 'play_exception')
        self._notify()
