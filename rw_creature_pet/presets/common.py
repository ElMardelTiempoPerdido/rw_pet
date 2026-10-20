"""外观包和角色设置共用的读取、字段合并及目录操作"""
from dataclasses import dataclass, replace
from datetime import datetime
import json
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import tempfile
from uuid import UUID, uuid4

from ..shared.messages import Message


def get_value(obj, path):
    for name in path.split('.'):
        obj = obj[name] if isinstance(obj, dict) else getattr(obj, name)
    return obj


def set_value(mapping, path, value):
    *parts, name = path.split('.')
    for part in parts:
        mapping = mapping.setdefault(part, {})
    mapping[name] = value


def mapping_for(config, paths):
    result = {}
    for path in paths:
        set_value(result, path, get_value(config, path))
    return result


def replace_fields(config, changes):
    """一次替换每组字段，保留未展示的设置和嵌套配色"""
    return replace(config, **{
        name: replace_fields(getattr(config, name), value) if isinstance(value, dict) else value
        for name, value in changes.items()
    })


def scoped_leaves(data, allowed, prefix=''):
    if not isinstance(data, dict):
        raise ValueError('配置内容必须为对象')
    for key, value in data.items():
        path = f'{prefix}.{key}' if prefix else key
        if path in allowed:
            if isinstance(value, (dict, list)):
                raise ValueError(Message('配置字段格式无效：{path}', path=path))
            yield path, value
        elif any(item.startswith(path+'.') for item in allowed):
            yield from scoped_leaves(value, allowed, path)
        else:
            raise ValueError(Message('不属于此配置类型的字段：{path}', path=path))


def validate_metadata(identifier, name, updated_at):
    try:
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            raise ValueError
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError
        if any(ord(char) < 32 for char in name):
            raise ValueError
        if not isinstance(updated_at, str):
            raise ValueError
        stamp = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError('配置文件的 ID、名称或更新时间无效') from None
    return stamp


def package_path(directory, reference):
    if not isinstance(reference, str):
        raise ValueError('配置引用路径必须为字符串')
    path = PurePosixPath(reference)
    if (not reference or '\\' in reference or ':' in reference or path.is_absolute()
            or PureWindowsPath(reference).drive or '..' in path.parts):
        raise ValueError(Message('配置资源必须使用包内相对路径：{path}', path=reference))
    root = Path(directory).resolve()
    resolved = (root/reference).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(Message('资源路径超出了配置包目录：{path}', path=reference))
    return resolved


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(Message('配置文件包含重复字段：{path}', path=key))
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError('配置文件包含无效数值')


def read_document(path, *, format, version, extra_fields=()):
    path = Path(path).resolve()
    if path.stat().st_size > 256*1024:
        raise ValueError('配置文件不能超过 256 KB')
    data = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object,
                      parse_constant=_invalid_number)
    if not isinstance(data, dict) or data.get('type') != format:
        raise ValueError('配置类型不匹配，请选择对应类型的文件')
    if type(data.get('version')) is not int or data['version'] != version:
        raise ValueError('不支持此配置文件版本，请使用匹配版本的桌宠')
    if set(data) != {'type', 'version', 'id', 'name', 'updated_at', 'config', *extra_fields}:
        raise ValueError('配置文件字段不完整或包含未知字段')
    validate_metadata(data['id'], data['name'], data['updated_at'])
    return data


def write_document(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def revision_for(paths):
    digest = sha256()
    for path in paths:
        payload = Path(path).read_bytes()
        digest.update(len(payload).to_bytes(8, 'big'))
        digest.update(payload)
    return digest.hexdigest()


def update_package(directory, target, manifest, write, load):
    """先写不可变资源，最后原子替换清单；旧清单和旧资源可通过备份恢复"""
    root, path = Path(directory).resolve(), target.path.resolve()
    if path.name != manifest or not path.is_relative_to(root):
        raise ValueError('只能更新配置库内的文件')

    def check_revision():
        current = load(path)
        if current.id != target.id or current.revision != target.revision:
            raise ValueError('目标文件已被修改，请刷新后重新选择')

    check_revision()
    created = []
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=root) as temporary:
        staging = Path(temporary)
        write(staging)
        load(staging/manifest)
        try:
            for source in staging.rglob('*'):
                if not source.is_file() or source == staging/manifest:
                    continue
                destination = package_path(path.parent, source.relative_to(staging).as_posix())
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if destination.read_bytes() != source.read_bytes():
                        raise ValueError('目标文件的资源发生冲突，请刷新后重试')
                else:
                    created.append(destination)
                    shutil.copyfile(source, destination)
            check_revision()
            backup = staging/'previous.json'
            backup.write_bytes(path.read_bytes())
            backup.replace(path.with_suffix('.json.bak'))
            (staging/manifest).replace(path)
        except Exception:
            for destination in created:
                destination.unlink(missing_ok=True)
            raise
    return load(path)


def default_library_directory(kind):
    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    return root/'presets'/kind


@dataclass(frozen=True, slots=True)
class LibraryScan:
    presets: tuple
    duplicates: tuple[tuple, ...]
    errors: tuple[tuple[Path, Exception], ...]


def scan_library(directory, manifest, loader):
    groups, errors = {}, []
    root = Path(directory).resolve()
    if not root.exists():
        return LibraryScan((), (), ())
    for path in sorted(root.rglob(manifest), key=lambda p: (str(p).casefold(), str(p))):
        if any(part.startswith('.staging-') for part in path.relative_to(root).parts):
            continue
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError('配置文件路径超出了配置包目录')
            preset = loader(path)
            groups.setdefault(preset.id, []).append(preset)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            # 报告仅供显示；堆栈会保留 PNG 读取器并锁住文件，阻止用户修复坏资源
            exc.__traceback__ = exc.__context__ = exc.__cause__ = None
            errors.append((path, exc))
    winners, duplicates = [], []
    for group in groups.values():
        # 相同时间戳保持先前的路径排序，不依赖系统文件修改时间
        group.sort(key=lambda preset: preset.timestamp, reverse=True)
        winners.append(group[0])
        if len(group) > 1:
            duplicates.append(tuple(group))
    winners.sort(key=lambda preset: (preset.name.casefold(), preset.id))
    return LibraryScan(tuple(winners), tuple(duplicates), tuple(errors))


def publish_package(directory, name, prefix, manifest, write, load):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=directory) as temporary:
        staging = Path(temporary)
        write(staging)
        load(staging/manifest)
        slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:48] or 'untitled'
        target = directory/f'{prefix}-{slug}-{uuid4().hex}'
        staging.rename(target)
    return load(target/manifest)
