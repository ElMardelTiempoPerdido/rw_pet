"""旧 settings 角色快照迁移，保留原文件并按角色记录可重试的完成标记"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

from ..config import AppConfig
from ..shared.messages import Message
from .common import write_document
from .editing import PresetLink, snapshot
from .personal import PersonalEntry, PersonalState, apply_values, read_link
from .profile import MANIFEST, load_profile
from .workspace import (ensure_workspace, metadata, read_entry, save_entry,
                        values_from_profile)


def backup_legacy(store):
    """补默认值和拆分前保留原始字节及外部图片，重试不覆盖先前备份"""
    if not store.path.exists():
        return None
    payload = store.path.read_bytes()
    data = json.loads(payload.decode('utf-8'))
    state = data.get('preset_state', {})
    if state.get('version') == 3:
        return None
    digest = sha256(payload).hexdigest()
    root = store.path.parent/'migrations/characters-v1'
    target = root/digest
    if target.exists():
        return target
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=root) as temporary:
        staging = Path(temporary)
        (staging/'settings.json').write_bytes(payload)
        resources, missing = {}, []
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if (key == 'image_path' or key.endswith('.image_path')) and item:
                        source = Path(item).expanduser()
                        source = source if source.is_absolute() else store.path.parent/source
                        if not source.is_file():
                            missing.append(str(source))
                            continue
                        content = source.read_bytes()
                        name = 'images/'+sha256(content).hexdigest()+'.png'
                        (staging/'images').mkdir(exist_ok=True)
                        (staging/name).write_bytes(content)
                        resources[str(source)] = name
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(data)
        write_document(staging/'resources.json', {'files': resources, 'missing': missing})
        staging.rename(target)
    return target


def _merge(entry, preset):
    """用旧基准识别实际修改，图片按内容比较，相关部件作为一组迁移"""
    defaults = values_from_profile(preset)
    old = apply_values(AppConfig(), entry.defaults)
    current = apply_values(AppConfig(), entry.values)
    # 只判断旧文件确实保存过的值；新字段采用新的发行默认
    keys = tuple(entry.values)
    before, after = snapshot(old, keys), snapshot(current, keys)
    changed = {key for key in keys if before[key] != after[key]}
    # 图片开关、形状、路径及偏移不能拼接为不相容的资源组合
    image_groups = {key.removesuffix('image_path') for key in keys if key.endswith('.image_path')}
    for key in tuple(changed):
        for prefix in image_groups:
            if key.startswith(prefix):
                changed.update(path for path in keys if path.startswith(prefix))
        # 上下限必须保持成对有效，避免新版另一端与用户值形成反向区间
        counterpart = re.sub(r'([._])(min|max)(?=[._]|$)',
            lambda match: match[1]+('max' if match[2] == 'min' else 'min'), key)
        if counterpart in keys:
            changed.add(counterpart)
    # 主体改变时保留这一主体的完整外观，避免把发行版另一个主体的默认值套入
    if 'oracle.body_appearance' in changed:
        from .fields import paths_for
        changed.update(path for path in keys if path in paths_for('appearance'))
    values = {**defaults, **{key: entry.values[key] for key in changed}}
    apply_values(AppConfig(), values)
    return defaults, values


def migration_marker(key, entry):
    return sha256((key+json.dumps(entry.serialize(), sort_keys=True, ensure_ascii=False)).encode('utf-8')).hexdigest()


def select_records(saved, choices):
    """每个现存角色只选择一份记录，旧会话及已删除角色只留在备份中"""
    targets = {preset.id: preset for preset in choices}
    groups, archived = {}, []
    records = saved.get('entries', {}) if saved.get('version') == 2 else {}
    for key, data in records.items():
        if data.get('kind') != 'profile' or not data.get('source'):
            archived.append({'key': key, 'reason': 'unlinked_or_appearance'})
            continue
        source = read_link(data['source'])
        target = targets.get(source.id)
        if target is None:
            archived.append({'key': key, 'reason': 'missing_character'})
            continue
        score = (key == saved.get('active'), source.revision == target.revision,
                 source.path.resolve() == target.path.resolve(), source.timestamp, key)
        groups.setdefault(source.id, []).append((score, key, data))
    selected = []
    for identifier, candidates in groups.items():
        candidates.sort(reverse=True, key=lambda row: row[0])
        _, key, data = candidates[0]
        selected.append((key, data, targets[identifier]))
        archived.extend({'key': old_key, 'reason': 'older_revision'} for _, old_key, _ in candidates[1:])
    return selected, archived


def migrate(store, library, config, saved, fallback):
    """全部角色成功后返回新引用状态，旧 settings 的移除由统一提交完成"""
    backup = backup_legacy(store)
    state = PersonalState()
    state.workspace = True
    state.autosave = saved.get('autosave', True) is not False
    state.character_setup = {'version': 1, 'complete': True}
    active = saved.get('active')
    selected, archived = select_records(saved, library.scan().presets)
    entries = [(key, PersonalEntry.read(data), target) for key, data, target in selected]
    def resolve_images(values):
        for path, value in tuple(values.items()):
            if path.endswith('.image_path') and value:
                image = Path(value).expanduser()
                values[path] = str((image if image.is_absolute() else store.path.parent/image).resolve())
    for _, entry, _ in entries:
        resolve_images(entry.defaults)
        resolve_images(entry.overrides)
        for item in entry.history:
            resolve_images(item['values'])
    entries.sort(key=lambda row: row[0] != active)
    raw_values = deepcopy(saved.get('directory_migration', {}).get('raw_values', {}))
    resolve_images(raw_values)
    # 没有角色会话的最老版本才迁入全局配置；已删除/未关联会话不能套到其他角色
    if not saved.get('entries') and raw_values:
        defaults = values_from_profile(load_profile(fallback.path.parent/'original'/MANIFEST))
        if 'oracle.body_appearance' in raw_values and 'oracle.voice' not in raw_values:
            from ..oracle.audio.voice import legacy_voice
            raw_values['oracle.voice'] = legacy_voice(raw_values['oracle.body_appearance'])
        values = {**defaults, **raw_values}
        # 最老格式没有比较基准，明确保存的值均按用户值保留
        entry = PersonalEntry('profile', PresetLink.of(fallback), defaults,
                              {key: value for key, value in values.items() if value != defaults.get(key)})
        entries.insert(0, ('legacy-current', entry, fallback))
        active = 'legacy-current'
    state.character_setup['directory_migration'] = {'version': 2, 'backup': str(backup) if backup else None,
                                                   'archived': archived}
    for key, entry, target in entries:
        try:
            target = ensure_workspace(target.path)
            marker = migration_marker(key, entry)
            if metadata(target).get('migration_key') == marker:
                migrated = read_entry(target.path)
            else:
                original = load_profile(target.path.parent/'original'/MANIFEST)
                defaults, values = _merge(entry, original)
                migrated = PersonalEntry('profile', PresetLink.of(target), defaults,
                    {path: value for path, value in values.items() if value != defaults.get(path)},
                    deepcopy(entry.history), entry.appearance_name, entry.appearance_source)
                migrated = save_entry(migrated, migration_key=marker)
            new_key = state.key('profile', migrated.source)
            state.entries[new_key] = migrated
            if key == active:
                state.active = new_key
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(Message('角色 {name} 迁移未完成，旧数据及备份已保留：{error}',
                                    name=entry.source.name if entry.source else key, error=exc)) from exc
    if state.active not in state.entries:
        key, entry = state.from_preset('profile', fallback, config, store.path.parent/'appearance/images')
        state.committed(key, entry)
    return state, bool(entries)
