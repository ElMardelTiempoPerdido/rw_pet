"""只读配置；用户修改的配置不会被启动过程覆盖。"""
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import tomllib

from .oracle_config import OracleConfig


DEFAULT_GAME_DIR = Path(r"D:\steam\steamapps\common\Rain World")


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


@dataclass(frozen=True, slots=True)
class AppConfig:
    game_dir: Path = DEFAULT_GAME_DIR
    debug: DebugConfig = DebugConfig()
    oracle: OracleConfig = OracleConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        if path is None:
            return cls()
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        unknown = set(data) - {"game_dir", "debug", "oracle"}
        if unknown:
            raise ValueError(f"未知配置字段：{', '.join(sorted(unknown))}")
        game_dir = data.get("game_dir", str(DEFAULT_GAME_DIR))
        if not isinstance(game_dir, str) or not game_dir.strip():
            raise ValueError("game_dir 必须为非空路径字符串")
        return cls(Path(game_dir), DebugConfig(**data.get("debug", {})),
                   OracleConfig.from_mapping(data.get('oracle', {})))
