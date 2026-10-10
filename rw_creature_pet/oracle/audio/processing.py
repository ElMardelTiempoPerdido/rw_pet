"""Bell 语音的共用准备算法；初始化和离线工具使用同一份实现。"""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import wave

from .voice import BELL_VOICE_CLIPS, BELL_VOICE_SOURCES

# 修改处理算法或抵消参数时递增，避免沿用旧缓存。
PROCESSING_VERSION = 2
SPLIT_FADE_SECONDS = .005


def cut_clips(source, output):
    source, output = Path(source), Path(output)
    with wave.open(str(source), 'rb') as audio:
        params = audio.getparams()
        if params.nframes/params.framerate < max(clip.end for clip in BELL_VOICE_SOURCES):
            raise ValueError('完整采访长度不足，无法按字幕时间裁剪')
        output.mkdir(parents=True, exist_ok=True)
        entries = []
        for clip in BELL_VOICE_SOURCES:
            start = round(clip.start*params.framerate)
            end = round(clip.end*params.framerate)
            audio.setpos(start)
            frames = audio.readframes(end-start)
            with wave.open(str(output/clip.filename), 'wb') as part:
                part.setparams(params)
                part.writeframes(frames)
            entries.append(dict(clip_id=clip.clip_id, file=clip.filename,
                start_seconds=clip.start, end_seconds=clip.end,
                duration_seconds=(end-start)/params.framerate, frames=end-start))
    manifest = dict(source=str(source.resolve()), source_sha256=sha256(source.read_bytes()).hexdigest(),
        sample_rate=params.framerate, channels=params.nchannels, sample_width=params.sampwidth,
        note='按字幕时间直接切分，保留原始双声道采样。抢话期间的主持人声音尚未分离。',
        clips=entries)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest

def prepare_clips(source, output):
    # 仅缓存首次生成时加载 NumPy；日常播放不执行声道处理。
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

    # 先按五段原片段处理，不能在每个短片段开头重新抵消主持人。
    host, bell = balance(9., 13.8), balance(6.2, 8.1)
    if abs(bell-host) < .05:
        raise ValueError('两个声音的声道分布过于接近，不适合此抵消方法')
    manifest = cut_clips(source, output/'raw')
    prepared = output/'source-clips'
    prepared.mkdir(exist_ok=True)
    for clip in manifest['clips']:
        raw = output/'raw'/clip['file']
        target = prepared/clip['file']
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

    manifest['source_clips'] = manifest.pop('clips')
    sources = {clip.clip_id: clip for clip in BELL_VOICE_SOURCES}
    entries = []
    for clip in BELL_VOICE_CLIPS:
        original = sources[clip.source_id]
        # 使用同一套绝对采样边界，避免分别四舍五入导致丢帧或重复帧。
        origin = round(original.start*rate)
        start, end = round(clip.start*rate)-origin, round(clip.end*rate)-origin
        fade_in = SPLIT_FADE_SECONDS if clip.start > original.start else 0.
        fade_out = SPLIT_FADE_SECONDS if clip.end < original.end else 0.
        with wave.open(str(prepared/original.filename), 'rb') as audio:
            part_params = audio.getparams()
            audio.setpos(start)
            frames = audio.readframes(end-start)
        if fade_in or fade_out:
            samples = np.frombuffer(frames, dtype='<i2').reshape(-1, 2).astype(np.float64)
            n = min(len(samples)//2, max(2, round(SPLIT_FADE_SECONDS*rate)))
            if n:
                ramp = np.linspace(0., 1., n)[:, None]
                if fade_in:
                    samples[:n] *= ramp
                if fade_out:
                    samples[-n:] *= ramp[::-1]
            frames = np.rint(samples).astype('<i2').tobytes()
        with wave.open(str(output/clip.filename), 'wb') as audio:
            audio.setparams(part_params)
            audio.writeframes(frames)
        entries.append(dict(clip_id=clip.clip_id, file=clip.filename,
            start_seconds=clip.start, end_seconds=clip.end,
            duration_seconds=(end-start)/rate, frames=end-start,
            source_clip_id=clip.source_id,
            source_offset_seconds=round(clip.start-original.start, 6),
            edge_fade_seconds=dict(start=fade_in, end=fade_out)))
    manifest.update(clips=entries,
        note='先保留五段已试听的声道处理，再按确认停顿切成十段。raw/ 为原始裁剪，'
             'source-clips/ 为处理后的五段；外层 WAV 用于播放，仅新增切口淡入淡出 5 ms。',
        host_right_to_left=host, bell_right_to_left=bell,
        host_reference_seconds=[9., 13.8], bell_reference_seconds=[6.2, 8.1])
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest
