"""独立于生物和音频设备的语音请求槽；本身不打开设备、不播放声音。"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VoiceCue:
    clip_id: str
    duration_seconds: float
    reason: str


class VoiceCueChannel:
    """最多保留一个未消费请求；按片段时长预占，限制行为侧的请求频率。

    播放适配器通过 take_pending() 取走请求，再按设备状态避免重叠。未接适配器时到期丢弃，
    不在日后启用声音时补播积压；last_cue / request_count 仅供调试。
    """
    def __init__(self):
        self.pending = self.last_cue = None
        self.remaining = 0.
        self.request_count = 0

    def request(self, cue):
        if self.remaining > 0:
            return False
        self.pending = self.last_cue = cue
        self.remaining = cue.duration_seconds
        self.request_count += 1
        return True

    def step(self, seconds):
        self.remaining = max(0., self.remaining-seconds)
        if self.remaining == 0:
            self.pending = None

    def take_pending(self):
        cue, self.pending = self.pending, None
        return cue

    def cancel(self):
        self.pending = None
        self.remaining = 0.
