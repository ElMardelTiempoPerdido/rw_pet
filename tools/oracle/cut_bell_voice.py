"""从已导出的完整采访 WAV 按字幕时间裁切；不混音、不消除主持人声音。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rw_creature_pet.oracle.voice_processing import cut_clips


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
