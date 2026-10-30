"""角色优先的编辑会话：自动保存、只读默认值与外观快照"""
from contextlib import contextmanager
from copy import deepcopy

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialogButtonBox

from ...settings_store import load_defaults
from ...i18n import tr
from ...shared.messages import Message
from ...presets.appearance import apply_appearance
from ...presets.common import get_value
from ...presets.editing import ALL_PATHS, PresetLink
from ...presets.personal import apply_values, capture, normalized
from ...presets.startup import default_custom
from .preset_dialogs import NewCharacterDialog
from .preset_controls import bind_parameter_resets


class PresetWorkflow:
    def __init__(self, settings):
        self.settings = settings
        self.applied = settings.original
        self.defaults = load_defaults()
        self.filling = False
        self.dirty = False
        self.panels = {'appearance': settings.appearance_presets, 'profile': settings.profile_presets}
        self.state = settings.character_state
        self.key = self.state.active
        self.entry = deepcopy(self.state.entries[self.key])
        self.timer = QTimer(settings)
        self.timer.setSingleShot(True)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self.flush)
        with self.suspended():
            settings.fill_preset(apply_values(settings.original, self.entry.values), self.entry.values)
        for kind, panel in self.panels.items():
            panel.apply = lambda preset, k=kind: self.activate(k, preset)
            panel.loadedChanged.connect(lambda *_: self.sync_ui())
        self.panels['appearance'].after_export = lambda preset: self.sync_ui()
        self.panels['profile'].before_import = self.before_import
        ui = settings.personal_controls
        ui.autosave.setChecked(self.state.autosave)
        ui.autosave.toggled.connect(self.set_autosave)
        ui.save.clicked.connect(self.flush)
        settings.appearance_history.undo.clicked.connect(lambda: self.restore_history(0))
        settings.appearance_history.recent.clicked.connect(self.show_history)
        settings.appearance_history.reset.clicked.connect(lambda: self.restore_defaults('appearance'))
        settings.profile_presets.createCharacter.connect(self.show_new_character)
        settings.profile_defaults.clicked.connect(lambda: self.restore_defaults('profile'))
        for key, control in settings.controls.items():
            if key not in ALL_PATHS and not any(path.startswith(key+'.') for path in ALL_PATHS):
                continue
            signal = (control.group.buttonToggled if hasattr(getattr(control, 'group', None), 'buttonToggled') else
                      control.currentIndexChanged if hasattr(control, 'currentIndexChanged') else
                      control.valueChanged if hasattr(control, 'valueChanged') else control.toggled)
            signal.connect(lambda *args, k=key: self.changed(k))
        bind_parameter_resets(settings, self)
        settings.finished.connect(self.timer.stop)
        self.sync_ui()

    @property
    def directory(self):
        return self.entry.source.path.parent/'appearance/images'

    @contextmanager
    def suspended(self):
        previous, self.filling = self.filling, True
        try:
            yield
        finally:
            self.filling = previous

    def show_new_character(self):
        NewCharacterDialog(self.settings, self.create_character).exec()

    def create_character(self, name):
        if self.state.autosave and self.dirty and not self.flush():
            raise ValueError('当前调整保存失败，已保留当前选择')
        config = default_custom(self.defaults)
        preset = self.panels['profile'].library.export(config, name)
        self.activate('profile', preset)
        self.panels['profile'].refresh()
        return preset

    def draft(self):
        return self.settings.scoped_draft(ALL_PATHS)

    def changed(self, key=None):
        if self.filling:
            return
        self.settings.behavior_styles.edited(key)
        self.dirty = True
        self.settings.set_status('当前调整尚未保存')
        self.sync_ui()
        if self.state.autosave and self.settings.assets is not None:
            self.timer.start()

    def write(self, key, entry, config):
        data = self.state.serialize(key, entry)
        settings = self.settings
        # 自动保存只提交当前对象的字段，本机设置和不相关草稿仍等待显式应用
        effective = apply_values(self.applied, entry.values)
        info = settings.space_assessment(effective)
        if info is not None and not info.valid:
            raise ValueError('场景空间不足，请扩大活动带、缩小机械臂或降低显示倍率')
        with settings.store.preset_state(data):
            if settings.commit is not None and effective != self.applied:
                settings.commit(effective, settings.assets)
            else:
                settings.store.save(effective)
        from ...presets.workspace import refresh_entry
        refresh_entry(entry)
        effective = apply_values(effective, entry.values)
        with self.suspended():
            settings.fill_preset(effective, entry.values)
        self.applied = effective
        settings.saved_config, settings.prepared_assets = effective, settings.assets
        self.state.committed(key, entry)
        if hasattr(settings, 'resource_settings'):
            settings.resource_settings.ensure_runtime(effective)

    def flush(self):
        self.timer.stop()
        if (self.filling or self.settings.worker is not None
                or (hasattr(self.settings, 'resource_settings') and self.settings.resource_settings.worker is not None)):
            return False
        # 初次启动仍由“保存并启动”完成目录验证与资源准备
        if self.settings.assets is None:
            return True
        try:
            entry = deepcopy(self.entry)
            config = self.draft()
            if config.oracle.body_appearance == 'custom':
                for editor in self.settings.image_editors:
                    editor.validate()
            entry.update(config, self.directory)
            self.write(self.key, entry, config)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.settings.set_status(Message('调整尚未保存：{error}', error=exc))
            self.dirty = True
            self.sync_ui()
            return False
        self.entry = entry
        self.dirty = False
        self.sync_ui()
        self.settings.set_status('当前调整已保存')
        return True

    def set_autosave(self, enabled):
        self.timer.stop()
        self.state.autosave = enabled
        try:
            if enabled:
                if not self.flush():
                    return
            elif self.settings.assets is not None:
                # 只记住开关，不把尚未保存的选择或草稿一起提交
                with self.settings.store.preset_state(self.state.serialize()):
                    self.settings.store.save(self.applied)
        except (OSError, ValueError, TypeError) as exc:
            self.settings.set_status(Message('调整尚未保存：{error}', error=exc))
        self.sync_ui()

    def activate(self, kind, preset):
        if self.state.autosave and self.dirty and not self.flush():
            raise ValueError('当前调整保存失败，已保留当前选择')
        current = self.draft()
        if kind == 'profile' and not self.state.autosave:
            # 切换角色丢弃整个角色草稿，不能把未显示分支的临时配色带入新角色
            current = apply_values(current, capture(self.applied, 'profile', self.directory, include_inactive=True))
        if kind == 'appearance':
            # 每次导入读取分享文件本身，作为当前角色的副本，不存在独立外观会话
            key, entry = self.key, deepcopy(self.entry)
            desired = apply_appearance(current, preset, self.directory)
            before = capture(current, 'appearance', self.directory)
            after = capture(desired, 'appearance', self.directory)
            if normalized(before) != normalized(after):
                entry.remember(current, self.directory)
            entry.appearance_name = preset.name
            entry.appearance_source = PresetLink.of(preset)
        else:
            key, entry = self.state.from_preset('profile', preset, current, self.directory)
            desired = apply_values(current, entry.values)
        entry.update(desired, self.directory)
        self.install(key, entry, desired)

    def install(self, key, entry, config):
        if self.state.autosave and self.settings.assets is not None:
            self.write(key, entry, config)
        with self.suspended():
            self.settings.fill_preset(config, entry.values)
        self.key, self.entry = key, entry
        self.dirty = not self.state.autosave or self.settings.assets is None
        self.sync_ui()
        self.settings.set_status('当前调整尚未保存' if self.dirty else '当前调整已保存')

    def before_import(self):
        if self.state.autosave and self.dirty and not self.flush():
            raise ValueError('当前调整保存失败，已保留当前选择')

    def sync_ui(self):
        source = self.entry.source
        role = source if self.entry.kind == 'profile' else None
        appearance = self.panels['appearance']
        appearance.owner_name = role.name if role else ''
        appearance.loaded = None
        self.panels['profile'].loaded = role
        selector = self.panels['profile'].selector
        for index in range(selector.count()):
            item = selector.itemData(index)
            if item.path == role.path:
                selector.setItemData(index, role)
        for panel in self.panels.values():
            panel.dirty = self.dirty
            panel.select_loaded()
            panel.retranslate()
        self.settings.appearance_owner.setText(tr('正在调整：{name}', name=role.name))
        self.settings.set_appearance_source(self.entry.appearance_source)
        self.settings.personal_controls.save.setVisible(not self.state.autosave)
        self.settings.personal_controls.save.setEnabled(self.dirty)
        self.settings.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr('关闭') if self.state.autosave else tr('取消'))
        self.settings.appearance_history.undo.setEnabled(bool(self.entry.history))
        self.settings.appearance_history.recent.setEnabled(bool(self.entry.history))
        self.settings.profile_defaults.setEnabled(role is not None)

    def restore_history(self, index):
        try:
            entry = deepcopy(self.entry)
            config = entry.restore(index, self.draft(), self.directory)
            self.install(self.key, entry, config)
        except (OSError, ValueError, TypeError, IndexError, RuntimeError) as exc:
            self.settings.set_status(Message('无法恢复外观：{error}', error=exc))

    def show_history(self):
        from .preset_controls import show_history
        show_history(self.settings.appearance_history.recent, self.entry.history, self.restore_history)

    def default_config(self):
        if self.entry.source:
            from ...presets.profile import load_profile
            from ...presets.workspace import values_from_profile
            self.entry.defaults = values_from_profile(load_profile(self.entry.source.path.parent/'original/profile.json'))
            return apply_values(self.defaults, self.entry.defaults)
        return self.defaults

    def reset_parameter(self, path):
        try:
            self._reset_parameter(path)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            # 单项默认值可能与用户已修改的另一端冲突，不丢弃草稿或暗改关联参数
            self.settings.set_status(Message('无法恢复此项默认值：{error}', error=exc))

    def _reset_parameter(self, path):
        current = self.draft()
        defaults = self.default_config()
        keys = [key for key in ALL_PATHS if key == path or key.startswith(path+'.')]
        if path.endswith('.image_path'):
            prefix = path.removesuffix('.image_path')
            keys = [prefix+'.'+name for name in ('image_path', 'image_name', 'enabled')]
        # 本机参数同样支持单项恢复，但仍遵守显式保存边界
        if not keys:
            keys = [path]
        from ...presets.common import replace_fields, set_value
        values = {}
        for key in keys:
            set_value(values, key, get_value(defaults, key))
        config = replace_fields(current, values)
        with self.suspended():
            self.settings.fill_preset(config, keys)
        if any(key in ALL_PATHS for key in keys):
            self.changed(path)

    def restore_defaults(self, kind):
        try:
            current = self.draft()
            entry = deepcopy(self.entry)
            defaults = self.default_config()
            values = capture(defaults, kind, self.directory)
            config = apply_values(current, values)
            if normalized(capture(current, 'appearance', self.directory)) != normalized(
                    capture(config, 'appearance', self.directory)):
                entry.remember(current, self.directory)
            entry.appearance_name = ''
            entry.appearance_source = None
            entry.update(config, self.directory)
            self.install(self.key, entry, config)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.settings.set_status(Message('无法恢复外观：{error}', error=exc))

    def prepare_commit(self, config):
        self.timer.stop()
        entry = deepcopy(self.entry)
        entry.update(config, self.directory)
        config = apply_values(config, capture(config, entry.kind, self.directory))
        return config, entry, self.state.serialize(self.key, entry)

    def committed(self, config, entry):
        from ...presets.workspace import refresh_entry
        refresh_entry(entry)
        config = apply_values(config, entry.values)
        with self.suspended():
            self.settings.fill_preset(config, entry.values)
        self.applied, self.entry = config, entry
        self.state.committed(self.key, entry)
        self.dirty = False
        self.sync_ui()

    def before_close(self):
        self.timer.stop()
        return not self.state.autosave or not self.dirty or self.flush()
