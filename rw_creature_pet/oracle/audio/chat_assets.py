"""Moon / Pebbles Chat 与 Prince Talk 提取缓存；每次准备最多解包一次"""
import gc
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import wave

from .errors import VoiceAssetError
from .voice import GAME_VOICE_CLIPS


CACHE_VERSION = 1


def wav_info(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if (channels not in (1, 2) or width != 2 or rate <= 0 or frames <= 0
                    or len(audio.readframes(frames)) != frames*channels*width):
                raise ValueError('invalid PCM')
            return dict(frames=frames, rate=rate, channels=channels, duration_seconds=frames/rate)
    except (OSError, ValueError, EOFError, wave.Error) as exc:
        raise VoiceAssetError('语音文件不是完整的 16 位 PCM WAV') from exc


def _sources(game_dir, clips):
    streaming = Path(game_dir)/'RainWorld_Data/StreamingAssets'
    bundle = streaming/'AssetBundles/loadedsoundeffects'
    sources = {}
    for clip in clips:
        loose = streaming/'loadedsoundeffects'/f'{clip.asset_name}.wav'
        try:
            wav_info(loose.read_bytes())
            sources[clip.clip_id] = (loose, 'wav')
        except (OSError, VoiceAssetError):
            if not bundle.is_file() or not bundle.stat().st_size:
                raise VoiceAssetError(f'找不到语音 {clip.asset_name}：{streaming}')
            sources[clip.clip_id] = (bundle, 'bundle')
    return sources


def _identity(voice, sources):
    files = {}
    for clip_id, (path, kind) in sources.items():
        stat = path.stat()
        files[clip_id] = dict(path=str(path.resolve()), kind=kind, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return dict(version=CACHE_VERSION, voice=voice, sources=files,
                assets=[c.asset_name for c in GAME_VOICE_CLIPS[voice]])


def _cache_ready(root, identity, clips):
    try:
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or manifest.get('cache_identity') != identity:
            return False
        entries = {entry['clip_id']: entry for entry in manifest['clips']}
        for clip in clips:
            data = (root/clip.filename).read_bytes()
            if sha256(data).hexdigest() != entries[clip.clip_id]['sha256']:
                return False
            if wav_info(data)['frames'] != entries[clip.clip_id]['frames']:
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, VoiceAssetError):
        return False


def _bundle_data(environment, name):
    target = next((obj for path, obj in environment.container.items()
                   if path.replace('\\', '/').rsplit('/', 1)[-1].casefold() == name.casefold()+'.wav'), None)
    if target is None:
        target = next((obj for obj in environment.objects if obj.type.name == 'AudioClip'
                       and (obj.peek_name() or '').casefold() == name.casefold()), None)
    if target is None:
        raise VoiceAssetError(f'游戏音效包中缺少语音：{name}')
    samples = target.read().samples
    if len(samples) != 1:
        raise VoiceAssetError(f'语音 {name} 不是单段音频')
    data = next(iter(samples.values()))
    wav_info(data)
    return data


def _prepare(voice, sources, identity, cache_root, environments):
    clips = GAME_VOICE_CLIPS[voice]
    key = sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()[:16]
    root = cache_root/f'{voice}-{key}'
    if not _cache_ready(root, identity, clips):
        from PySide6.QtCore import QLockFile
        cache_root.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(root)+'.lock')
        lock.setStaleLockTime(120000)
        if not lock.tryLock(60000):
            raise VoiceAssetError(f'等待 {voice} 语音缓存初始化超时，请稍后重新检查资源')
        try:
            if not _cache_ready(root, identity, clips):
                with TemporaryDirectory(prefix=f'{voice}-prepare-', dir=cache_root) as temp:
                    output = Path(temp)
                    entries = []
                    for clip in clips:
                        source, kind = sources[clip.clip_id]
                        if kind == 'wav':
                            data = source.read_bytes()
                        else:
                            if source not in environments:
                                import UnityPy
                                environments[source] = UnityPy.load(str(source))
                            data = _bundle_data(environments[source], clip.asset_name)
                        info = wav_info(data)
                        (output/clip.filename).write_bytes(data)
                        entries.append(dict(clip_id=clip.clip_id, file=clip.filename, asset=clip.asset_name,
                                            sha256=sha256(data).hexdigest(), **info))
                    manifest = dict(cache_identity=identity, clips=entries)
                    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n',
                                                        encoding='utf-8')
                    if not _cache_ready(output, identity, clips):
                        raise VoiceAssetError(f'{voice} 语音缓存校验失败')
                    root.mkdir(parents=True, exist_ok=True)
                    for clip in clips:
                        (output/clip.filename).replace(root/clip.filename)
                    (output/'manifest.json').replace(root/'manifest.json')
        finally:
            lock.unlock()
    return {c.clip_id: root/c.filename for c in clips}


def prepare_chat_voices(game_dir, voices=tuple(GAME_VOICE_CLIPS), *, cache_root=None):
    """分别报告每套语音结果；其中一套缺失不影响其他语音"""
    cache_root = (Path(cache_root) if cache_root is not None else
                  Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))/'rw_creature_pet/voices')
    results, environments = {}, {}
    try:
        for voice in voices:
            try:
                sources = _sources(game_dir, GAME_VOICE_CLIPS[voice])
                paths = _prepare(voice, sources, _identity(voice, sources), cache_root, environments)
                results[voice] = paths, ''
            except Exception as exc:
                results[voice] = {}, str(exc)
    finally:
        if environments:
            environments.clear()
            gc.collect()
    return results
