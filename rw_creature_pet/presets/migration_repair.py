"""依据旧备份和迁移指纹纠正已完成的错误会话迁入，不自动重跑普通角色迁移"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from ..config import AppConfig
from .common import write_document
from .editing import ALL_PATHS, PresetLink, snapshot
from .fields import paths_for
from .migration import _merge, migration_marker, select_records
from .migration_cleanup import _legacy_fingerprints, directory_digest
from .personal import PersonalEntry, apply_values
from .profile import load_profile
from .workspace import metadata, read_entry, save_entry


def _signature(values):
    return snapshot(apply_values(AppConfig(), values), tuple(values))


def _history_signature(history):
    return [(row['name'], row['time'], _signature(row['values'])) for row in history]


def _resolve_images(entry, store, backup):
    resources = Path(backup).parent/'resources.json'
    files = json.loads(resources.read_text(encoding='utf-8')).get('files', {}) if resources.exists() else {}
    entry = deepcopy(entry)
    for values in (entry.defaults, entry.overrides, *(row['values'] for row in entry.history)):
        for key, value in tuple(values.items()):
            if key.endswith('.image_path') and value:
                path = Path(value).expanduser()
                path = (path if path.is_absolute() else store.path.parent/path).resolve()
                if not path.is_file() and str(path) in files:
                    path = Path(backup).parent/files[str(path)]
                values[key] = str(path)
    return entry


def _preserved_fields(old, current):
    before, after = _signature(old), _signature(current)
    changed = {key for key in current if before.get(key) != after[key]}
    groups = {key.removesuffix('image_path') for key in current if key.endswith('.image_path')}
    for key in tuple(changed):
        for prefix in groups:
            if key.startswith(prefix):
                changed.update(field for field in current if field.startswith(prefix))
        counterpart = re.sub(r'([._])(min|max)(?=[._]|$)',
            lambda match: match[1]+('max' if match[2] == 'min' else 'min'), key)
        if counterpart in current:
            changed.add(counterpart)
    if 'oracle.body_appearance' in changed:
        changed.update(key for key in current if key in paths_for('appearance'))
    return changed


def plan_repair(store, library, *, preserve_changes=True):
    document = store.read_document()
    if document.get('preset_state', {}).get('version') != 3:
        raise ValueError('修复只适用于已完成目录迁移的配置')
    report = library.scan()
    if report.errors or report.duplicates or not report.presets:
        raise ValueError('请先处理角色库中的损坏文件或重复 ID')
    known, _ = _legacy_fingerprints(store, report.presets)
    root = library.directory.resolve()
    rows = []
    for preset in report.presets:
        directory = preset.path.parent.resolve()
        if directory.parent != root:
            raise ValueError('修复只处理 profiles 的直接子目录')
        row = {'id': preset.id, 'name': preset.name, 'path': str(directory),
               'digest': directory_digest(directory), 'action': 'keep', 'reason': 'no_matching_migration'}
        rows.append(row)
        matched = known.get(metadata(preset).get('migration_key'))
        if not matched or matched[2] != 'profile' or matched[1].source is None:
            continue
        old_key, previous, _, backup = matched
        if previous.source.id != preset.id:
            continue
        saved = json.loads(Path(backup).read_text(encoding='utf-8'))['preset_state']
        selected, _ = select_records(saved, report.presets)
        key, raw, _ = next(item for item in selected if item[2].id == preset.id)
        chosen = PersonalEntry.read(raw)
        # 与正式迁移保持相同的路径规范化和指纹计算，备用图片替换在计算指纹之后进行
        for values in (chosen.defaults, chosen.overrides, *(item['values'] for item in chosen.history)):
            for field, value in tuple(values.items()):
                if field.endswith('.image_path') and value:
                    path = Path(value).expanduser()
                    values[field] = str((path if path.is_absolute() else store.path.parent/path).resolve())
        marker = migration_marker(key, chosen)
        row.update(old_key=old_key, selected_key=key, backup=backup,
                   old_source_date=previous.source.updated_at, selected_source_date=chosen.source.updated_at)
        if marker == metadata(preset).get('migration_key'):
            row['reason'] = 'correct_record_already_selected'
            continue
        current = read_entry(preset.path)
        original = load_profile(directory/'original/profile.json')
        previous = _resolve_images(previous, store, backup)
        chosen = _resolve_images(chosen, store, backup)
        _, wrong_values = _merge(previous, original)
        defaults, corrected = _merge(chosen, original)
        preserved = _preserved_fields(wrong_values, current.values) if preserve_changes else set()
        values = {**corrected, **{field: current.values[field] for field in preserved}}
        apply_values(AppConfig(), values)
        history = chosen.history
        if preserve_changes and _history_signature(current.history) != _history_signature(previous.history):
            history = current.history
        entry = PersonalEntry('profile', current.source, defaults,
            {field: value for field, value in values.items() if value != defaults.get(field)},
            deepcopy(history), chosen.appearance_name, chosen.appearance_source)
        before, after = _signature(current.values), _signature(values)
        row.update(action='repair', reason='different_legacy_record', migration_key=marker,
                   corrected_fields=[field for field in ALL_PATHS if before[field] != after[field]],
                   preserved_fields=sorted(preserved), replacement=entry.serialize())
    return {'settings': str(store.path.resolve()), 'settings_digest': sha256(store.path.read_bytes()).hexdigest(),
            'library': str(root), 'preserve_changes': preserve_changes, 'rows': rows}


def apply_repair(store, library, plan):
    """先备份全部角色并在副本中修复，再原子提交各角色清单；失败恢复旧清单"""
    fresh = plan_repair(store, library, preserve_changes=plan['preserve_changes'])
    if fresh != plan:
        raise ValueError('角色、settings 或旧备份已改变，请重新检查修复计划')
    changed = [row for row in plan['rows'] if row['action'] == 'repair']
    if not changed:
        return {'repaired': [], 'unchanged': [row['name'] for row in plan['rows']], 'backup_directory': None}
    root = library.directory.resolve()
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    backup = (root.parent/'migration-repair'/token).resolve()
    if backup.is_relative_to(root) or backup.parent.parent != root.parent:
        raise ValueError('备份目录不在允许范围内')
    backup.mkdir(parents=True)
    before_settings = store.path.read_bytes()
    (backup/'settings.before.json').write_bytes(before_settings)
    settings_bak = store.path.with_suffix('.json.bak')
    before_bak = settings_bak.read_bytes() if settings_bak.exists() else None
    if before_bak is not None:
        (backup/'settings.before.json.bak').write_bytes(before_bak)
    for row in plan['rows']:
        source = Path(row['path'])
        destination = backup/'before'/source.name
        shutil.copytree(source, destination)
        if directory_digest(destination) != row['digest']:
            raise ValueError('角色备份校验失败，当前目录未改动')
    for row in changed:
        source = Path(row['path'])
        staging = backup/'staging'/source.name
        shutil.copytree(backup/'before'/source.name, staging)
        entry = PersonalEntry.read(row['replacement'])
        entry.source = PresetLink.of(load_profile(staging/'profile.json'))
        save_entry(entry, migration_key=row['migration_key'])
        if directory_digest(staging/'original') != directory_digest(source/'original'):
            raise ValueError('修复副本的恢复源发生变化，当前目录未改动')
    result = {'repaired': [row['name'] for row in changed],
              'unchanged': [row['name'] for row in plan['rows'] if row['action'] != 'repair'],
              'backup_directory': str(backup), 'settings_backup': str(backup/'settings.before.json')}
    receipt = {'status': 'pending', 'result': result, 'plan': plan}
    write_document(backup/'repair.json', receipt)
    document = json.loads(before_settings.decode('utf-8'))
    state = document['preset_state']
    written = []
    try:
        if store.path.read_bytes() != before_settings:
            raise ValueError('settings 已改变，请重新检查')
        for row in plan['rows']:
            if directory_digest(Path(row['path'])) != row['digest']:
                raise ValueError('角色目录已改变，请重新检查')
        for row in changed:
            source = Path(row['path'])
            existing = {path.relative_to(source) for path in source.rglob('*') if path.is_file()}
            written.append((source, existing))
            entry = PersonalEntry.read(row['replacement'])
            entry = save_entry(entry, migration_key=row['migration_key'])
            for value in state['entries'].values():
                if (value.get('source') or {}).get('id') == row['id']:
                    value['source'] = entry.source.serialize()
        if store.path.read_bytes() != before_settings:
            raise ValueError('settings 已改变，已撤销修复')
        state.setdefault('character_setup', {})['migration_repair'] = {
            'version': 1, 'backup': str(backup), 'roles': result['repaired']}
        store._write(document)
    except Exception:
        for source, existing in reversed(written):
            original = backup/'before'/source.name
            for name in ('profile.json', 'profile.json.bak'):
                previous, target = original/name, source/name
                if previous.exists():
                    payload = previous.read_bytes()
                    if not target.exists() or target.read_bytes() != payload:
                        temporary = source/('.staging-repair-rollback-'+uuid4().hex)
                        temporary.write_bytes(payload)
                        temporary.replace(target)
                else:
                    target.unlink(missing_ok=True)
            # save_entry 只增加不可变资源，失败后移除本批新增文件，不移动或删除角色目录
            for candidate in source.rglob('*'):
                relative = candidate.relative_to(source)
                if (candidate.is_file() and relative not in existing
                        and relative.parts[0] in ('appearance', 'history')):
                    candidate.unlink()
        # settings 原子提交失败不会修改主文件，但可能已经更新 .bak
        if before_bak is None:
            settings_bak.unlink(missing_ok=True)
        else:
            settings_bak.write_bytes(before_bak)
        raise
    receipt['status'] = 'complete'
    try:
        write_document(backup/'repair.json', receipt)
    except OSError as exc:
        result['receipt_error'] = str(exc)
    return result
