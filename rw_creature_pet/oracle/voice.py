"""Bell 采访片段时间表及本地已处理音频的路径；不在运行时裁剪。"""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BellVoiceClip:
    clip_id: str
    start: float
    end: float

    @property
    def duration(self):
        return self.end-self.start

    @property
    def filename(self):
        return self.clip_id+'.wav'


# text_audio_talkshow.txt 中 convo:240 的 1 / 3 / 5 / 7 / 9。
# 采访是混合录音，字幕时间切分仍可能包含抢话时重叠的主持人声音。
# 第 04 段按试听反馈延长 0.3 秒，保留尾音并避开更晚的杂音。
BELL_VOICE_CLIPS = tuple(BellVoiceClip(f'bell_{i:02}', start, end)
    for i, (start, end) in enumerate(((6., 8.5), (14.5, 19.6), (22.23, 23.6),
                                     (24.5, 34.8), (36.5, 42.1)), 1))


def bell_voice_paths(config, config_path=None):
    directory = Path(config.voice_directory).expanduser()
    if not directory.is_absolute():
        # 从其他工作目录启动也读取同一份缓存；指定 TOML 时以该文件目录为基准。
        root = Path(config_path).resolve().parent if config_path else Path(__file__).resolve().parents[2]
        directory = root/directory
    return {clip.clip_id: directory/clip.filename for clip in BELL_VOICE_CLIPS}
