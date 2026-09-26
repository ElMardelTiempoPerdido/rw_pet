"""Bell 采访片段时间表及自定义音频路径；自动初始化见 voice_assets。"""
from dataclasses import dataclass
from pathlib import Path


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


def bell_voice_paths(config, config_path=None):
    if config.voice_directory == 'auto':
        raise ValueError('自动语音目录需要通过 voice_assets 初始化')
    directory = Path(config.voice_directory).expanduser()
    if not directory.is_absolute():
        # 从其他工作目录启动也读取同一份缓存；指定 TOML 时以该文件目录为基准。
        root = Path(config_path).resolve().parent if config_path else Path(__file__).resolve().parents[2]
        directory = root/directory
    return {clip.clip_id: directory/clip.filename for clip in BELL_VOICE_CLIPS}
