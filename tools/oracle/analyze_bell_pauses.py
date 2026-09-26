"""离线寻找 Bell WAV 的低能量停顿候选；不修改音频或运行时播放配置。"""
import argparse
import base64
import csv
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import wave

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def analyze(path, *, drop_db=18., minimum_core=.18, window=.02, hop=.005):
    with wave.open(str(path), 'rb') as audio:
        if audio.getsampwidth() != 2 or audio.getcomptype() != 'NONE':
            raise ValueError(f'{path}: 需要 16 位 PCM WAV')
        rate, channels = audio.getframerate(), audio.getnchannels()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
        samples = samples.reshape(-1, channels).astype(np.float64)/32768.
    width, stride = max(1, round(rate*window)), max(1, round(rate*hop))
    if len(samples) < width:
        raise ValueError(f'{path}: 音频短于分析窗口')
    starts = np.arange(0, len(samples)-width+1, stride)
    sums = np.vstack((np.zeros(channels), np.cumsum(samples*samples, axis=0)))
    # 分别计算声道能量，取较响声道，避免直接混成单声道时产生相位抵消假停顿。
    power = np.maximum(np.max((sums[starts+width]-sums[starts])/width, axis=1), 1e-18)
    db = 10*np.log10(power)
    times = (starts+width/2)/rate
    step = stride/rate
    reference = float(np.percentile(db, 95))
    threshold = reference-drop_db
    # 较宽松区间描述尾音衰减；切点必须落入其中连续的严格低能量核心。
    loose = db <= threshold+6.
    for a, b in runs(~loose):
        if a and b < len(loose) and (b-a)*step <= .025:
            loose[a:b] = True
    duration = len(samples)/rate
    candidates = []
    for a, b in runs(loose):
        # 首尾静音只有一侧有声音，不作为内部切分候选。
        if a == 0 or b == len(loose):
            continue
        cores = [(a+c, a+d) for c, d in runs(db[a:b] <= threshold)
                 if (d-c)*step >= minimum_core]
        if not cores:
            continue
        c, d = max(cores, key=lambda pair: pair[1]-pair[0])
        cut = float((times[c]+times[d-1])/2)
        start, end = float(times[a]-step/2), float(times[b-1]+step/2)
        core_start, core_end = float(times[c]-step/2), float(times[d-1]+step/2)
        # 验证停顿两侧附近确实有更响的声音，降低缓慢底噪起伏的误报。
        before = db[(times >= max(0., start-.5)) & (times < start)]
        after = db[(times > end) & (times <= min(duration, end+.5))]
        if not len(before) or not len(after):
            continue
        core_db = float(np.median(db[c:d]))
        contrast = float(min(np.percentile(before, 90), np.percentile(after, 90))-core_db)
        if contrast < 10.:
            continue
        category = 'edge' if min(cut, duration-cut) < 1.2 else (
            'long' if core_end-core_start >= .45 else 'short')
        candidates.append(dict(cut_seconds=round(cut, 4),
            quiet_start=round(start, 4), quiet_end=round(end, 4),
            core_start=round(core_start, 4), core_end=round(core_end, 4),
            core_duration=round(core_end-core_start, 4),
            core_dbfs=round(core_db, 2), flank_contrast_db=round(contrast, 2),
            category=category, left_seconds=round(cut, 4), right_seconds=round(duration-cut, 4)))
    result = dict(file=path.name, source=str(path.resolve()), sha256=sha256(path.read_bytes()).hexdigest(),
        duration_seconds=duration, sample_rate=rate, channels=channels,
        reference_dbfs=round(reference, 2), core_threshold_dbfs=round(threshold, 2),
        candidates=candidates)
    return result, times, db


LABELS = {'long': '较长低能量核心', 'short': '较短低能量核心', 'edge': '靠近首尾，可能形成短片段'}


def write_plot(output, analyses):
    # 只供离线分析；matplotlib 不加入桌宠运行时依赖。
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(analyses), 1, figsize=(13, 2.25*len(analyses)), squeeze=False)
    for axis, (entry, times, db) in zip(axes[:, 0], analyses):
        axis.plot(times, db, color='#344f65', lw=.85)
        axis.axhline(entry['core_threshold_dbfs'], color='#80919a', lw=.8, ls='--')
        for item in entry['candidates']:
            color = '#b77827' if item['category'] == 'edge' else '#16846b'
            axis.axvspan(item['quiet_start'], item['quiet_end'], color=color, alpha=.08)
            axis.axvspan(item['core_start'], item['core_end'], color=color, alpha=.2)
            axis.axvline(item['cut_seconds'], color=color, lw=1.)
            axis.text(item['cut_seconds'], -7, f"{item['cut_seconds']:.2f}s",
                      color=color, ha='center', va='top', fontsize=10)
        axis.set(xlim=(0, entry['duration_seconds']), ylim=(-65, -5), ylabel='RMS (dBFS)',
                 title=f"{entry['file']}  |  {entry['duration_seconds']:.2f}s", xlabel='Seconds within this clip')
        axis.grid(alpha=.15)
    fig.suptitle('Bell voice: pause candidates (20 ms RMS, louder channel)\n'
                 'Pale = decay region; dark = quiet core; line = candidate; amber = near an endpoint', fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, .95))
    fig.savefig(output/'pauses.png', dpi=150)
    plt.close(fig)


def write_reports(output, report, *, has_plot=False):
    (output/'pauses.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (output/'pauses.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['clip', 'duration_s', 'cut_s', 'quiet_start_s', 'quiet_end_s',
                         'core_start_s', 'core_end_s', 'core_duration_s', 'core_dbfs', 'category'])
        for entry in report['clips']:
            for item in entry['candidates']:
                writer.writerow([entry['file'], entry['duration_seconds'], item['cut_seconds'],
                    item['quiet_start'], item['quiet_end'], item['core_start'], item['core_end'],
                    item['core_duration'], item['core_dbfs'], item['category']])
    lines = ['# Bell 语音停顿候选', '',
        '所有时间均相对于当前 bell_01～05.wav 的开头，不是完整采访时间。', '',
        '这是声学停顿检测，不是语义断句；失真人声的句内间隙也可能成为候选，需要试听。'
        '音频、切分时间表及运行时播放配置均未修改。', '',
        '方法：20 ms 窗口 / 约 5 ms 步长，逐声道计算 RMS 后取较响声道；'
        f"相对每段第 95 百分位音量下降 {report['settings']['drop_db']:g} dB 的连续核心至少 "
        f"{report['settings']['minimum_core_seconds']*1000:g} ms。"
        '放宽 6 dB 定位尾音区域，只合并其中不超过 25 ms 的短暂隆起。'
        '切点取最长严格核心的中点，并要求两侧声音至少高 10 dB。', '',
        '| 音频 | 总长 | 候选切点 | 含尾音的低能量区间 | 严格核心 | 单独切此处后的长度 | 备注 |',
        '| --- | ---: | ---: | --- | --- | --- | --- |']
    sections = []
    for index, entry in enumerate(report['clips']):
        buttons = []
        if not entry['candidates']:
            lines.append(f"| {entry['file']} | {entry['duration_seconds']:.2f}s | — | — | — | — | 未发现符合本轮阈值的内部停顿 |")
        for item in entry['candidates']:
            lines.append(f"| {entry['file']} | {entry['duration_seconds']:.2f}s | {item['cut_seconds']:.2f}s | "
                f"{item['quiet_start']:.2f}–{item['quiet_end']:.2f}s | {item['core_start']:.2f}–{item['core_end']:.2f}s | "
                f"{item['left_seconds']:.2f}s / {item['right_seconds']:.2f}s | {LABELS[item['category']]} |")
            buttons.append(f'<button type="button" data-audio="a{index}" data-start="{max(0., item["cut_seconds"]-1.2):.4f}" '
                f'data-end="{min(entry["duration_seconds"], item["cut_seconds"]+1.2):.4f}">'
                f'试听 {item["cut_seconds"]:.2f}s 前后 · {LABELS[item["category"]]}</button>')
        encoded = base64.b64encode(Path(entry['source']).read_bytes()).decode('ascii')
        sections.append(f'<section><h2>{escape(entry["file"])} · {entry["duration_seconds"]:.2f}s</h2>'
            f'<audio id="a{index}" controls preload="metadata" src="data:audio/wav;base64,{encoded}"></audio>'
            '<div>'+(''.join(buttons) or '本轮未发现合适的内部候选。')+'</div></section>')
    lines.extend(['', '可先选择低能量核心较长的候选试听，再考虑进一步缩短。',
        '靠近首尾的候选保留在报告中，但不默认建议切分。所有候选是备选位置，不建议未经试听全部切开。', '',
        '实际切分时，可分别保留上一段尾音和下一段起音的余量；必要时在低能量处加几毫秒淡入淡出以避免爆音。', '',
        *(['![短时音量与候选区间](pauses.png)', ''] if has_plot else []),
        '交互试听页：[review.html](review.html)', ''])
    (output/'pauses.md').write_text('\n'.join(lines), encoding='utf-8')
    plot = output/'pauses.png'
    figure = ('<img alt="各段短时音量和候选切点" src="data:image/png;base64,'+
              base64.b64encode(plot.read_bytes()).decode('ascii')+'">') if has_plot else ''
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Bell 语音停顿候选</title><style>
body{max-width:1050px;margin:32px auto;padding:0 20px;background:#f8fafb;color:#20333f;font:16px/1.65 system-ui}
h1{font-size:26px}h2{font-size:19px}section{background:white;border:1px solid #dce3e8;border-radius:8px;margin:18px 0;padding:16px}
audio{width:100%}button{padding:9px 12px;margin:10px 8px 0 0;background:#f1f6f5;border:1px solid #b8d2c8;border-radius:5px;cursor:pointer}
img{width:100%;height:auto}p{max-width:900px}</style><h1>Bell 语音 · 停顿候选</h1>
<p>使用当前已处理的五段音频；所有时间从各段开头计算。按钮播放候选点前后各约 1.2 秒，播放器也支持完整试听。
候选仅表示能量降低，不保证一句结束。当前播放资源未修改。</p>'''+figure+''.join(sections)+'''
<script>
let active=null, stop=null;
document.querySelectorAll('audio').forEach(a=>{
 a.addEventListener('pointerdown',()=>{stop=null});
 a.addEventListener('play',()=>{document.querySelectorAll('audio').forEach(b=>{if(b!==a)b.pause()})});
 a.addEventListener('timeupdate',()=>{if(active===a&&stop!==null&&a.currentTime>=stop){a.pause();stop=null}});
});
document.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{
 if(active)active.pause();active=document.getElementById(b.dataset.audio);stop=Number(b.dataset.end);
 active.currentTime=Number(b.dataset.start);active.play();
}));
</script></html>'''
    (output/'review.html').write_text(html, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'artifacts/oracle-voice-reference/bell-clips')
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/oracle-voice-reference/pause-analysis')
    parser.add_argument('--drop-db', type=float, default=18.)
    parser.add_argument('--min-core', type=float, default=.18)
    parser.add_argument('--plot', action='store_true', help='额外输出音量图，需要离线依赖 matplotlib')
    args = parser.parse_args()
    if not np.isfinite(args.drop_db) or args.drop_db <= 0 or not np.isfinite(args.min_core) or args.min_core <= 0:
        parser.error('--drop-db 和 --min-core 必须是有限正数')
    paths = [args.input/f'bell_{i:02}.wav' for i in range(1, 6)]
    if any(not path.is_file() for path in paths):
        parser.error('输入目录须包含 bell_01.wav 至 bell_05.wav')
    analyses = [analyze(path, drop_db=args.drop_db, minimum_core=args.min_core) for path in paths]
    report = dict(input_directory=str(args.input.resolve()),
        settings=dict(window_seconds=.02, hop_seconds=.005, reference_percentile=95,
                      drop_db=args.drop_db, loose_margin_db=6., minimum_core_seconds=args.min_core,
                      maximum_loose_gap_seconds=.025, minimum_flank_contrast_db=10.),
        clips=[entry for entry, _, _ in analyses])
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plot:
        write_plot(args.output, analyses)
    write_reports(args.output, report, has_plot=args.plot)
    for entry in report['clips']:
        print(entry['file'], entry['duration_seconds'], [item['cut_seconds'] for item in entry['candidates']])
    print(args.output.resolve())


if __name__ == '__main__':
    main()
