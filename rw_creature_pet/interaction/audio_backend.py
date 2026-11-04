"""Qt 媒体播放与默认输出设备适配，不修改语音素材或系统设备设置"""
from PySide6.QtCore import QUrl

from .audio_log import voice_event


class QtMediaBackend:
    """一个媒体播放器复用本地语音，取消后不保留待播请求"""
    def __init__(self, parent):
        from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise RuntimeError('没有可用的音频输出设备')
        self.player = QMediaPlayer(parent)
        self.output = QAudioOutput(device, self.player)
        self.devices = QMediaDevices(self.player)
        self.player.setAudioOutput(self.output)
        self.player.setLoops(1)
        self.player.setPlaybackRate(1.)
        self.requested = False
        self._device_error = ''
        self._device_key = self._key(device)
        self.devices.audioOutputsChanged.connect(self._outputs_changed)

    @staticmethod
    def _key(device):
        # QAudioDevice 的相等判断不能用于发现同一设备的格式变化
        fmt = device.preferredFormat()
        return (bytes(device.id()), fmt.sampleRate(), fmt.channelCount(),
                fmt.sampleFormat(), fmt.channelConfig())

    def _sync_output(self):
        from PySide6.QtMultimedia import QAudioOutput
        device = self.devices.defaultAudioOutput()
        if device.isNull():
            self._device_error = '没有可用的音频输出设备'
            self.stop()
            return
        key = self._key(device)
        if key == self._device_key:
            return
        old = self.output
        output = QAudioOutput(device, self.player)
        output.setVolume(old.volume())
        output.setMuted(old.isMuted())
        # 更换输出而不重设媒体或调用 play，保留进度，也不复活已经取消的请求
        self.player.setAudioOutput(output)
        self.output, self._device_key = output, key
        voice_event('output_device_changed', previous=old.device().description(),
                    device=device.description(), rate=device.preferredFormat().sampleRate(),
                    channels=device.preferredFormat().channelCount())
        old.deleteLater()

    def _outputs_changed(self):
        if self.player is None:
            return
        try:
            self._sync_output()
        except (OSError, RuntimeError, ValueError) as exc:
            self._device_error = str(exc)
            try:
                self.stop()
            except (OSError, RuntimeError, ValueError):
                pass  # 由 VoicePlayer 的下一次状态检查释放失效后端

    def play(self, path):
        self.stop()
        self._device_error = ''
        self._sync_output()  # 播放前也刷新一次，覆盖尚未送达的设备通知
        if self._device_error:
            raise RuntimeError(self._device_error)
        self.requested = True
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.player.play()

    def stop(self):
        self.requested = False
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())  # 撤销异步加载并释放文件，设备重连不补播

    def set_volume(self, volume):
        self.output.setVolume(volume)

    def close(self):
        self.requested = False
        player, self.player = self.player, None
        if player is None:
            return
        try:
            self.devices.audioOutputsChanged.disconnect(self._outputs_changed)
            player.stop()
            player.setSource(QUrl())
        finally:
            # output 和 devices 都由 player 持有，随同一个 QObject 树释放
            self.output = self.devices = None
            player.deleteLater()

    def diagnostics(self):
        return dict(backend='QMediaPlayer', device=self.output.device().description(),
                    default_device=self.devices.defaultAudioOutput().description(),
                    qt_status=self.player.mediaStatus().name,
                    qt_error=self._device_error or self.player.errorString(),
                    playing=self.player.isPlaying(), position_ms=self.player.position(),
                    duration_ms=self.player.duration(), playback_rate=self.player.playbackRate())

    @property
    def state(self):
        if self.player is None:
            return 'idle'
        if (self._device_error or self.player.error() != self.player.Error.NoError
                or self.player.mediaStatus() == self.player.MediaStatus.InvalidMedia):
            return 'error'
        if not self.requested or self.player.mediaStatus() == self.player.MediaStatus.EndOfMedia:
            return 'idle'
        # play() 可以在解码前立即报告 PlayingState，加载结束才开始计片段播放期限
        if self.player.mediaStatus() in (self.player.MediaStatus.NoMedia, self.player.MediaStatus.LoadingMedia):
            return 'loading'
        return 'playing' if self.player.isPlaying() else 'loading'
