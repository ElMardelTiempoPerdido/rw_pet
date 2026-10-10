"""珍珠的无声播放效果；运行期只采样预计算曲线，不加载音频或 FFT。"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class SpectrumCurve:
    values: tuple[float, ...]
    duration: float
    rate: int = 40

    def __post_init__(self):
        if (not self.values or not isfinite(self.duration) or self.duration <= 0 or self.rate <= 0
                or abs(len(self.values)-self.duration*self.rate) > 1
                or any(not isfinite(v) or not 0 <= v <= 1 for v in self.values)):
            raise ValueError('无效的珍珠频谱曲线')

    def sample(self, seconds):
        index = max(0., min(len(self.values)-1., seconds*self.rate))
        low = int(index)
        high = min(low+1, len(self.values)-1)
        return self.values[low]+(self.values[high]-self.values[low])*(index-low)


class PearlPlayback:
    """只有被抽取并进入阅读的珍珠持有此状态；收尾时淡出，不触发声音。"""
    def __init__(self, curve, start, duration):
        self.curve = curve
        self.start = max(0., start) % curve.duration
        self.duration = duration
        self.ticks = 0
        self.strength = self.previous_strength = curve.sample(self.start)
        self.fade = self.previous_fade = 0.

    def step(self):
        self.previous_strength = self.strength
        self.previous_fade = self.fade
        self.ticks += 1
        # 半秒淡入/淡出只影响透明度；尺寸始终跟随独立的频谱强度。
        # 长时间阅读循环采样整曲，保持原节奏；循环处不重新淡入或提前结束。
        self.fade = min(1., self.ticks/20, max(0., (self.duration-self.ticks)/20))
        self.strength = self.curve.sample((self.start+self.ticks/40) % self.curve.duration)

    def sample(self, alpha):
        return self.previous_strength+(self.strength-self.previous_strength)*alpha

    def sample_fade(self, alpha):
        return self.previous_fade+(self.fade-self.previous_fade)*alpha
