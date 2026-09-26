"""从已导出的完整采访 WAV 按字幕时间裁切；不混音、不消除主持人声音。"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rw_creature_pet.oracle.voice import BELL_VOICE_CLIPS


def cut_clips(source, output):
    source, output = Path(source), Path(output)
    with wave.open(str(source), 'rb') as audio:
        params = audio.getparams()
        if params.nframes/params.framerate < max(clip.end for clip in BELL_VOICE_CLIPS):
            raise ValueError('完整采访长度不足，无法按字幕时间裁剪')
        output.mkdir(parents=True, exist_ok=True)
        entries = []
        for clip in BELL_VOICE_CLIPS:
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
        note='按字幕时间直接切分，保留原始双声道采样。抢话期间的主持人声音尚未分离；应用当前不播放。',
        clips=entries)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'artifacts/oracle-voice-reference/RWTW_ATalkShow.wav')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/oracle-voice-reference/bell-clips')
    args = parser.parse_args()
    manifest = cut_clips(args.source, args.output)
    for clip in manifest['clips']:
        print(f"{clip['file']}: {clip['start_seconds']:.2f}-{clip['end_seconds']:.2f}s ({clip['duration_seconds']:.2f}s)")
    print(args.output.resolve())


if __name__ == '__main__':
    main()
