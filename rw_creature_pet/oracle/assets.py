"""桌面启动与设置共用的资源准备；QImage 可在线程中加载，不创建 QWidget。"""
from dataclasses import dataclass, field
from pathlib import Path

from ..shared.atlas import Atlas, AtlasError, extract_atlas
from .pearls.glyphs import load_pearl_glyphs
from .graphics.render import OracleRenderer
from .audio.assets import prepare_bell_voice
from .pearls.playback_assets import prepare_pearl_playback
from .effects.projection_assets import prepare_projection
from ..resources.status import ResourceReport


def resource_key(config):
    return (str(Path(config.game_dir).resolve()), config.oracle.voice_directory)


@dataclass
class OracleAssets:
    renderer: OracleRenderer
    message: str
    voice_paths: dict
    voice_error: str
    resources: ResourceReport = field(default_factory=ResourceReport)
    source_key: tuple | None = None

    def reusable(self, config):
        # 未携带快照的几何预览仍兼容；真实资源必须匹配安装位置与语音来源
        if self.source_key is None:
            return True
        return self.source_key == resource_key(config) and (
            config.oracle.voice == 'none' or 'bell_voice' in self.resources.items)


def prepare_oracle_assets(config):
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.active_colors)
    report = ResourceReport()
    report.record('main_atlas')
    messages = []
    try:
        renderer.glyphs = load_pearl_glyphs(config.game_dir, atlas.root)
        report.record('pearl_glyphs')
    except Exception as exc:
        report.record('pearl_glyphs', error=str(exc))
        messages.append(f'珍珠投影不可用：{exc}')
    paths, error = {}, ''
    if config.oracle.voice != 'none':
        try:
            paths, error = prepare_bell_voice(config)
        except Exception as exc:
            error = str(exc)
        report.record('bell_voice', error=error, available=bool(paths))
        if error:
            paths = {}
    for key, prepare, attribute in (
        ('pearl_playback_curve', lambda: prepare_pearl_playback(renderer), 'playback_curve'),
        ('scan_images', lambda: prepare_projection(config.game_dir, renderer), 'projection_images'),
    ):
        try:
            optional_error = prepare()
            if key == 'pearl_playback_curve' and not optional_error:
                atlas.sprite('LizardBubble6')
        except Exception as exc:
            optional_error = str(exc)
        if optional_error:
            setattr(renderer, attribute, () if key == 'scan_images' else None)
            messages.append(str(optional_error))
        report.record(key, error=optional_error, available=bool(getattr(renderer, attribute)))
    return OracleAssets(renderer, ' / '.join(messages), paths, error, report, resource_key(config))
