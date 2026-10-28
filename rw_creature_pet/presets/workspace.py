"""角色工作目录：当前设置、发行默认值和可移植历史的唯一磁盘来源"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import re
from uuid import uuid4

from ..config import AppConfig
from .appearance import image_paths
from .common import get_value, package_path, update_package, write_document
from .editing import ALL_PATHS, PresetLink
from .fields import paths_for
from .library import write_appearance
from .profile import FORMAT, MANIFEST, load_profile, profile_mapping

VERSION = 1
MARKER = 'character.json'


def values_from_profile(preset):
    values = {key: get_value(preset.config, key) for key in paths_for('profile')}
    values.update({key: get_value({'oracle': preset.appearance.oracle}, key)
                   for key in paths_for('appearance')})
    for key in image_paths(preset.appearance.oracle, full=True):
        if values[key]:
            values[key] = str(preset.appearance.image(values[key]))
    return values


def metadata(preset):
    if not preset.state_path:
        return {'version': VERSION, 'history': [], 'appearance_name': preset.appearance.name}
    path = package_path(preset.path.parent, preset.state_path)
    if path.stat().st_size > 4*1024*1024:
        raise ValueError('角色历史文件过大')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or type(data.get('version')) is not int or data.get('version') != VERSION:
        raise ValueError('不支持的角色工作目录版本')
    if not isinstance(data.get('history'), list) or not isinstance(data.get('appearance_name'), str):
        raise ValueError('角色工作目录格式或 ID 无效')
    if any(not isinstance(item, dict) or not {'name', 'time', 'values'} <= item.keys()
           or not isinstance(item['values'], dict) for item in data['history']):
        raise ValueError('角色工作目录格式或 ID 无效')
    return data


def read_entry(path):
    from .personal import PersonalEntry, apply_values, read_link
    current = load_profile(path)
    marker = current.path.parent/MARKER
    if marker.exists():
        info = json.loads(marker.read_text(encoding='utf-8'))
        if (not isinstance(info, dict) or type(info.get('version')) is not int
                or info.get('version') != VERSION or info.get('type') != 'rw-creature-pet.character'
                or info.get('id') != current.id):
            raise ValueError('角色工作目录格式或 ID 无效')
    original = load_profile(current.path.parent/'original'/MANIFEST)
    if current.id != original.id:
        raise ValueError('当前角色与 original 的 ID 不一致')
    defaults, values = values_from_profile(original), values_from_profile(current)
    info = metadata(current)
    history = deepcopy(info.get('history', []))
    for item in history:
        for key, value in tuple(item['values'].items()):
            if key.endswith('.image_path') and value:
                item['values'][key] = str(package_path(current.path.parent, value))
                if not Path(item['values'][key]).is_file():
                    raise ValueError('角色历史引用的贴图不存在')
        apply_values(AppConfig(), item['values'])
    entry = PersonalEntry('profile', PresetLink.of(current), defaults,
        {key: value for key, value in values.items() if value != defaults.get(key)}, history,
        info.get('appearance_name', current.appearance.name),
        read_link(info.get('appearance_source', PresetLink.of(current.appearance).serialize())))
    # 复用旧快照的字段、时间及范围校验
    return PersonalEntry.read(entry.serialize())


def resolve_reference(source, library=None):
    """安装目录整体移动时按 ID 找回；当前文件损坏或单独丢失仍报错"""
    path = Path(source['path'])
    if path.exists() or (path.parent/MARKER).exists():
        return path
    if library is None:
        from .profile_library import ProfileLibrary
        library = ProfileLibrary()
    report = library.scan()
    choices = {item.path: item for item in report.presets if item.id == source['id']}
    for group in report.duplicates:
        choices.update({item.path: item for item in group if item.id == source['id']})
    if len(choices) == 1:
        return next(iter(choices))
    raise ValueError('找不到唯一对应的角色目录，请恢复原目录或检查重复角色')


def copy_snapshot(preset, destination):
    """只复制明确引用的配置和资源，不递归携带本地历史或其他角色"""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    write_appearance(destination/'appearance', preset.appearance.oracle, preset.appearance.name,
        preset.appearance.id, preset.appearance.updated_at, preset.appearance.image,
        full=preset.appearance.full)
    write_document(destination/MANIFEST, dict(type=FORMAT, version=1, id=preset.id,
        name=preset.name, updated_at=preset.updated_at, config=profile_mapping(preset.config),
        appearance={'id': preset.appearance.id, 'path': 'appearance/appearance.json'}))
    return load_profile(destination/MANIFEST)


def ensure_workspace(path):
    """旧角色保留原始默认值；仅 original 的发行包首次创建当前副本"""
    path = Path(path).resolve()
    root = path.parent
    marker = root/MARKER
    if marker.exists():
        info = json.loads(marker.read_text(encoding='utf-8'))
        if (not isinstance(info, dict) or type(info.get('version')) is not int
                or info.get('version') != VERSION or info.get('type') != 'rw-creature-pet.character'):
            raise ValueError('不支持的角色工作目录格式')
        current = load_profile(path)  # 丢失或损坏的当前文件不能自动恢复为默认
        if current.id != info.get('id'):
            raise ValueError('角色工作目录 ID 不一致')
        read_entry(path)
        return current
    current = load_profile(path)
    original = root/'original'
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=root) as temporary:
        staging = Path(temporary)
        if not original.exists():
            copy_snapshot(current, staging/'original')
            (staging/'original').rename(original)
        baseline = load_profile(original/MANIFEST)
        if baseline.id != current.id:
            raise ValueError('当前角色与 original 的 ID 不一致')
        if not path.exists():
            # manifest 最后出现，初始化中断后可以继续；发布包不含当前文件
            copy_snapshot(baseline, staging/'current')
            appearance = root/'appearance'/('initial-'+uuid4().hex)
            appearance.parent.mkdir(exist_ok=True)
            (staging/'current/appearance').rename(appearance)
            data = json.loads((staging/'current'/MANIFEST).read_text(encoding='utf-8'))
            data['appearance']['path'] = (appearance/'appearance.json').relative_to(root).as_posix()
            write_document(staging/MANIFEST, data)
            (staging/MANIFEST).replace(path)
        write_document(staging/MARKER, {'type': 'rw-creature-pet.character',
                                      'version': VERSION, 'id': current.id})
        (staging/MARKER).replace(marker)
    return load_profile(path)


def _portable_history(history, staging):
    from .appearance import checked_image
    from .personal import apply_values
    result = deepcopy(history)
    for item in result:
        config = apply_values(AppConfig(), item['values'])
        for key, value in tuple(item['values'].items()):
            if not key.endswith('.image_path') or not value:
                continue
            decal = get_value(config, key.removesuffix('.image_path'))
            payload = checked_image(value, decal).read_bytes()
            relative = 'history/images/'+sha256(payload).hexdigest()+'.png'
            destination = staging/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            item['values'][key] = relative
    return result


def save_entry(entry, *, migration_key=None):
    """写入不可变外观和历史，最后一次原子切换当前 profile 指针"""
    from .personal import apply_values
    target = ensure_workspace(entry.source.path)
    if target.id != entry.source.id or target.revision != entry.source.revision:
        raise ValueError('角色文件已被修改，请重新载入后保存')
    config = apply_values(AppConfig(), entry.values)
    token = uuid4().hex
    folder, state_path = 'appearance/'+token, 'history/state-'+token+'.json'
    stamp = max(datetime.now(timezone.utc), target.timestamp+timedelta(microseconds=1)).isoformat()
    previous_info = metadata(target)

    def write(staging):
        write_appearance(staging/folder, config.oracle, entry.appearance_name or target.appearance.name,
            target.appearance.id, stamp, lambda reference: Path(reference), full=True)
        info = {'version': VERSION, 'history': _portable_history(entry.history, staging),
                'appearance_name': entry.appearance_name,
                'appearance_source': entry.appearance_source.serialize() if entry.appearance_source else None}
        if migration_key or previous_info.get('migration_key'):
            info['migration_key'] = migration_key or previous_info['migration_key']
        (staging/'history').mkdir(exist_ok=True)
        write_document(staging/state_path, info)
        write_document(staging/MANIFEST, dict(type=FORMAT, version=2, id=target.id,
            name=target.name, updated_at=stamp, config=profile_mapping(config), state=state_path,
            appearance={'id': target.appearance.id, 'path': folder+'/appearance.json'}))

    saved = update_package(target.path.parent, target, MANIFEST, write, load_profile)
    return read_entry(saved.path)


def refresh_entry(entry):
    loaded = read_entry(entry.source.path)
    entry.__dict__.update(loaded.__dict__)
    return entry


@contextmanager
def commit_pending(state):
    """设置文件提交失败时回滚角色清单；已写的不可变资源不影响旧指针"""
    from .personal import PersonalEntry
    result = deepcopy(state)
    pending = result.pop('pending', {})
    before = []
    try:
        for key, data in pending.items():
            entry = PersonalEntry.read(data)
            path = entry.source.path
            previous = path.read_bytes()
            saved = save_entry(entry)
            before.append((path, previous, path.read_bytes()))
            result['entries'][key] = {'kind': 'profile', 'source': saved.source.serialize()}
        yield result
    except Exception:
        for path, payload, committed in reversed(before):
            if path.read_bytes() != committed:
                continue  # 其他写入者已更新文件，不能用本次回滚覆盖它
            temporary = path.with_name('.staging-rollback-'+uuid4().hex)
            temporary.write_bytes(payload)
            temporary.replace(path)
        raise
    else:
        for path, _, _ in before:
            prune_generations(path)


def prune_generations(path):
    """只清理本模块创建且不再被当前/回滚清单引用的代次，保留用户资源"""
    root = Path(path).resolve().parent
    keep = set()
    try:
        for manifest in (root/MANIFEST, root/'profile.json.bak'):
            if manifest.exists():
                data = json.loads(manifest.read_text(encoding='utf-8'))
                keep.add(package_path(root, data['appearance']['path']).parent)
                if data.get('state'):
                    keep.add(package_path(root, data['state']))
        for directory in (root/'appearance', root/'history'):
            if not directory.is_dir():
                continue
            for candidate in directory.iterdir():
                generated = (re.fullmatch(r'[0-9a-f]{32}', candidate.name) if directory.name == 'appearance'
                             else re.fullmatch(r'state-[0-9a-f]{32}\.json', candidate.name))
                resolved = candidate.resolve()
                if generated and resolved not in keep and resolved.is_relative_to(root) and not candidate.is_symlink():
                    if candidate.is_dir():
                        shutil.rmtree(candidate)
                    else:
                        candidate.unlink()
    except (OSError, ValueError, KeyError):
        pass  # 清理失败保留不可变文件，不把已经成功的保存报告为失败


def local_mapping(config_mapping):
    """磁盘 settings 只保存本机字段，角色字段从当前角色目录重建"""
    data = deepcopy(config_mapping)
    for path in ALL_PATHS:
        *parts, leaf = path.split('.')
        node = data
        for name in parts:
            node = node.get(name, {})
        node.pop(leaf, None)
    def prune(node):
        return {key: prune(value) if isinstance(value, dict) else value
                for key, value in node.items() if not isinstance(value, dict) or prune(value)}
    return prune(data)
