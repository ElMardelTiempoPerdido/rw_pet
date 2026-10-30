"""生成 EXE 与 original 预设组成的发行目录及 ZIP，不写入开发者的角色目录"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import tempfile
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rw_creature_pet.presets.common import package_path, write_document
from rw_creature_pet.presets.appearance import image_paths
from rw_creature_pet.presets.common import get_value
from rw_creature_pet.presets.profile import MANIFEST, load_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.presets.sharing import open_profile, original_of, write_snapshot, write_zip


def load_catalog(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('characters'), list) or not data['characters']:
        raise ValueError('发行角色清单格式无效')
    identifiers, directories = set(), set()
    for item in data['characters']:
        if not isinstance(item, dict) or set(item) != {'id', 'directory'}:
            raise ValueError('发行角色清单需要 ID 和固定目录名')
        identifier, directory = item['id'], item['directory']
        if str(UUID(identifier)) != identifier or identifier in identifiers:
            raise ValueError('发行角色 ID 无效或重复')
        target = package_path(ROOT, directory)
        if (target.parent != ROOT or directory in ('original', 'history', 'recovery')
                or directory.startswith('.') or directory.casefold() in directories):
            raise ValueError('发行角色目录名无效或重复')
        identifiers.add(identifier)
        directories.add(directory.casefold())
    return data['characters']


def validate_release(directory):
    root = Path(directory).resolve()
    data = json.loads((root/'release.json').read_text(encoding='utf-8'))
    if data.get('type') != 'rw-creature-pet.release' or data.get('version') != 1:
        raise ValueError('发行包清单无效')
    executable = package_path(root, data['executable'])
    if executable.parent != root or executable.suffix.lower() != '.exe' or not executable.is_file():
        raise ValueError('发行包缺少 EXE')
    allowed = {executable, root/'release.json'}
    for item in data['characters']:
        role = package_path(root/'presets/profiles', item['directory'])
        original = load_profile(role/'original'/MANIFEST)
        if original.id != item['id']:
            raise ValueError('发行角色 ID 与清单不一致')
        allowed.update((original.path, original.appearance.path))
        for key in image_paths(original.appearance.oracle, full=original.appearance.full):
            reference = get_value({'oracle': original.appearance.oracle}, key)
            if reference:
                allowed.add(original.appearance.image(reference))
    allowed.update(root/'presets/behavior_styles'/name for name in ('builtin.toml', 'README.md'))
    for path in root.rglob('*'):
        if path.is_file() and path not in allowed:
            raise ValueError(f'发行包包含用户当前设置或多余文件：{path.relative_to(root)}')
    return data


def build_release(executable, output, *, profiles=None, catalog=None, overrides=()):
    executable, output = Path(executable).resolve(), Path(output).resolve()
    if not executable.is_file() or executable.suffix.lower() != '.exe':
        raise ValueError('请选择已生成的 EXE 文件')
    if output == executable.parent or executable.is_relative_to(output):
        raise ValueError('发行目录不能包含输入 EXE')
    characters = load_catalog(catalog or ROOT/'presets/release.json')
    source = Path(profiles or ROOT/'presets/profiles').resolve()
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('发行输出目录必须与源角色目录分开')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        validate_release(output)  # 只允许替换本工具生成的发行目录
    with ExitStack() as stack:
        replacements = {}
        for override in overrides:
            path = Path(override).resolve()
            packages = sorted(path.glob('*.zip')) if path.is_dir() and not (path/MANIFEST).exists() else [path]
            if not packages:
                raise ValueError(f'没有找到角色分享包：{path}')
            for package in packages:
                preset = stack.enter_context(open_profile(package))
                if preset.id in replacements:
                    raise ValueError(f'同一角色提供了多个替换包：{preset.id}')
                replacements[preset.id] = preset
        known = {item['id'] for item in characters}
        if set(replacements)-known:
            raise ValueError('替换包中存在未登记的角色，请先添加到发行清单')
        with tempfile.TemporaryDirectory(prefix='.staging-release-', dir=output.parent) as temporary:
            staging = Path(temporary)/'release'
            staging.mkdir()
            shutil.copy2(executable, staging/executable.name)
            styles = staging/'presets/behavior_styles'
            styles.mkdir(parents=True)
            for filename in ('builtin.toml', 'README.md'):
                shutil.copy2(ROOT/'presets/behavior_styles'/filename, styles/filename)
            for item in characters:
                if item['id'] in replacements:
                    preset = replacements[item['id']]
                else:
                    # 固定目录而非遍历整个用户角色库，恢复副本不会被顺带发布
                    preset = load_profile(source/item['directory']/MANIFEST)
                if preset.id != item['id']:
                    raise ValueError(f'角色目录中的 ID 已改变：{item["directory"]}')
                write_snapshot(original_of(preset), staging/'presets/profiles'/item['directory']/'original')
            write_document(staging/'release.json', {'type': 'rw-creature-pet.release', 'version': 1,
                'executable': executable.name, 'characters': characters})
            validate_release(staging)
            archive = Path(temporary)/'release.zip'
            write_zip(staging, archive)
            previous = None
            try:
                if output.exists():
                    previous = output.with_name(output.name+'.previous-'+uuid4().hex)
                    output.rename(previous)
                staging.rename(output)
                archive.replace(output.with_name(output.name+'.zip'))
            except Exception:
                if previous is not None:
                    if output.exists():
                        output.rename(Path(temporary)/'failed')
                    previous.rename(output)
                elif output.exists():
                    output.rename(Path(temporary)/'failed')
                raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=ROOT/'dist/BellPet.exe')
    parser.add_argument('--output', type=Path, default=ROOT/'dist/release')
    parser.add_argument('--profiles', type=Path, default=ROOT/'presets/profiles')
    parser.add_argument('--catalog', type=Path, default=ROOT/'presets/release.json')
    parser.add_argument('--overrides', type=Path, action='append', default=[], help='新导出的 ZIP 或存放分享 ZIP 的目录')
    args = parser.parse_args()
    result = build_release(args.exe, args.output, profiles=args.profiles, catalog=args.catalog,
                           overrides=args.overrides)
    print(result)
    print(result.with_name(result.name+'.zip'))


if __name__ == '__main__':
    main()
