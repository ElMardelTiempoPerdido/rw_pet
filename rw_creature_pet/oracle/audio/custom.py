"""本地自定义语音快照；扫描只发生于初始化或用户刷新，不进入仿真循环"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import struct


PREFIX = 'custom:'
MISSING = '自定义语音目录中没有可用的 WAV 文件'


def custom_voice_name(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return None
    name = value[len(PREFIX):]
    if (not name or name in ('.', '..') or name.endswith((' ', '.'))
            or any(c in '/\\:<>"|?*' or ord(c) < 32 for c in name)):
        return None
    return name


def voice_directory():
    from ...presets.common import default_library_directory
    return default_library_directory('voices')


@dataclass(frozen=True)
class CustomVoiceClip:
    clip_id: str
    duration: float
    path: Path


@dataclass(frozen=True)
class CustomVoice:
    name: str
    clips: tuple = ()
    signature: tuple = ()
    error: str = MISSING

    @property
    def paths(self):
        return {clip.clip_id: clip.path for clip in self.clips}


@lru_cache(maxsize=256)
def wav_duration(path, size, modified):
    """只读 RIFF 元数据，支持 PCM / 浮点 WAV，不解码或载入整段音频"""
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
            raise ValueError('Invalid WAV header')
        end = struct.unpack_from('<I', header, 4)[0]+8
        if end > size:
            raise ValueError('Truncated WAV')
        fmt, data_size = None, 0
        while stream.tell()+8 <= end:
            kind, length = struct.unpack('<4sI', stream.read(8))
            start = stream.tell()
            if start+length > end:
                raise ValueError('Truncated WAV chunk')
            if kind == b'fmt ':
                fmt = stream.read(min(length, 40))
            elif kind == b'data':
                data_size += length
            stream.seek(start+length+(length % 2))
        if fmt is None or len(fmt) < 16:
            raise ValueError('Missing WAV format')
        tag, channels, rate, _, block, bits = struct.unpack_from('<HHIIHH', fmt)
        if tag == 0xfffe and len(fmt) >= 40:
            # WAVE_FORMAT_EXTENSIBLE 的 PCM / IEEE_FLOAT 子格式 GUID
            if fmt[28:40] != bytes.fromhex('00001000800000aa00389b71'):
                raise ValueError('Unsupported WAV subtype')
            tag = struct.unpack_from('<I', fmt, 24)[0]
        widths = {1: (8, 16, 24, 32), 3: (32, 64)}
        if (tag not in widths or bits not in widths[tag] or not 1 <= channels <= 8
                or rate <= 0 or block != channels*(bits//8)
                or not data_size or data_size % block):
            raise ValueError('Unsupported or empty WAV')
        return data_size/block/rate


_voices = {}


def _read_voice(root, name):
    directory = root/name
    clips, signature = [], []
    try:
        files = sorted((p for p in directory.iterdir() if p.suffix.lower() == '.wav' and p.is_file()),
                       key=lambda p: (p.name.casefold(), p.name))
        for path in files:
            try:
                stat = path.stat()
                signature.append((path.name, stat.st_size, stat.st_mtime_ns))
                duration = wav_duration(path, stat.st_size, stat.st_mtime_ns)
                clips.append(CustomVoiceClip(PREFIX+name+'/'+path.name, duration, path))
            except (OSError, ValueError, struct.error):
                continue  # 单个损坏文件不禁用同目录中的其他录音
    except OSError:
        pass
    return CustomVoice(name, tuple(clips), tuple(signature), '' if clips else MISSING)


def scan_custom_voices():
    root = voice_directory().resolve()
    result = {}
    try:
        for directory in sorted(root.iterdir(), key=lambda p: (p.name.casefold(), p.name)):
            key = PREFIX+directory.name
            if directory.is_dir() and custom_voice_name(key) is not None:
                result[key] = _read_voice(root, directory.name)
    except OSError:
        pass
    _voices[root] = result
    return dict(result)


def custom_voice(value):
    name = custom_voice_name(value)
    if name is None:
        raise ValueError('Invalid custom voice identifier')
    root = voice_directory().resolve()
    if root not in _voices:
        scan_custom_voices()
    return _voices[root].get(value, CustomVoice(name))
