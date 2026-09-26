"""只读配置；用户修改的配置不会被启动过程覆盖。"""
from dataclasses import dataclass
from pathlib import Path
import tomllib

from .lizard.config import DebugConfig
from .oracle.config import OracleConfig
from .shared.paths import DEFAULT_GAME_DIR
from .interaction.config import AudioConfig, InteractionConfig


@dataclass(frozen=True, slots=True)
class AppConfig:
    game_dir: Path = DEFAULT_GAME_DIR
    debug: DebugConfig = DebugConfig()
    oracle: OracleConfig = OracleConfig()
    interaction: InteractionConfig = InteractionConfig()
    audio: AudioConfig = AudioConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        if path is None:
            return cls()
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        unknown = set(data) - {"game_dir", "debug", "oracle", "interaction", "audio"}
        if unknown:
            raise ValueError(f"未知配置字段：{', '.join(sorted(unknown))}")
        game_dir = data.get("game_dir", str(DEFAULT_GAME_DIR))
        if not isinstance(game_dir, str) or not game_dir.strip():
            raise ValueError("game_dir 必须为非空路径字符串")
        return cls(Path(game_dir), DebugConfig(**data.get("debug", {})),
                   OracleConfig.from_mapping(data.get('oracle', {})),
                   InteractionConfig(**data.get('interaction', {})),
                   AudioConfig(**data.get('audio', {})))
