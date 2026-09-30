"""从本机 Soft Gesture 预计算音乐强度；缓存仅保存曲线，不保存/播放音乐。"""
from hashlib import sha256
import gc
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import wave

from .pearl_playback import SpectrumCurve

TRACK_NAME = 'RW_121 - Soft Gesture'
PROCESSING_VERSION = 1
CURVE_RATE = 40
FFT_SIZE = 2048  # 实数 FFT 的前 1024 个频段，对应 HalcyonPearl 的数组长度。


def _decode_source(source):
    import UnityPy
    from UnityPy.helpers.ResourceReader import get_resource_data
    from fmod_toolkit.fmod import pyfmodex, sound_to_wav

    environment = UnityPy.load(str(source))
    target = next((obj for path, obj in environment.container.items()
                   if path.replace('\\', '/').rsplit('/', 1)[-1].casefold()
                   == (TRACK_NAME+'.mp3').casefold()), None)
    if target is None:
        target = next((obj for obj in environment.objects if obj.type.name == 'AudioClip'
                       and (obj.peek_name() or '').casefold() == TRACK_NAME.casefold()), None)
    if target is None:
        raise ValueError('music_songs 中找不到 Soft Gesture')
    clip = target.read()
    if clip.m_AudioData:
        raw = bytes(clip.m_AudioData)
    else:
        resource = clip.m_Resource
        raw = get_resource_data(resource.m_Source, clip.object_reader.assets_file,
                                resource.m_Offset, resource.m_Size)
    # 独立无声输出系统，仅 create_sound/read 数据；不创建播放 channel，
    # 不复用语音播放器或 fmod_toolkit 的默认输出系统。
    system = pyfmodex.System()
    sound = None
    try:
        system.output = pyfmodex.enums.OUTPUTTYPE.NOSOUND_NRT
        system.init(1, pyfmodex.flags.INIT_FLAGS.NORMAL, None)
        sound = system.create_sound(bytes(raw), pyfmodex.flags.MODE.OPENMEMORY,
            exinfo=pyfmodex.structure_declarations.CREATESOUNDEXINFO(
                length=len(raw), numchannels=clip.m_Channels, defaultfrequency=clip.m_Frequency))
        samples = sound_to_wav(sound, TRACK_NAME)
        if len(samples) != 1:
            raise ValueError('Soft Gesture 音频不是单一曲目')
        return next(iter(samples.values()))
    finally:
        if sound is not None:
            sound.release()
        system.release()


def precompute_strength(wav_data):
    import numpy as np
    with wave.open(io.BytesIO(wav_data), 'rb') as audio:
        channels, sample_rate, frames = audio.getnchannels(), audio.getframerate(), audio.getnframes()
        if audio.getsampwidth() != 2 or channels < 1 or frames == 0:
            raise ValueError('需要非空的 16 位 PCM 音频')
        pcm = audio.readframes(frames)
        if len(pcm) != frames*channels*2:
            raise ValueError('音频数据不完整')
    # 原版 GetSpectrumData(channel=0)，不混合左右声道，以免反相抵消。
    mono = np.frombuffer(pcm, dtype='<i2').reshape(-1, channels)[:, 0].astype(np.float32)/32768.
    padded = np.pad(mono, (FFT_SIZE//2, FFT_SIZE//2))
    window = np.hamming(FFT_SIZE)
    duration = frames/sample_rate
    count = int(np.ceil(duration*CURVE_RATE))
    strengths = np.empty(count, dtype='<f4')
    for i in range(count):
        offset = round(i*sample_rate/CURVE_RATE)
        spectrum = np.abs(np.fft.rfft(padded[offset:offset+FFT_SIZE]*window))[:FFT_SIZE//2]/FFT_SIZE
        strengths[i] = np.clip(spectrum.sum()/.25, 0., 1.)
    metadata = dict(track=TRACK_NAME, duration=duration, sample_rate=sample_rate, channels=channels,
                    curve_rate=CURVE_RATE, fft_size=FFT_SIZE, window='Hamming', channel=0,
                    normalization='abs(rfft)/2048; clamp(sum/0.25, 0, 1)',
                    samples=count, minimum=float(strengths.min()), maximum=float(strengths.max()),
                    mean=float(strengths.mean()), saturated_fraction=float((strengths >= 1).mean()))
    return SpectrumCurve(tuple(map(float, strengths)), duration, CURVE_RATE), metadata


def _read_cache(root, identity):
    import numpy as np
    try:
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        raw = (root/'strength.npy').read_bytes()
        if manifest['identity'] != identity or sha256(raw).hexdigest() != manifest['sha256']:
            return None
        values = np.load(io.BytesIO(raw), allow_pickle=False)
        if values.ndim != 1 or values.dtype != np.dtype('<f4'):
            return None
        return SpectrumCurve(tuple(map(float, values)), manifest['duration'], manifest['curve_rate'])
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        return None


def load_pearl_playback(game_dir, *, cache_root=None):
    source = Path(game_dir)/'RainWorld_Data/StreamingAssets/AssetBundles/music_songs'
    stat = source.stat()
    identity = dict(source=str(source.resolve()), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                    track=TRACK_NAME, processing_version=PROCESSING_VERSION)
    key = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    base = (Path(cache_root) if cache_root is not None else
            Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))/'rw_creature_pet/pearl-playback')
    root = base/key
    cached = _read_cache(root, identity)
    if cached is not None:
        return cached, root
    from PySide6.QtCore import QLockFile
    base.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root)+'.lock')
    lock.setStaleLockTime(120000)
    if not lock.tryLock(60000):
        raise RuntimeError('等待珍珠动画曲线初始化超时')
    try:
        cached = _read_cache(root, identity)
        if cached is not None:
            return cached, root
        try:
            curve, metadata = precompute_strength(_decode_source(source))
        finally:
            gc.collect()  # UnityPy 的资源对象存在环引用，冷启动后及时释放大音乐包。
        import numpy as np
        root.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=root) as temp:
            temp = Path(temp)
            np.save(temp/'strength.npy', np.asarray(curve.values, dtype='<f4'), allow_pickle=False)
            metadata.update(identity=identity, sha256=sha256((temp/'strength.npy').read_bytes()).hexdigest())
            (temp/'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            for name in ('strength.npy', 'manifest.json'):
                (temp/name).replace(root/name)
        return curve, root
    finally:
        lock.unlock()


def prepare_pearl_playback(game_dir, renderer):
    """资源缺失时保留普通阅读；错误通过现有资源状态显示。"""
    try:
        renderer.playback_curve, _ = load_pearl_playback(game_dir)
        return ''
    except Exception as exc:
        renderer.playback_curve = None
        return f'珍珠播放动画不可用：{exc}'
