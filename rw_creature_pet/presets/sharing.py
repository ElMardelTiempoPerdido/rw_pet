"""角色分享快照、ZIP 读取和有备份的导入事务，不携带全局设置"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from ..config import AppConfig
from ..shared.messages import Message
from .common import package_path, publish_package, validate_metadata, write_document
from .editing import ALL_PATHS, snapshot
from .library import write_appearance
from .personal import apply_values
from .profile import FORMAT, MANIFEST, load_profile, profile_mapping
from .workspace import (ensure_workspace, read_entry, save_entry, values_from_profile)

_RESERVED = {'original', 'history', 'recovery', '__macosx'}


def original_of(preset):
    path = preset.path.parent/'original'/MANIFEST
    original = load_profile(path) if path.exists() else preset
    if original.id != preset.id:
        raise ValueError('当前角色与 original 的 ID 不一致')
    return original


def content_key(preset):
    """忽略时间、缓存路径和像素相同的图片文件名，比较当前配置与恢复源"""
    def key(item):
        return snapshot(apply_values(AppConfig(), values_from_profile(item)), ALL_PATHS)
    return preset.name, key(preset), key(original_of(preset))


def write_snapshot(preset, destination, *, identifier=None, name=None, folder='appearance'):
    config = apply_values(AppConfig(), values_from_profile(preset))
    return write_config(config, destination, name or preset.name, identifier or preset.id,
                        preset.updated_at, preset.appearance, folder=folder,
                        appearance_time=preset.appearance.updated_at)


def write_config(config, destination, name, identifier, stamp, appearance=None, *, folder='appearance', appearance_time=None):
    """分享快照保留全部外观分支，只写入角色所属的字段"""
    validate_metadata(identifier, name, stamp)
    root = Path(destination)
    appearance_id = appearance.id if appearance else str(uuid4())
    write_appearance(root/folder, config.oracle, appearance.name if appearance else name,
        appearance_id, appearance_time or stamp, lambda reference: Path(reference).expanduser().resolve(), full=True)
    write_document(root/MANIFEST, dict(type=FORMAT, version=1, id=identifier, name=name,
        updated_at=stamp, config=profile_mapping(config),
        appearance={'id': appearance_id, 'path': folder+'/appearance.json'}))
    return load_profile(root/MANIFEST)


def write_zip(directory, destination):
    """先生成完整 ZIP，成功后再替换输出文件"""
    directory, destination = Path(directory).resolve(), Path(destination).resolve()
    if destination.suffix.lower() != '.zip':
        raise ValueError('分享文件必须使用 .zip 扩展名')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.staging-', suffix='.zip', dir=destination.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED) as archive:
            for path in sorted(directory.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(directory).as_posix())
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError('分享压缩包校验失败')
        temporary.replace(destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_share(config, destination, *, name, identifier, appearance=None):
    stamp = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    with tempfile.TemporaryDirectory(prefix='rw-character-share-') as temporary:
        root = Path(temporary)/('profile-'+identifier)
        current = write_config(config, root, name.strip(), identifier, stamp, appearance)
        write_snapshot(current, root/'original')
        # 在打包前重读两个入口，禁止生成缺资源的分享文件
        if content_key(current)[1] != content_key(load_profile(root/'original'/MANIFEST))[1]:
            raise ValueError('分享副本与默认设置不一致')
        return write_zip(Path(temporary), destination)


def _extract(archive, directory):
    entries = archive.infolist()
    if len(entries) > 4096 or sum(item.file_size for item in entries) > 256*1024*1024:
        raise ValueError('角色压缩包过大或包含过多文件')
    seen = set()
    for item in entries:
        name = item.filename.rstrip('/')
        if not name:
            continue
        target = package_path(directory, name)
        parts = PurePosixPath(name).parts
        devices = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))}
        if any(part.endswith((' ', '.')) or any(char in part for char in '<>"|?*')
               or part.split('.')[0].casefold() in devices for part in parts):
            raise ValueError('角色压缩包包含无效文件名')
        key = target.relative_to(directory).as_posix().casefold()
        if key in seen or stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('角色压缩包包含重复路径或链接')
        seen.add(key)
    for item in entries:
        if item.is_dir():
            continue
        target = package_path(directory, item.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as source, target.open('wb') as output:
            shutil.copyfileobj(source, output)


def profile_in_directory(directory):
    root = Path(directory).resolve()
    if (root/MANIFEST).exists() or (root/'original'/MANIFEST).exists():
        if (root/MANIFEST).exists() and not (root/MANIFEST).resolve().is_relative_to(root):
            raise ValueError('角色文件路径超出了压缩包目录')
        return load_profile(root/MANIFEST)
    candidates = set(root.rglob(MANIFEST))
    candidates.update(path.parent.parent/MANIFEST for path in tuple(candidates)
                      if path.parent.name.casefold() == 'original')
    candidates = [path for path in candidates if not any(
        part.casefold() in _RESERVED or part.startswith('.staging-') for part in path.relative_to(root).parts[:-1])]
    if len(candidates) != 1:
        raise ValueError('请选择只包含一个角色的文件夹或压缩包')
    if not candidates[0].resolve().is_relative_to(root):
        raise ValueError('角色文件路径超出了压缩包目录')
    return load_profile(candidates[0])


@contextmanager
def open_profile(source):
    source = Path(source).expanduser().resolve()
    if source.is_dir():
        yield profile_in_directory(source)
    elif source.suffix.lower() == '.zip':
        try:
            with tempfile.TemporaryDirectory(prefix='rw-character-import-') as temporary:
                root = Path(temporary)
                with ZipFile(source) as archive:
                    _extract(archive, root)
                yield profile_in_directory(root)
        except BadZipFile as exc:
            raise ValueError('角色压缩包损坏或格式无效') from exc
    else:
        yield load_profile(source)


def _atomic_bytes(path, payload):
    temporary = path.with_name('.staging-import-'+uuid4().hex)
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _replace(existing, incoming):
    target = ensure_workspace(existing.path)
    if target.revision != existing.revision:
        raise ValueError('目标文件已被修改，请刷新后重新选择')
    root = target.path.parent
    original = root/'original'/MANIFEST
    previous, baseline = target.path.read_bytes(), original.read_bytes()
    token = uuid4().hex
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=root) as temporary:
        staging = Path(temporary)
        # 自包含备份保留替换前的外观、行为和恢复源，旧外观历史继续沿用
        backup = staging/'backup'
        write_snapshot(target, backup)
        write_snapshot(load_profile(original), backup/'original')
        prepared = write_snapshot(original_of(incoming), staging/'baseline',
                                  folder='appearance/import-'+token)
        if load_profile(target.path).revision != target.revision or original.read_bytes() != baseline:
            raise ValueError('目标文件已被修改，请刷新后重新选择')
        (root/'history/imports').mkdir(parents=True, exist_ok=True)
        backup.rename(root/'history/imports'/token)
        destination = root/'original/appearance'/('import-'+token)
        destination.parent.mkdir(exist_ok=True)
        (staging/'baseline/appearance'/('import-'+token)).rename(destination)
        try:
            _atomic_bytes(original, prepared.path.read_bytes())
            entry = read_entry(target.path)
            current = apply_values(AppConfig(), entry.values)
            desired = apply_values(AppConfig(), values_from_profile(incoming))
            if snapshot(current, ALL_PATHS) != snapshot(desired, ALL_PATHS):
                entry.remember(current, root/'appearance/images')
            entry.appearance_name = incoming.appearance.name
            entry.appearance_source = None
            entry.update(desired, root/'appearance/images')
            saved = save_entry(entry)
            # 分享包的名字属于角色本身，时间则由本地提交生成
            data = json.loads(saved.source.path.read_text(encoding='utf-8'))
            data['name'] = incoming.name
            _atomic_bytes(saved.source.path, (json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
            yield load_profile(target.path)
        except Exception:
            _atomic_bytes(original, baseline)
            _atomic_bytes(target.path, previous)
            raise


@contextmanager
def import_transaction(library, source, *, conflict=None):
    with open_profile(source) as incoming:
        report = library.scan()
        existing = next((item for item in report.presets if item.id == incoming.id), None)
        if existing is not None:
            if content_key(existing) == content_key(incoming) or conflict == 'keep':
                yield ensure_workspace(existing.path)
                return
            if conflict == 'replace':
                with _replace(existing, incoming) as installed:
                    yield installed
                return
            if conflict != 'new':
                raise ValueError('已存在同 ID 的不同角色设置，请选择导入处理方式')
        identifier = str(uuid4()) if existing is not None else incoming.id
        name = incoming.name

        def write(staging):
            write_snapshot(incoming, staging, identifier=identifier, name=name)
            write_snapshot(original_of(incoming), staging/'original', identifier=identifier, name=name)

        installed = publish_package(library.directory, name, 'profile', MANIFEST, write, load_profile)
        try:
            yield ensure_workspace(installed.path)
        except Exception:
            root = Path(library.directory).resolve()
            created = installed.path.parent.resolve()
            if created.parent == root and created.name.startswith('profile-'):
                shutil.rmtree(created)
            raise
