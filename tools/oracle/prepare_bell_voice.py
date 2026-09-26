"""离线准备 Bell 语音：与自动初始化共用切分及 04/05 开头的声道抵消算法。"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rw_creature_pet.oracle.voice_processing import prepare_clips


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'artifacts/oracle-voice-reference/RWTW_ATalkShow.wav')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/oracle-voice-reference/bell-clips-split')
    args = parser.parse_args()
    result = prepare_clips(args.source, args.output)
    for clip in result['clips']:
        print(clip['file'], clip['duration_seconds'], clip['edge_fade_seconds'])


if __name__ == '__main__':
    main()
