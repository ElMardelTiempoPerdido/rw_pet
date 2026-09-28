"""桌面启动与设置共用的资源准备；QImage 可在线程中加载，不创建 QWidget。"""
from dataclasses import dataclass

from ..shared.atlas import Atlas, AtlasError, extract_atlas
from .glyphs import load_pearl_glyphs
from .render import OracleRenderer
from .voice_assets import prepare_bell_voice


@dataclass
class OracleAssets:
    renderer: OracleRenderer
    message: str
    voice_paths: dict
    voice_error: str


def prepare_oracle_assets(config):
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors)
    message = ''
    try:
        renderer.glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
    except (AtlasError, OSError, ValueError) as exc:
        message = f'珍珠投影不可用：{exc}'
    paths, error = prepare_bell_voice(config)
    return OracleAssets(renderer, message, paths, error)
