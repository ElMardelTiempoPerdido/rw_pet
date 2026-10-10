"""监视者形态、避让换位和按固定时间尺度抽签的事件配置。"""
from ..shared.messages import Message
from dataclasses import dataclass
from math import isfinite
import re


APPEARANCE_COLORS = {'standard': '#ffffff', 'friend': '#000000'}


@dataclass(frozen=True, slots=True)
class OverseerSlot:
    id: int = 1
    color: str | None = None
    appearance: str = 'standard'

    def __post_init__(self):
        if type(self.id) is not int or not 1 <= self.id <= 4:
            raise ValueError('overseer.slots id 必须为 1～4 的整数')
        if not isinstance(self.appearance, str) or self.appearance not in APPEARANCE_COLORS:
            raise ValueError('overseer.slots appearance 必须为 standard 或 friend')
        if self.color is None:
            object.__setattr__(self, 'color', APPEARANCE_COLORS[self.appearance])
        if not isinstance(self.color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', self.color):
            raise ValueError('overseer.slots color 必须为 #RRGGBB 颜色')


@dataclass(frozen=True, slots=True)
class OverseerConfig:
    enabled: bool = False
    appearance_mode: str = 'random'
    slots: tuple[OverseerSlot, ...] | None = None
    check_interval: float = 30.
    appearance_probability: float = .15  # 每次检查的概率，不是每秒或每帧。
    duration_min: float = 20.
    duration_max: float = 45.
    cooldown_min: float = 60.
    cooldown_max: float = 120.
    size: float = .6
    color: str = '#72e6c4'  # 兼容旧配置和单模型绘制，运行时由对应槽位主色覆盖
    withdraw_distance: float = 60.
    reemerge_distance: float = 100.
    puppet_withdraw_distance: float = 100.
    puppet_reemerge_distance: float = 150.
    relocation_probability: float = .5  # 每次完全避让隐藏时只抽一次；否则留在原位。
    observation_probability: float = .35  # 完全探出并有观察目标时，每个间隔抽一次。
    observation_interval: float = 12.
    safe_delay: float = .45
    emerge_seconds: float = .5
    withdraw_seconds: float = .25

    def __post_init__(self):
        if self.appearance_mode not in ('random', 'resident'):
            raise ValueError('overseer.appearance_mode 必须为 random 或 resident')
        # 兼容旧 TOML/JSON 中的单色设置；显式空列表表示不配置任何监视者
        slots = self.slots
        if slots is None:
            slots = (OverseerSlot(color=self.color),)
        if not isinstance(slots, (tuple, list)) or len(slots) > 4:
            raise ValueError('overseer.slots 最多允许 4 个槽位')
        slots = tuple(OverseerSlot(**s) if isinstance(s, dict) else s for s in slots)
        if any(not isinstance(s, OverseerSlot) for s in slots):
            raise ValueError('overseer.slots 必须为监视者槽位列表')
        if len({s.id for s in slots}) != len(slots):
            raise ValueError('overseer.slots id 不能重复')
        object.__setattr__(self, 'slots', tuple(sorted(slots, key=lambda s: s.id)))
        if not isinstance(self.enabled, bool):
            raise ValueError('overseer.enabled 必须为布尔值')
        for key in ('appearance_probability', 'relocation_probability', 'observation_probability'):
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
                    'check_interval', 'duration_min', 'duration_max', 'observation_interval'):
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
