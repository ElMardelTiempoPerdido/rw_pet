"""独立目录 + 无 Conda PATH + 空用户缓存的单文件包验收。"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def stage_release(archive, directory, executable):
    """验证实际交付的 ZIP；先检查路径，再解压校验，EXE 必须与受检版本一致"""
    from rw_creature_pet.presets.common import package_path
    from tools.packaging.release import validate_release
    seen = set()
    with ZipFile(archive) as package:
        for item in package.infolist():
            key = item.filename.rstrip('/').casefold()
            if key in seen or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('发行 ZIP 包含重复路径或链接')
            seen.add(key)
            package_path(directory, item.filename.rstrip('/'))
        package.extractall(directory)
    manifest = validate_release(directory)
    installed = directory/manifest['executable']
    if hashlib.sha256(installed.read_bytes()).digest() != hashlib.sha256(executable.read_bytes()).digest():
        raise ValueError('发行 ZIP 的 EXE 与受检版本不一致')
    return installed, manifest


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8')
    from PyInstaller.archive.readers import CArchiveReader
    import pefile
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=ROOT/'dist/BellPet.exe')
    parser.add_argument('--release', type=Path, help='同时验证并从实际发行 ZIP 启动，包含固定角色库')
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
                 'rw_creature_pet/fonts/WenQuanYi Bitmap Song 14px.ttf',
                 'fmod_toolkit/libfmod/Windows/x64/fmod.dll', 'rw_creature_pet/ico/bell_icon_16.png'):
        assert name in entries, f'缺少包内依赖：{name}'
    for name in ('config.toml', 'rw_creature_pet/translations/en.qm',
                 'rw_creature_pet/fonts/WenQuanYi Bitmap Song 14px.ttf'):
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
    release = None
    if args.release:
        copied, release = stage_release(args.release.resolve(), directory, exe)
    else:
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
    if release is not None:
        from rw_creature_pet.presets.profile_library import ProfileLibrary
        from rw_creature_pet.presets.startup import BELL_PROFILE_ID
        settings = output/'profile/rw_creature_pet/settings.json'
        data = json.loads(settings.read_text(encoding='utf-8'))
        state = data['preset_state']
        assert state['version'] == 3 and state['entries'][state['active']]['source']['id'] == BELL_PROFILE_ID
        library = ProfileLibrary(directory/'presets/profiles').scan()
        assert not library.errors and {p.id for p in library.presets} == {p['id'] for p in release['characters']}
        report.update(release_zip=str(args.release.resolve()),
                      release_sha256=hashlib.sha256(args.release.read_bytes()).hexdigest(),
                      release_characters=len(library.presets), release_zip_startup=True,
                      fresh_active_character=BELL_PROFILE_ID)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    assert completed.returncode == 0 and report['ok'], '包内自检失败，见上方报告'


if __name__ == '__main__':
    main()
