"""核对旧迁移指纹，将误生成的角色完整归档到 profiles 之外"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from .common import get_value, write_document
from .fields import paths_for
from .migration import _merge, migration_marker
from .personal import PersonalEntry, apply_values
from .profile import load_profile
from .startup import BELL_PROFILE_ID
from .workspace import metadata, read_entry, values_from_profile
from .editing import ALL_PATHS, snapshot
from ..config import AppConfig


def directory_digest(directory):
    root = Path(directory).resolve()
    digest = sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('待清理目录包含链接，请手动检查')
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode('utf-8'))
            digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _legacy_fingerprints(store, choices):
    fallback = next((p for p in choices if p.id == BELL_PROFILE_ID), None)
    fallback = fallback or next((p for p in choices if p.appearance.oracle.body_appearance == 'bell'), choices[0])
    defaults = values_from_profile(load_profile(fallback.path.parent/'original/profile.json'))
    known, source_times = {}, {}
    backup_root = store.path.parent/'migrations/characters-v1'
    for path in sorted(backup_root.glob('*/settings.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        state = data.get('preset_state', {})
        if state.get('version') != 2:
            continue
        for key, raw in state.get('entries', {}).items():
            entry = PersonalEntry.read(raw)
            kind = entry.kind
            for values in (entry.defaults, entry.overrides, *(item['values'] for item in entry.history)):
                for field, value in tuple(values.items()):
                    if field.endswith('.image_path') and value:
                        image = Path(value).expanduser()
                        values[field] = str((image if image.is_absolute() else store.path.parent/image).resolve())
            if kind == 'appearance':
                merged_defaults = {**defaults, **entry.defaults}
                overrides = dict(entry.overrides)
                if key == state.get('active'):
                    values = state.get('directory_migration', {}).get('raw_values')
                    if values is None:
                        values = {}
                        for field in paths_for('profile'):
                            try:
                                values[field] = get_value(data.get('config', {}), field)
                            except (KeyError, AttributeError):
                                pass
                    overrides.update({field: value for field, value in values.items() if field in paths_for('profile')})
                entry = PersonalEntry('profile', entry.source, merged_defaults, overrides,
                                      entry.history, entry.appearance_name, entry.appearance_source)
            marker = migration_marker(key, entry)
            known[marker] = (key, entry, kind, str(path))
            if entry.source:
                source_times.setdefault(entry.source.id, set()).add(entry.source.updated_at)
    return known, source_times


def plan_cleanup(store, library):
    document = store.read_document()
    if document.get('preset_state', {}).get('version') != 3:
        raise ValueError('清理只适用于已经完成目录迁移的配置')
    report = library.scan()
    if report.errors:
        raise ValueError('角色库包含损坏文件，请先检查后再清理')
    if not report.presets:
        raise ValueError('没有可检查的角色目录')
    known, source_times = _legacy_fingerprints(store, report.presets)
    root = library.directory.resolve()
    rows = []
    for preset in report.presets:
        info = metadata(preset)
        matched = known.get(info.get('migration_key'))
        row = {'name': preset.name, 'id': preset.id, 'path': str(preset.path.parent),
               'action': 'keep', 'reason': 'not_verified_generated', 'revision': preset.revision}
        if matched:
            key, entry, kind, backup = matched
            row.update(legacy_key=key, backup=backup,
                       legacy_source_id=entry.source.id if entry.source else None)
            generated_id = str(uuid5(NAMESPACE_URL, 'rw-creature-pet:recovery:'+key))
            original = load_profile(preset.path.parent/'original/profile.json')
            if kind == 'appearance' or entry.source is None or preset.id == generated_id:
                row.update(action='archive', reason='historical_or_unlinked')
            elif entry.source.path.resolve() == preset.path.resolve():
                row['reason'] = 'original_existing_character'
            elif original.updated_at not in source_times.get(preset.id, set()):
                row.update(action='archive', reason='recreated_missing_character')
            else:
                row['reason'] = 'relocated_existing_character'
            if row['action'] == 'archive':
                # 此前的自动生成角色都是库的直接子目录，嵌套或手工整理过的目录保守保留
                if preset.path.parent.resolve().parent != root:
                    row.update(action='keep', reason='manually_relocated_directory')
                else:
                    _, expected = _merge(entry, original)
                    current = read_entry(preset.path)
                    row['changed_values'] = snapshot(apply_values(AppConfig(), expected), ALL_PATHS) != snapshot(
                        apply_values(AppConfig(), current.values), ALL_PATHS)
                    row['digest'] = directory_digest(preset.path.parent)
        rows.append(row)
    return {'settings': str(store.path.resolve()), 'settings_digest': sha256(store.path.read_bytes()).hexdigest(),
            'library': str(root), 'rows': rows}


def apply_cleanup(store, library, plan):
    """同盘移动完整目录，设置提交失败则移回；实际角色内容始终保留"""
    root = library.directory.resolve()
    if plan['library'] != str(root) or plan['settings'] != str(store.path.resolve()):
        raise ValueError('清理计划与当前目录不一致')
    previous = store.path.read_bytes()
    if sha256(previous).hexdigest() != plan['settings_digest']:
        raise ValueError('settings 已改变，请重新检查清理计划')
    archived = [row for row in plan['rows'] if row['action'] == 'archive']
    if not archived:
        return {'archived': 0, 'remaining': len(plan['rows']), 'archive_directory': None}
    paths = {Path(row['path']).resolve() for row in archived}
    for row in archived:
        path = Path(row['path']).resolve()
        if path.parent != root or path == root or directory_digest(path) != row['digest']:
            raise ValueError('角色目录已改变或不在清理范围内，请重新检查')
    document = json.loads(previous.decode('utf-8'))
    state = document['preset_state']
    removed = {}
    for key, value in tuple(state.get('entries', {}).items()):
        source = value.get('source') or {}
        path = Path(source.get('path', '')).resolve()
        if path.parent in paths:
            removed[key] = state['entries'].pop(key)
    if state.get('active') in removed:
        current = removed[state['active']]['source']
        legacy_id = next((r.get('legacy_source_id') for r in archived if r['id'] == current['id']), None)
        candidates = state['entries']
        selected = next((key for key, value in candidates.items() if value['source']['id'] == legacy_id), None)
        selected = selected or next((key for key, value in candidates.items() if value['source']['id'] == BELL_PROFILE_ID), None)
        selected = selected or next(iter(candidates), None)
        if selected is None:
            raise ValueError('清理后没有可用的当前角色，请先保留一个实际使用的角色')
        state['active'] = selected
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    archive = (root.parent/'migration-archive'/token).resolve()
    if archive.is_relative_to(root) or archive == root or archive.parent.parent != root.parent:
        raise ValueError('归档目录不在允许的位置')
    backup = store.path.parent/'migrations/profile-cleanup'/token
    backup.mkdir(parents=True)
    (backup/'settings.before.json').write_bytes(previous)
    archive.mkdir(parents=True)
    result = {'archived': len(archived), 'remaining': len(plan['rows'])-len(archived),
              'archive_directory': str(archive), 'settings_backup': str(backup/'settings.before.json'),
              'changed_values_archived': sum(bool(row.get('changed_values')) for row in archived)}
    receipt = {'status': 'pending', 'result': result, 'plan': plan}
    for path in (archive/'cleanup.json', backup/'cleanup.json'):
        write_document(path, receipt)
    moved = []
    try:
        for row in archived:
            source = Path(row['path']).resolve()
            destination = archive/source.name
            source.rename(destination)
            moved.append((source, destination))
            if directory_digest(destination) != row['digest']:
                raise ValueError('归档内容校验失败')
        if store.path.read_bytes() != previous:
            raise ValueError('settings 已改变，已撤销清理，请重新检查')
        state.setdefault('character_setup', {})['recovery_cleanup'] = {
            'version': 1, 'archive': str(archive), 'removed_entries': len(removed)}
        store._write(document)
    except Exception:
        for source, destination in reversed(moved):
            if destination.exists() and not source.exists():
                destination.rename(source)
        raise
    receipt['status'] = 'complete'
    for path in (archive/'cleanup.json', backup/'cleanup.json'):
        try:
            write_document(path, receipt)
        except OSError as exc:
            # 主数据已提交，不能把补写收据失败误报为清理已撤销
            result.setdefault('receipt_errors', []).append(str(exc))
    return result
