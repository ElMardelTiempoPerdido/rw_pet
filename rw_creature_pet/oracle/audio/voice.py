"""内置语音索引及 Bell 采访切片时间表"""
from dataclasses import dataclass
from pathlib import Path

from ...shared.paths import PACKAGE_ROOT

@dataclass(frozen=True, slots=True)
class BellVoiceClip:
    clip_id: str
    start: float
    end: float
    source_id: str = ''

    @property
    def duration(self):
        return self.end-self.start

    @property
    def filename(self):
        return self.clip_id+'.wav'


# text_audio_talkshow.txt 中 convo:240 的 1 / 3 / 5 / 7 / 9。
# 采访是混合录音，字幕时间切分仍可能包含抢话时重叠的主持人声音。
# 第 04 段按试听反馈延长 0.3 秒，保留尾音并避开更晚的杂音。
BELL_VOICE_SOURCES = tuple(BellVoiceClip(f'bell_{i:02}', start, end)
    for i, (start, end) in enumerate(((6., 8.5), (14.5, 19.6), (22.23, 23.6),
                                     (24.5, 34.8), (36.5, 42.1)), 1))

# 试听确认的停顿切点，秒数相对于已处理的五段原片段开头。
BELL_VOICE_SPLITS = {'bell_02': (1.88, 3.58), 'bell_04': (4.18, 8.15), 'bell_05': (3.07,)}


def _playback_clips():
    for source in BELL_VOICE_SOURCES:
        cuts = BELL_VOICE_SPLITS.get(source.clip_id, ())
        boundaries = (source.start, *(source.start+cut for cut in cuts), source.end)
        for i, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
            clip_id = f'{source.clip_id}_{i:02}' if cuts else source.clip_id
            yield BellVoiceClip(clip_id, start, end, source.clip_id)


BELL_VOICE_CLIPS = tuple(_playback_clips())


@dataclass(frozen=True)
class ChatVoiceClip:
    clip_id: str
    asset_name: str
    duration: float

    @property
    def filename(self):
        return self.clip_id+'.wav'


# 本体 sounds.txt 的 SL/SS_AI_Talk_1～5，完整独立录音，不包含 Protest 或 Pain
CHAT_VOICE_CLIPS = {
    'moon': tuple(ChatVoiceClip(f'moon_chat_{i:02}', f'MoonChat{i}', duration)
                  for i, duration in enumerate((5.316, 6.896, 3.400, 6.274, 6.705), 1)),
    'pebbles': tuple(ChatVoiceClip(f'pebbles_chat_{i:02}', f'PebblesChat{i}', duration)
                     for i, duration in enumerate((2.858, 5.064, 7.677, 2.164, 5.390), 1)),
}
# Hunter Expansion 的完整日常对话，不使用 Attacked / Break / Recover
SIG_VOICE_CLIPS = tuple(
    ChatVoiceClip(f'sig_{kind}_{i:02}', f'NSH-{asset}-{i}', duration)
    for kind, asset, durations in (
        ('short', 'ShortDialogue', (12.240, 9.504)),
        ('long', 'LongDialogue', (17.808, 20.880, 20.928)),
    ) for i, duration in enumerate(durations, 1)
)
# Watcher 的 Prince_Talk，共 22 段完整录音；不包含机械臂、印记等音效
# 帧数来自原始 44100 Hz PCM，便于播放调度使用完整时长
PRINCE_VOICE_CLIPS = tuple(
    ChatVoiceClip(f'prince_talk_{i:02}', f'RWTW_PrinceTalk1_{i:02}', frames/44100)
    for i, frames in enumerate((
        120304, 134921, 95569, 73216, 128175, 66336, 84326, 94445, 80590, 98942,
        127050, 107937, 104564, 149537, 145040, 80953, 104564, 119180, 110185,
        107937, 112434, 109061,
    ), 1)
)
GAME_VOICE_CLIPS = {**CHAT_VOICE_CLIPS, 'prince': PRINCE_VOICE_CLIPS}
VOICE_CLIPS = {'bell': BELL_VOICE_CLIPS, **CHAT_VOICE_CLIPS, 'sig': SIG_VOICE_CLIPS,
               'prince': PRINCE_VOICE_CLIPS, 'none': ()}
VOICE_RESOURCES = {name: name+'_voice' for name in VOICE_CLIPS if name != 'none'}


def valid_voice(value):
    from .custom import custom_voice_name
    return isinstance(value, str) and (value in VOICE_CLIPS or custom_voice_name(value) is not None)


def voice_clips(value):
    if value in VOICE_CLIPS:
        return VOICE_CLIPS[value]
    from .custom import custom_voice
    return custom_voice(value).clips


def legacy_voice(body_appearance):
    """仅补齐旧配置的缺省选项，显式选择语音后不再依据主体外观推断"""
    return 'bell' if body_appearance == 'bell' else 'none'


def bell_voice_paths(config, config_path=None):
    if config.voice_directory == 'auto':
        raise ValueError('自动语音目录需要通过 voice_assets 初始化')
    directory = Path(config.voice_directory).expanduser()
    if not directory.is_absolute():
        # 从其他工作目录启动也读取同一份缓存；指定 TOML 时以该文件目录为基准。
        root = Path(config_path).resolve().parent if config_path else PACKAGE_ROOT.parent
        directory = root/directory
    return {clip.clip_id: directory/clip.filename for clip in BELL_VOICE_CLIPS}
