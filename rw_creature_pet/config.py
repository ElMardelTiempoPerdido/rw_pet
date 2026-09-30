"""不可变应用配置；TOML 默认值与用户设置共用验证。"""
from dataclasses import dataclass
from pathlib import Path
import tomllib

from .lizard.config import DebugConfig
from .oracle.config import OracleConfig
from .overseer.config import OverseerConfig
from .shared.paths import DEFAULT_GAME_DIR
from .interaction.config import AudioConfig, InteractionConfig


@dataclass(frozen=True, slots=True)
class DesktopConfig:
    scale: float = 1.
    autonomous: bool = True

    def __post_init__(self):
        if isinstance(self.scale, bool) or self.scale not in (1., 1.5, 2.):
            raise ValueError('desktop.scale 必须为 1、1.5 或 2')
        if type(self.autonomous) is not bool:
            raise ValueError('desktop.autonomous 必须为布尔值')


@dataclass(frozen=True, slots=True)
class AppConfig:
    game_dir: Path = DEFAULT_GAME_DIR
    debug: DebugConfig = DebugConfig()
    oracle: OracleConfig = OracleConfig()
    interaction: InteractionConfig = InteractionConfig()
    audio: AudioConfig = AudioConfig()
    desktop: DesktopConfig = DesktopConfig()
    overseer: OverseerConfig = OverseerConfig()

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        if path is None:
            return cls()
        if path.suffix.lower() == '.json':
            # 调试窗口重载配色也使用当前用户文件，共用版本校验与路径解析。
            from .settings_store import SettingsStore
            return SettingsStore(path).load()
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data) -> "AppConfig":
        if not isinstance(data, dict):
            raise ValueError('配置必须为对象')
        unknown = set(data) - {"game_dir", "debug", "oracle", "interaction", "audio", "desktop", "overseer"}
        if unknown:
            raise ValueError(f"未知配置字段：{', '.join(sorted(unknown))}")
        game_dir = data.get("game_dir", str(DEFAULT_GAME_DIR))
        if not isinstance(game_dir, str) or not game_dir.strip():
            raise ValueError("game_dir 必须为非空路径字符串")
        return cls(Path(game_dir), DebugConfig(**data.get("debug", {})),
                   OracleConfig.from_mapping(data.get('oracle', {})),
                   InteractionConfig(**data.get('interaction', {})),
                   AudioConfig(**data.get('audio', {})),
                   DesktopConfig(**data.get('desktop', {})),
                   OverseerConfig(**data.get('overseer', {})))
