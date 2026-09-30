"""监视者形态、避让换位和按固定时间尺度抽签的事件配置。"""
from ..shared.messages import Message
from dataclasses import dataclass
from math import isfinite
import re


@dataclass(frozen=True, slots=True)
class OverseerConfig:
    enabled: bool = False
    check_interval: float = 30.
    appearance_probability: float = .15  # 每次检查的概率，不是每秒或每帧。
    duration_min: float = 20.
    duration_max: float = 45.
    cooldown_min: float = 60.
    cooldown_max: float = 120.
    size: float = .6
    color: str = '#72e6c4'  # 原版普通 Overseer 默认主色，暂不代表 Bell 的最终配色。
    withdraw_distance: float = 60.
    reemerge_distance: float = 100.
    puppet_withdraw_distance: float = 100.
    puppet_reemerge_distance: float = 150.
    relocation_probability: float = .5  # 每次完全避让隐藏时只抽一次；否则留在原位。
    safe_delay: float = .45
    emerge_seconds: float = .5
    withdraw_seconds: float = .25

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise ValueError('overseer.enabled 必须为布尔值')
        for key in ('appearance_probability', 'relocation_probability'):
            probability = getattr(self, key)
            if (isinstance(probability, bool) or not isinstance(probability, (int, float))
                    or not isfinite(probability) or not 0 <= probability <= 1):
                raise ValueError(Message('overseer.{value0} 必须在 0～1 之间', value0=key))
        if isinstance(self.size, bool) or not isinstance(self.size, (int, float)) or not isfinite(self.size) or not .5 <= self.size <= 1.:
            raise ValueError('overseer.size 必须在原版的 0.5～1 范围内')
        if not isinstance(self.color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.color):
            raise ValueError('overseer.color 必须为 #RRGGBB 颜色')
        for key in ('withdraw_distance', 'reemerge_distance', 'emerge_seconds', 'withdraw_seconds',
                    'puppet_withdraw_distance', 'puppet_reemerge_distance',
                    'check_interval', 'duration_min', 'duration_max'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(Message('overseer.{value0} 必须为有限正数', value0=key))
        for key in ('safe_delay', 'cooldown_min', 'cooldown_max'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(Message('overseer.{value0} 必须为有限非负数', value0=key))
        for prefix in ('duration', 'cooldown'):
            if getattr(self, prefix+'_min') > getattr(self, prefix+'_max'):
                raise ValueError(Message('overseer.{value0}_min 不能大于 {value1}_max', value0=prefix, value1=prefix))
        if self.reemerge_distance <= self.withdraw_distance:
            raise ValueError('overseer.reemerge_distance 必须大于 withdraw_distance')
        if self.puppet_reemerge_distance <= self.puppet_withdraw_distance:
            raise ValueError('overseer.puppet_reemerge_distance 必须大于 puppet_withdraw_distance')
