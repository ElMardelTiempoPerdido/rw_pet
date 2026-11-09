"""Bell 缓存校验及 v2 到 v3 的一次性增益转换，不改写旧缓存"""
from hashlib import sha256
import io
import json
import math
import wave

from .errors import VoiceAssetError
from .processing import apply_pcm_gain
from .voice import BELL_VOICE_CLIPS


def cache_directory(root, identity):
    key = sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()[:16]
    return root/f'bell-{key}'


def v2_identity(identity):
    # 仅已知配方之间允许直接转换；未来算法版本必须重新决定兼容性
    if identity['processing_version'] != 3:
        return None
    previous = dict(identity, processing_version=2)
    previous.pop('linear_gain')
    return previous


def read_cache(root, identity):
    try:
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or manifest.get('cache_identity') != identity:
            return None
        if 'linear_gain' in identity:
            if (manifest.get('linear_gain') != identity['linear_gain']
                    or manifest.get('processing_version') != identity['processing_version']):
                return None
        elif manifest.get('linear_gain', 1.) != 1. or manifest.get('processing_version', 2) != 2:
            # 不猜测未知处理过的音频，避免重复衰减
            return None
        entries = {entry['clip_id']: entry for entry in manifest['clips']}
        if len(manifest['clips']) != len(BELL_VOICE_CLIPS) or set(entries) != {c.clip_id for c in BELL_VOICE_CLIPS}:
            return None
        for clip in BELL_VOICE_CLIPS:
            entry = entries[clip.clip_id]
            if entry['file'] != clip.filename:
                return None
            data = (root/clip.filename).read_bytes()
            if sha256(data).hexdigest() != entry['sha256']:
                return None
            with wave.open(io.BytesIO(data), 'rb') as audio:
                rate = audio.getframerate()
                frames = round(clip.end*rate)-round(clip.start*rate)
                if (rate <= 0 or frames <= 0 or audio.getnchannels() != 2 or audio.getsampwidth() != 2
                        or audio.getnframes() != frames or entry['frames'] != frames
                        or len(audio.readframes(frames)) != frames*4):
                    return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError, EOFError, wave.Error):
        return None


def cache_ready(root, identity):
    return read_cache(root, identity) is not None


def upgrade_v2_cache(cache_root, identity, output, *, legacy_root=None):
    previous = v2_identity(identity)
    if previous is None:
        return None
    root = legacy_root if legacy_root is not None else cache_directory(cache_root, previous)
    manifest = read_cache(root, previous)
    if manifest is None:
        return None
    output.mkdir(parents=True, exist_ok=True)
    entries = {entry['clip_id']: entry for entry in manifest['clips']}
    for clip in BELL_VOICE_CLIPS:
        data = (root/clip.filename).read_bytes()
        if sha256(data).hexdigest() != entries[clip.clip_id]['sha256']:
            raise VoiceAssetError('Bell v2 cache changed during upgrade')
        with wave.open(io.BytesIO(data), 'rb') as audio:
            params = audio.getparams()
            frames = apply_pcm_gain(audio.readframes(params.nframes), identity['linear_gain'])
        with wave.open(str(output/clip.filename), 'wb') as audio:
            audio.setparams(params)
            audio.writeframes(frames)
    manifest.update(processing_version=identity['processing_version'], linear_gain=identity['linear_gain'],
        gain_db=20*math.log10(identity['linear_gain']),
        upgraded_from=dict(processing_version=2, directory=str(root.resolve())),
        note='从来源匹配且校验完整的 v2 缓存应用一次 linear_gain；旧文件保持不变')
    return manifest
