"""离线准备 Bell 试听候选：时间裁剪，以及 04/05 开头的加权声道抵消。"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.oracle.cut_bell_voice import cut_clips


def prepare_clips(source, output):
    # 只在离线工具中使用 NumPy，桌宠运行时不加载音频或执行抵消。
    import numpy as np

    source, output = Path(source), Path(output)
    with wave.open(str(source), 'rb') as audio:
        params = audio.getparams()
        if params.nchannels != 2 or params.sampwidth != 2:
            raise ValueError('声道抵消需要双声道 16 位 PCM WAV')
        full = np.frombuffer(audio.readframes(params.nframes), dtype='<i2').reshape(-1, 2).astype(np.float64)
    rate = params.framerate

    def balance(start, end):
        left, right = full[round(start*rate):round(end*rate)].T
        power = left@left
        if power <= 0:
            raise ValueError('参考片段为空或静音，无法计算声道比例')
        return float(left@right/power)

    # 与首轮已试听版本使用相同参考片段和算法；只更改 04 的时间范围。
    host, bell = balance(9., 13.8), balance(6.2, 8.1)
    if abs(bell-host) < .05:
        raise ValueError('两个声音的声道分布过于接近，不适合此抵消方法')
    manifest = cut_clips(source, output/'raw')
    for clip in manifest['clips']:
        raw = output/'raw'/clip['file']
        target = output/clip['file']
        if clip['clip_id'] not in ('bell_04', 'bell_05'):
            shutil.copyfile(raw, target)
            clip['processing'] = None
            continue
        with wave.open(str(raw), 'rb') as audio:
            part_params = audio.getparams()
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').reshape(-1, 2).astype(np.float64)
        hold = 1.5 if clip['clip_id'] == 'bell_04' else .5
        end = hold+.2
        n = min(len(samples), round(end*rate))
        segment = samples[:n].copy()
        estimate = (segment[:, 1]-host*segment[:, 0])/(bell-host)
        separated = np.column_stack((estimate, estimate*bell))
        t = np.arange(n)/rate
        blend = np.clip((end-t)/.2, 0, 1)
        blend = blend*blend*(3-2*blend)
        samples[:n] = segment*(1-blend[:, None])+separated*blend[:, None]
        if np.any(np.abs(samples) > 32767):
            raise ValueError(f"{clip['file']} 抵消后会削波，需要调整增益")
        with wave.open(str(target), 'wb') as audio:
            audio.setparams(part_params)
            audio.writeframes(np.rint(samples).astype('<i2').tobytes())
        clip['processing'] = dict(method='weighted_stereo_cancellation',
            full_until_seconds=hold, crossfade_until_seconds=end)
    manifest.update(note='离线处理候选，应用当前不播放。原始裁剪留在 raw/；04/05 只处理开头，交叉淡化后保留原音。',
        host_right_to_left=host, bell_right_to_left=bell,
        host_reference_seconds=[9., 13.8], bell_reference_seconds=[6.2, 8.1])
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'artifacts/oracle-voice-reference/RWTW_ATalkShow.wav')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/oracle-voice-reference/bell-clips')
    args = parser.parse_args()
    result = prepare_clips(args.source, args.output)
    for clip in result['clips']:
        print(clip['file'], clip['duration_seconds'], clip['processing'])


if __name__ == '__main__':
    main()
