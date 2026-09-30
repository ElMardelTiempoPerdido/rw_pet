"""独立目录 + 无 Conda PATH + 空用户缓存的单文件包验收。"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    from PyInstaller.archive.readers import CArchiveReader
    import pefile
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=ROOT/'dist/BellPet.exe')
    parser.add_argument('--report', type=Path, default=ROOT/'artifacts/bell-package-verification.json')
    args = parser.parse_args()
    (ROOT/'artifacts').mkdir(exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    exe = args.exe.resolve()
    archive = CArchiveReader(str(exe))
    entries = {name.replace('\\', '/') for name in archive.toc}
    for name in ('config.toml', 'PySide6/plugins/platforms/qwindows.dll', 'UnityPy/resources/lzma.tpk',
                 'archspec/json/cpu/microarchitectures.json',
                 'rw_creature_pet/translations/en.qm', 'rw_creature_pet/translations/qtbase_zh_CN.qm',
                 'fmod_toolkit/libfmod/Windows/x64/fmod.dll', 'rw_creature_pet/ico/bell_icon_16.png'):
        assert name in entries, f'缺少包内依赖：{name}'
    for name in ('config.toml', 'rw_creature_pet/translations/en.qm'):
        stored_name = next(key for key in archive.toc if key.replace('\\', '/') == name)
        assert archive.extract(stored_name) == (ROOT/name).read_bytes(), f'包内文件不是当前版本：{name}'
    assert not any(name.endswith(('.wav', '.assets')) or name.startswith(('artifacts/', 'tests/'))
                   for name in entries), '包内不应包含游戏素材或测试缓存'
    pe = pefile.PE(str(exe))
    assert pe.FILE_HEADER.Machine == 0x8664 and pe.OPTIONAL_HEADER.Subsystem == 2
    icons = []
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id == 3:
            for entry in kind.directory.entries:
                for language in entry.directory.entries:
                    data = language.data.struct
                    icons.append(pe.get_data(data.OffsetToData, data.Size))
    assert all((ROOT/'rw_creature_pet/ico'/name).read_bytes() in icons
               for name in ('bell_icon_16_dark.png', 'bell_icon_dark.png'))
    pe.close()
    directory = Path(tempfile.mkdtemp(prefix='单文件验证-', dir=ROOT/'artifacts'))
    copied = directory/'BellPet.exe'
    shutil.copy2(exe, copied)
    environment = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'CONDA_PREFIX', 'PYFMODEX_DLL_PATH'):
        environment.pop(name, None)
    windows = Path(os.environ['SystemRoot'])
    environment['PATH'] = os.pathsep.join((str(windows/'System32'), str(windows)))
    output = directory/'checks'
    completed = subprocess.run([str(copied), '--self-test', str(output)], cwd=directory,
                               env=environment, timeout=240, creationflags=subprocess.CREATE_NO_WINDOW)
    report = json.loads((output/'report.json').read_text(encoding='utf-8'))
    report.update(exit_code=completed.returncode, exe=str(exe), bytes=exe.stat().st_size,
                  sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                  dark_icons_exact=True, isolated_directory=str(directory))
    report['current_defaults_and_translation'] = True
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    assert completed.returncode == 0 and report['ok'], '包内自检失败，见上方报告'


if __name__ == '__main__':
    main()
