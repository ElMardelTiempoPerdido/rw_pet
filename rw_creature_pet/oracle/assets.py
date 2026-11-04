"""桌面启动与设置共用的资源准备；QImage 可在线程中加载，不创建 QWidget。"""
from dataclasses import dataclass, field
from pathlib import Path

from ..shared.atlas import Atlas, AtlasError, extract_atlas
from .pearls.glyphs import load_pearl_glyphs
from .graphics.render import OracleRenderer
from .audio.assets import prepare_voice
from .audio.voice import VOICE_CLIPS, VOICE_RESOURCES
from .audio.mod_assets import prepare_sig_voice
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
            config.oracle.voice == 'none' or VOICE_RESOURCES[config.oracle.voice] in self.resources.items)

    def include_checked_voices(self, previous):
        """同一来源的已检查语音累积复用，新结果优先；不同游戏目录不混用"""
        if previous is None or self.source_key is None or self.source_key != previous.source_key:
            return self
        for voice, resource in VOICE_RESOURCES.items():
            if resource not in self.resources.items and resource in previous.resources.items:
                self.resources.items[resource] = previous.resources.items[resource]
                for clip in VOICE_CLIPS[voice]:
                    if clip.clip_id in previous.voice_paths:
                        self.voice_paths[clip.clip_id] = previous.voice_paths[clip.clip_id]
        return self


def prepare_oracle_assets(config, *, check_all_voices=False):
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
    # 独立 WAV 检测开销很小，启动即提供 Sig 选项状态，无需先选中缺失的模组
    voice_results = {'sig': prepare_sig_voice(config.game_dir)}
    if check_all_voices:
        from dataclasses import replace
        from .audio.chat_assets import prepare_chat_voices
        voice_results.update(prepare_chat_voices(config.game_dir))
        voice_config = replace(config, oracle=replace(config.oracle, voice='bell'))
    else:
        voice_config = config
    if voice_config.oracle.voice != 'none' and voice_config.oracle.voice not in voice_results:
        try:
            prepared = prepare_voice(voice_config)
        except Exception as exc:
            prepared = {}, str(exc)
        voice_results[voice_config.oracle.voice] = prepared
    for voice, (voice_paths, voice_error) in voice_results.items():
        report.record(VOICE_RESOURCES[voice], error=voice_error, available=bool(voice_paths))
        if not voice_error:
            paths.update(voice_paths)
        if voice == config.oracle.voice:
            error = voice_error
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
