"""首次从本机游戏准备 Bell 语音；后续启动只校验并使用用户缓存。"""
import gc
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import wave

from .voice import BELL_VOICE_CLIPS, bell_voice_paths
from .voice_processing import PROCESSING_VERSION, prepare_clips


class VoiceAssetError(RuntimeError):
    pass


LEGACY_DIRECTORY = 'artifacts/oracle-voice-reference/bell-clips'


def _valid_interview(source):
    try:
        with wave.open(source, 'rb') as audio:
            return (audio.getnchannels() == 2 and audio.getsampwidth() == 2
                    and audio.getnframes()/audio.getframerate() >= max(c.end for c in BELL_VOICE_CLIPS)
                    and len(audio.readframes(audio.getnframes())) == audio.getnframes()*4)
    except (OSError, ValueError, EOFError, wave.Error):
        return False


def _find_source(game_dir):
    streaming = Path(game_dir)/'RainWorld_Data/StreamingAssets'
    loose = streaming/'loadedsoundeffects/RWTW_ATalkShow.wav'
    # 某些游戏版本的散装同名文件为 0 字节占位，真正的录音在 AssetBundle 中。
    if loose.is_file() and _valid_interview(str(loose)):
        return loose, 'wav'
    bundle = streaming/'AssetBundles/loadedsoundeffects'
    if bundle.is_file() and bundle.stat().st_size:
        return bundle, 'bundle'
    raise VoiceAssetError(f'找不到 Bell 采访音频：{streaming}；请检查 game_dir 和游戏内容安装情况')


def _extract_interview(source, kind):
    if kind == 'wav':
        data = source.read_bytes()
    else:
        import UnityPy
        environment = UnityPy.load(str(source))
        target = next((obj for name, obj in environment.container.items()
                       if name.replace('\\', '/').rsplit('/', 1)[-1].casefold() == 'rwtw_atalkshow.wav'), None)
        if target is None:
            # 兼容没有 container 路径映射的导出格式，只读取 AudioClip 元数据。
            for obj in environment.objects:
                if obj.type.name == 'AudioClip' and (obj.peek_name() or '').casefold() == 'rwtw_atalkshow':
                    target = obj
                    break
        if target is None:
            raise VoiceAssetError('游戏音效包中没有 RWTW_ATalkShow；请确认安装了包含此采访的游戏内容')
        samples = target.read().samples
        if len(samples) != 1:
            raise VoiceAssetError('Bell 采访导出结果不是一段完整录音，无法使用当前切分参数')
        data = next(iter(samples.values()))
    if not _valid_interview(io.BytesIO(data)):
        raise VoiceAssetError('Bell 采访不是足够长的双声道 16 位 PCM WAV，无法使用当前处理参数')
    return data


def _cache_ready(root, identity):
    try:
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or manifest.get('cache_identity') != identity:
            return False
        entries = {entry['clip_id']: entry for entry in manifest['clips']}
        for clip in BELL_VOICE_CLIPS:
            data = (root/clip.filename).read_bytes()
            if sha256(data).hexdigest() != entries[clip.clip_id]['sha256']:
                return False
            with wave.open(io.BytesIO(data), 'rb') as audio:
                rate = audio.getframerate()
                frames = round(clip.end*rate)-round(clip.start*rate)
                if (audio.getnchannels() != 2 or audio.getsampwidth() != 2
                        or audio.getnframes() != frames or len(audio.readframes(frames)) != frames*4):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, EOFError, wave.Error):
        return False


def ensure_bell_voice(game_dir, *, cache_root=None):
    """返回完整缓存目录。版本/源文件变化、半写入或损坏缓存都会重新生成。"""
    try:
        source, kind = _find_source(game_dir)
        stat = source.stat()
        identity = dict(source=str(source.resolve()), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                        kind=kind, processing_version=PROCESSING_VERSION,
                        clips=[[c.clip_id, c.start, c.end] for c in BELL_VOICE_CLIPS])
        key = sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()[:16]
        cache_root = (Path(cache_root) if cache_root is not None else
                      Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))/'rw_creature_pet/voices')
        root = cache_root/f'bell-{key}'
        if _cache_ready(root, identity):
            return root
        # 多个窗口/进程同时冷启动时，只有一个生成者；提交 manifest 前不公布完整缓存。
        from PySide6.QtCore import QLockFile
        cache_root.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(root)+'.lock')
        lock.setStaleLockTime(120000)
        if not lock.tryLock(60000):
            raise VoiceAssetError('等待 Bell 语音缓存初始化超时，请稍后重新启动')
        try:
            if _cache_ready(root, identity):
                return root
            with TemporaryDirectory(prefix='bell-prepare-', dir=cache_root) as temporary:
                temp = Path(temporary)
                try:
                    full = _extract_interview(source, kind)
                finally:
                    # UnityPy 的对象图存在循环引用，冷启动后立即释放较大的音效包。
                    gc.collect()
                wav = temp/'RWTW_ATalkShow.wav'
                wav.write_bytes(full)
                del full
                output = temp/'clips'
                manifest = prepare_clips(wav, output)
                manifest.update(cache_identity=identity, source=str(source.resolve()),
                                source_asset='RWTW_ATalkShow')
                for clip in manifest['clips']:
                    clip['sha256'] = sha256((output/clip['file']).read_bytes()).hexdigest()
                (output/'manifest.json').write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                if not _cache_ready(output, identity):
                    raise VoiceAssetError('新生成的 Bell 语音未通过完整性校验')
                # 不缓存整个音效包或完整采访；只保留日常播放需要的十段音频。
                root.mkdir(parents=True, exist_ok=True)
                for clip in BELL_VOICE_CLIPS:
                    (output/clip.filename).replace(root/clip.filename)
                (output/'manifest.json').replace(root/'manifest.json')
            return root
        finally:
            lock.unlock()
    except VoiceAssetError:
        raise
    except Exception as exc:
        raise VoiceAssetError(f'准备 Bell 语音失败：{exc}') from exc


def make_bell_voice_player(config, config_path=None, parent=None, *, initialize=True, source=None):
    """桌面/调试共用入口；初始化失败只禁用语音，不妨碍桌宠其他功能。"""
    from ..interaction.audio import VoicePlayer
    if source is not None:
        return VoicePlayer(source.clips, config.audio, parent, asset_error=source.asset_error)
    paths, error = {}, ''
    try:
        directory = config.oracle.voice_directory
        if directory != 'auto':
            paths = bell_voice_paths(config.oracle, config_path)
            missing = [str(path) for path in paths.values() if not path.is_file()]
            if not missing:
                return VoicePlayer(paths, config.audio, parent)
            if directory.replace('\\', '/') != LEGACY_DIRECTORY:
                raise VoiceAssetError('自定义语音目录缺少文件：'+', '.join(missing))
            # 兼容旧 TOML：迁移设备后旧 artifacts 不存在时自动从游戏准备。
        if not initialize:
            raise VoiceAssetError('几何预览未初始化语音；请通过正常启动入口准备游戏资源')
        root = ensure_bell_voice(config.game_dir)
        paths = {clip.clip_id: root/clip.filename for clip in BELL_VOICE_CLIPS}
    except VoiceAssetError as exc:
        error = str(exc)
    return VoicePlayer(paths, config.audio, parent, asset_error=error)
