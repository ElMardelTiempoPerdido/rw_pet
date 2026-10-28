"""开发工具：从本机游戏或已有缓存生成随包分发的珍珠动画曲线，不输出音频"""
import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rw_creature_pet.oracle.pearls.playback import SpectrumCurve
from rw_creature_pet.oracle.pearls.playback_assets import CURVE_ROOT, FORMAT_VERSION
from rw_creature_pet.shared.paths import DEFAULT_GAME_DIR

TRACK_NAME = 'RW_121 - Soft Gesture'
PROCESSING_VERSION = 1
CURVE_RATE = 40
FFT_SIZE = 2048  # 实数 FFT 的前 1024 个频段，对应 HalcyonPearl 的数组长度。


def decode_source(source):
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



def export_curve(output, *, game_dir=DEFAULT_GAME_DIR, cache=None):
    import numpy as np
    if cache is None:
        source = Path(game_dir)/'RainWorld_Data/StreamingAssets/AssetBundles/music_songs'
        curve, metadata = precompute_strength(decode_source(source))
        stream = io.BytesIO()
        np.save(stream, np.asarray(curve.values, dtype='<f4'), allow_pickle=False)
        raw = stream.getvalue()
    else:
        cache = Path(cache)
        metadata = json.loads((cache/'manifest.json').read_text(encoding='utf-8'))
        raw = (cache/'strength.npy').read_bytes()
        if (sha256(raw).hexdigest() != metadata['sha256']
                or metadata['track'] != TRACK_NAME
                or metadata['identity']['processing_version'] != PROCESSING_VERSION):
            raise ValueError('缓存来源、算法版本或校验和不匹配')
        values = np.load(io.BytesIO(raw), allow_pickle=False)
        if values.ndim != 1 or values.dtype != np.dtype('<f4') or len(values) != metadata['samples']:
            raise ValueError('无效的缓存强度数组')
        SpectrumCurve(tuple(map(float, values)), metadata['duration'], metadata['curve_rate'])
    # 仅保留算法和曲线信息，不发布用户安装路径、文件时间或原始音频
    fields = ('track', 'duration', 'sample_rate', 'channels', 'curve_rate', 'fft_size', 'window',
              'channel', 'normalization', 'samples', 'minimum', 'maximum', 'mean', 'saturated_fraction')
    manifest = {key: metadata[key] for key in fields}
    manifest.update(format_version=FORMAT_VERSION, processing_version=PROCESSING_VERSION,
                    sha256=sha256(raw).hexdigest())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'strength.npy').write_bytes(raw)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n',
                                       encoding='utf-8', newline='\n')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--game-dir', type=Path, default=DEFAULT_GAME_DIR)
    source.add_argument('--from-cache', type=Path, help='复用旧版已验证的曲线缓存，不重新解码')
    parser.add_argument('--output', type=Path, default=CURVE_ROOT)
    args = parser.parse_args()
    print(export_curve(args.output, game_dir=args.game_dir, cache=args.from_cache))


if __name__ == '__main__':
    main()
