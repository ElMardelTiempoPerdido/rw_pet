"""蜥蜴平地／爬墙调试配置，对应现有 TOML 的 [debug] 表。"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class DebugConfig:
    tick_rate: int = 40
    world_width: float = 480.0
    world_height: float = 240.0
    floor_y: float = 180.0

    def __post_init__(self):
        if type(self.tick_rate) is not int or not 1 <= self.tick_rate <= 240:
            raise ValueError("tick_rate 必须为 1～240 的整数")
        values = (self.world_width, self.world_height, self.floor_y)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in values):
            raise ValueError("场景尺寸必须为有限数值")
        if self.world_width < 120 or self.world_height < 100:
            raise ValueError("场景宽度至少 120，高度至少 100")
        if not 40 <= self.floor_y <= self.world_height - 20:
            raise ValueError("floor_y 必须位于 40 和 world_height - 20 之间")
