"""托盘角色快捷切换，复用设置页的角色列表与编辑会话"""
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ...i18n import tr
from ...presets.personal import PersonalState, read_link
from ...presets.startup import CharacterInitialization
from ...presets.catalog import file_stamp, same_preset, selection_options
from ...presets.profile_library import ProfileLibrary
from ...settings_store import SettingsStore


def runtime_character(config, store):
    """运行期间保留已载入角色，即使用户移动或删除了它的分享文件"""
    state = PersonalState(store.load_preset_state())
    entry = state.entries.get(state.active)
    if entry is not None and entry.kind == 'profile' and entry.source is not None:
        return CharacterInitialization(config, state)
    return None


class CharacterMenu(QMenu):
    def __init__(self, window):
        super().__init__(tr('切换角色'), window)
        self.desktop = window
        self.library = ProfileLibrary()
        self._active_stamp = None
        self._active = None
        self.aboutToShow.connect(self.refresh)

    def active_source(self):
        """仅读取活动角色来源，不构造或校验全部个人调整和历史记录"""
        store = self.desktop.config_store or SettingsStore()
        stamp = store.path, file_stamp(store.path)
        if stamp != self._active_stamp:
            state = store.load_preset_state()
            entry = state.get('entries', {}).get(state.get('active'), {})
            self._active = read_link(entry.get('source')) if entry.get('kind') == 'profile' else None
            self._active_stamp = stamp if file_stamp(store.path) == stamp[1] else None
        return self._active

    def refresh(self):
        self.clear()
        window = self.desktop
        try:
            dialog = window.settings_dialog
            if dialog is not None:
                panel = dialog.profile_presets
                state = dialog.preset_workflow.state
                active = state.entries[state.active].source
                loaded, dirty, library = panel.loaded, panel.dirty, panel.library
            else:
                active = loaded = self.active_source()
                dirty, library = False, self.library
            report = library.scan()
            options = selection_options(report.presets, loaded)
            if active is not None and not any(same_preset(preset, active) for preset, _ in options):
                options.append((active, True))
            for preset, retained in options:
                name = preset.name + (tr('（已载入版本）') if retained else '')
                if dirty and same_preset(preset, loaded):
                    name += ' *'
                action = self.addAction(name)
                action.setCheckable(True)
                action.setChecked(same_preset(preset, active))
                action.setToolTip(str(preset.path))
                action.setEnabled(dialog is None or dialog.worker is None)
                action.triggered.connect(lambda checked=False, selected=preset: self.choose(selected))
            if not options:
                self.addAction(tr('打开设置菜单'), window.open_settings)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            action = self.addAction(tr('无法读取角色设置库：{error}', error=exc))
            action.setEnabled(False)

    def choose(self, selected):
        window = self.desktop
        temporary = window.settings_dialog is None
        dialog = None
        try:
            dialog = window.ensure_settings_dialog()
            if dialog.worker is not None:
                return
            panel = dialog.profile_presets
            loaded = panel.loaded
            if loaded is not None and (loaded.path, loaded.revision) == (selected.path, selected.revision):
                if dialog.preset_workflow.dirty and not dialog.preset_workflow.flush():
                    raise ValueError(tr(dialog._status_message))
                return
            # 复用 choose 的文件重读、错误回退和角色缓存流程
            index = next((i for i in range(panel.selector.count())
                          if panel.selector.itemData(i).path == selected.path), -1)
            if index < 0:
                panel.selector.addItem(selected.name, selected)
                index = panel.selector.count()-1
            if not panel.choose(index):
                raise ValueError(tr(panel.message))
            # 托盘选择是明确的应用操作，自动保存关闭时也提交这次角色切换
            if dialog.preset_workflow.dirty and not dialog.preset_workflow.flush():
                raise ValueError(tr(dialog._status_message))
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            window.tray.showMessage(tr('切换角色'), str(exc), QSystemTrayIcon.MessageIcon.Warning)
            if dialog is not None:
                window.open_settings()  # 保留失败的草稿，供用户检查与重试
                temporary = False
        finally:
            if temporary and dialog is not None:
                dialog.shutdown()
                if window.settings_dialog is dialog:
                    window.settings_closed()
