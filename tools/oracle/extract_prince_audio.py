"""从本机游戏解包 Prince 对话及直接相关音效，输出到同一个离线试听目录"""
import argparse
from collections import Counter
import gc
from hashlib import sha256
import io
import json
from pathlib import Path
import wave


ROOT = Path(__file__).resolve().parents[2]
GROUPS = (
    ('voice', '语音', 'Prince_Talk', '字幕切换为新的非省略号消息时随机播放，受击回复也使用此组',
     'Watcher/PrinceBehavior.cs:374-377,873-888', 'sounds.txt 触发器音量 0.4'),
    ('movement', '移动', 'Prince_Arm_Move_LOOP', 'Prince 茎部移动循环，音量和音调随身体速度变化',
     'Watcher/PrinceStem.cs:302-319', '素材音量 0.4；运行时音调约 0.5-1.0'),
    ('joint', '关节', 'Prince_Arm_Joint', '关节速度达到阈值时随机播放，间隔 20-79 个逻辑帧',
     'Watcher/PrinceStem.cs:334-354', 'sounds.txt 触发器音量 0.5'),
    ('mark', '印记', 'SS_AI_Give_The_Mark_Boom', 'Prince 赋予印记时的爆发音，与迭代器共用',
     'Watcher/PrinceBehavior.cs:538', '素材音量 0.8'),
    ('related', '场景提示', 'DaemonHintPrince', 'WRSA_J01 房间的 Prince 路线提示循环，不是人偶说话',
     'Watcher/WatcherRoomSpecificScript.cs:2199-2200', '触发器音量 0.5，另有距离范围配置'),
)


def sound_entries(sounds_path):
    lines = sounds_path.read_text(encoding='utf-8-sig').splitlines()
    entries = []
    for category, label, sound_id, purpose, reference, mix in GROUPS:
        matches = [(i, line) for i, line in enumerate(lines, 1)
                   if line.split(' : ', 1)[0].split('/', 1)[0] == sound_id]
        if len(matches) != 1:
            raise ValueError(f'{sound_id} 的 sounds.txt 定义不唯一或缺失')
        line_number, definition = matches[0]
        for item in definition.split(' : ', 1)[1].split(','):
            asset = item.strip().split('/', 1)[0]
            entries.append(dict(category=category, label=label, sound_id=sound_id, asset=asset,
                                purpose=purpose, code_reference=reference, game_mix=mix,
                                sound_definition=definition, sound_line=line_number,
                                bundle='loadedsoundeffects', suffix='.wav'))
    # 通过环境循环加载，不经过 sounds.txt 的 SoundID 映射
    entries.append(dict(category='mark', label='印记环境', sound_id=None, asset='RWTW_Sigil',
                        purpose='Prince 赋予印记期间的持续环境声',
                        code_reference='Watcher/PrinceBehavior.cs:485-502,622',
                        game_mix='音量随印记进度在 0-0.65 内变化', sound_definition=None, sound_line=None,
                        bundle='loadedsoundeffects_ambient', suffix='.ogg'))
    order = {name: i for i, name in enumerate(('voice', 'movement', 'joint', 'mark', 'related'))}
    return sorted(entries, key=lambda item: (order[item['category']], item['asset'].casefold()))


def wav_info(data):
    with wave.open(io.BytesIO(data), 'rb') as audio:
        frames, rate = audio.getnframes(), audio.getframerate()
        channels, width = audio.getnchannels(), audio.getsampwidth()
        pcm = audio.readframes(frames)
        if rate <= 0 or frames <= 0 or len(pcm) != frames*channels*width:
            raise ValueError('解码后的 WAV 数据不完整')
        return dict(frames=frames, sample_rate=rate, channels=channels, sample_width=width,
                    duration_seconds=frames/rate, sha256=sha256(data).hexdigest())


def write_clip(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f'试听文件已被修改，保留现有文件：{path}')
        return
    path.write_bytes(data)


def extract(game_dir, output):
    import UnityPy
    streaming = game_dir/'RainWorld_Data/StreamingAssets'
    sounds = streaming/'soundeffects/sounds.txt'
    entries = sound_entries(sounds)
    output.mkdir(parents=True, exist_ok=True)
    for i, entry in enumerate(entries, 1):
        entry['file'] = f"{i:02}_{entry['label']}_{entry['asset']}.wav"
    bundle_inventories = {}
    for bundle in dict.fromkeys(entry['bundle'] for entry in entries):
        source = streaming/'AssetBundles'/bundle
        print(f'Loading {source.name}', flush=True)
        environment = UnityPy.load(str(source))
        try:
            by_filename = {Path(name.replace('\\', '/')).name.casefold(): (name, obj)
                           for name, obj in environment.container.items()}
            bundle_inventories[bundle] = sorted(name for name in by_filename if 'prince' in name)
            for entry in entries:
                if entry['bundle'] != bundle:
                    continue
                key = (entry['asset']+entry['suffix']).casefold()
                if key not in by_filename:
                    raise ValueError(f'资源包内未找到 {key}')
                container_path, obj = by_filename[key]
                clip = obj.read()
                samples = clip.samples
                if len(samples) != 1:
                    raise ValueError(f'{key} 未解码成单个音频片段')
                data = next(iter(samples.values()))
                info = wav_info(data)
                write_clip(output/entry['file'], data)
                entry.update(info, source_bundle=str(source), source_container=container_path,
                             unity_name=clip.m_Name)
                print(f"{entry['file']}  {info['duration_seconds']:.3f}s", flush=True)
                del clip, samples, data
        finally:
            del environment
            by_filename = {}
            gc.collect()
    counts = dict(Counter(entry['category'] for entry in entries))
    report = dict(game_dir=str(game_dir), scope='Prince direct audio calls and one related room hint',
                  raw_audio=True, counts=counts, duration_seconds=sum(e['duration_seconds'] for e in entries),
                  sound_index=str(sounds), bundle_prince_inventory=bundle_inventories, clips=entries)
    (output/'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    description = [
        'Prince 音频试听索引', '',
        '01-22 是 Prince_Talk 的完整独立对话素材，是本次语音选项的主要候选',
        '其余文件是茎部移动、关节、印记效果，以及一个房间提示循环，均在文件名中标注用途',
        '原作没有按具体台词对应片段；新字幕随机选取 Prince_Talk，省略号不触发，瘫痪状态不发声',
        '受击产生的回复仍使用同一组 Prince_Talk，没有另外发现 Prince 专用 Pain/Protest 语音组',
        '完整保留每个源片段，没有按静音裁切、变调、响度统一，也没有拆分素材内部的语音与音效',
        '这些是原始素材音量；原作另有音量倍率、距离衰减，茎部移动循环还会改变音调',
        'RWTW_Sigil 原资源以 OGG 命名，和其他资源一样解码为 PCM WAV 便于统一试听',
        '本次只生成试听文件，不接入设置中的语音选项，也不修改角色配置', '',
        f'共 {len(entries)} 个 WAV，总时长 {report["duration_seconds"]:.3f} 秒',
        f'游戏目录：{game_dir}', '源码根目录：D:\\CODES\\CS\\rw_src', '',
    ]
    for entry in entries:
        description += [entry['file'],
                        f"  时长 {entry['duration_seconds']:.3f} 秒；{entry['sample_rate']} Hz；{entry['channels']} 声道",
                        f"  用途：{entry['purpose']}", f"  游戏混音：{entry['game_mix']}",
                        f"  调用位置：{entry['code_reference']}", '']
    (output/'试听说明.txt').write_text('\n'.join(description)+'\n', encoding='utf-8')
    playlist = ['#EXTM3U']
    for entry in entries:
        playlist += [f"#EXTINF:{entry['duration_seconds']:.3f},{entry['file']}", entry['file']]
    (output/'全部试听.m3u8').write_text('\n'.join(playlist)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, default=Path(r'D:\steam\steamapps\common\Rain World'))
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/prince-voice-reference')
    args = parser.parse_args()
    report = extract(args.game_dir.resolve(), args.output.resolve())
    print(json.dumps(dict(counts=report['counts'], output=str(args.output.resolve())), ensure_ascii=False))


if __name__ == '__main__':
    main()
