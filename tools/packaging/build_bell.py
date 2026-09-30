"""在已安装依赖的 Windows 环境生成 dist/BellPet.exe。"""
from pathlib import Path
import argparse
import os
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def make_icon():
    # 直接嵌入两张用户 PNG，保留原像素；不重新采样或修改源文件。
    from PIL import Image
    icons = ROOT/'rw_creature_pet/ico'
    frames = []
    for name in ('bell_icon_16_dark.png', 'bell_icon_dark.png'):
        path = icons/name
        with Image.open(path) as image:
            width, height = image.size
        if width != height or not 1 <= width <= 256:
            raise ValueError(f'图标必须为 1～256 像素的正方形：{path}')
        frames.append((width, height, path.read_bytes()))
    header = struct.pack('<HHH', 0, 1, len(frames))
    entries, data, offset = [], [], 6+16*len(frames)
    for width, height, png in frames:
        entries.append(struct.pack('<BBBBHHII', width % 256, height % 256, 0, 0, 1, 32, len(png), offset))
        data.append(png)
        offset += len(png)
    destination = ROOT/'build/packaging/bell-dark.ico'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header+b''.join(entries)+b''.join(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full', action='store_true', help='保留 Qt 自动收集的附加组件，供对照/回退')
    parser.add_argument('--upx-dir', type=Path, help='可选：UPX 所在目录；由 PyInstaller 压缩包内二进制')
    parser.add_argument('--name', default='BellPet', help='输出文件名，不含 .exe')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.name):
        parser.error('--name 只允许英文字母、数字、下划线和连字符')
    if args.upx_dir is not None and not (args.upx_dir/'upx.exe').is_file():
        parser.error('--upx-dir 下找不到 upx.exe')
    if sys.platform != 'win32':
        raise SystemExit('Windows EXE 需要在 Windows 上构建。')
    # TS 编辑后不能沿用旧 QM；检查通过才生成并打包最新译文。
    subprocess.run([sys.executable, str(ROOT/'tools/update_translations.py'), '--check', '--compile'],
                   cwd=ROOT, check=True)
    make_icon()
    environment = dict(os.environ, RW_PET_BUNDLE_FULL=str(int(args.full)),
                       RW_PET_BUNDLE_UPX=str(int(args.upx_dir is not None)), RW_PET_BUNDLE_NAME=args.name)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm',
               '--distpath', str(ROOT/'dist'), '--workpath', str(ROOT/'build/pyinstaller')]
    if args.upx_dir is not None:
        command += ['--upx-dir', str(args.upx_dir.resolve())]
    subprocess.run([*command, str(ROOT/'tools/packaging/bell.spec')],
                   cwd=ROOT, env=environment, check=True)
    exe = ROOT/'dist'/f'{args.name}.exe'
    print(f'{exe} ({exe.stat().st_size/1024**2:.1f} MiB)')


if __name__ == '__main__':
    main()
