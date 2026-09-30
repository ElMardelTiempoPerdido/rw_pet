"""形态与原位避让参数；事件概率和寿命在接入事件调度时再添加。"""
from dataclasses import dataclass
from math import isfinite
import re


@dataclass(frozen=True, slots=True)
class OverseerConfig:
    size: float = .6
    color: str = '#72e6c4'  # 原版普通 Overseer 默认主色，暂不代表 Bell 的最终配色。
    withdraw_distance: float = 60.
    reemerge_distance: float = 100.
    safe_delay: float = .45
    emerge_seconds: float = .5
    withdraw_seconds: float = .25

    def __post_init__(self):
        if isinstance(self.size, bool) or not isinstance(self.size, (int, float)) or not isfinite(self.size) or not .5 <= self.size <= 1.:
            raise ValueError('overseer.size 必须在原版的 0.5～1 范围内')
        if not isinstance(self.color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.color):
            raise ValueError('overseer.color 必须为 #RRGGBB 颜色')
        for key in ('withdraw_distance', 'reemerge_distance', 'emerge_seconds', 'withdraw_seconds'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f'overseer.{key} 必须为有限正数')
        if (isinstance(self.safe_delay, bool) or not isinstance(self.safe_delay, (int, float))
                or not isfinite(self.safe_delay) or self.safe_delay < 0):
            raise ValueError('overseer.safe_delay 必须为有限非负数')
        if self.reemerge_distance <= self.withdraw_distance:
            raise ValueError('overseer.reemerge_distance 必须大于 withdraw_distance')
