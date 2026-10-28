"""角色设置入口，复用预设库的选择和文件操作"""
from pathlib import Path
import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QMenu, QPushButton

from ...presets.profile import load_profile
from ...presets.profile_library import ProfileLibrary
from ...presets.startup import BELL_PROFILE_ID, default_bell
from ...settings_store import load_defaults
from ...presets.sharing import content_key, open_profile
from ...shared.messages import Message
from ...i18n import tr
from .preset_panel import PresetPanel
from .preset_dialogs import ProfileConflictDialog


PROFILE_TEXTS = {
    'label': '当前使用角色', 'import_button': '导入角色设置…', 'export_button': '导出分享此角色',
    'share_hint': '强烈建议使用此按钮分享角色；自行压缩角色文件夹可能遗漏资源或包含历史设置',
    'hint': '【角色设置】包含迭代器的【外观】与【影响行动风格的设置项】',
    'read_error': '无法读取角色设置库：{error}', 'current': '当前角色设置（不关联文件）',
    'duplicates': '重复角色设置「{name}」，最新有效版本列在第一项：\n{paths}',
    'load_error': '无法载入角色设置：{error}', 'loaded': '已加载当前选中的角色设置！',
    'import_title': '导入角色设置', 'filter': '角色设置 (*.zip *.json)',
    'import_error': '导入角色设置失败：{error}', 'export_title': '导出角色设置',
    'name': '角色设置名称', 'default_name': '迭代器名称111', 'export_error': '导出角色设置失败：{error}',
}


class ProfilePresetPanel(PresetPanel):
    createCharacter = Signal()

    def __init__(self, draft, apply, reference, *, library=None):
        self.ready = False
        self.before_import = lambda: None
        super().__init__(draft, apply, library=library or ProfileLibrary(), loader=load_profile,
                         texts=PROFILE_TEXTS, export_options=lambda: {'appearance_source': reference()})
        self.create_button = QPushButton('新建角色…')
        self.create_button.setAutoDefault(False)
        self.create_button.clicked.connect(self.createCharacter)
        self.layout().itemAt(1).layout().insertWidget(0, self.create_button)
        self.import_button.clicked.disconnect(self.choose_import)
        menu = QMenu(self.import_button)
        self.import_actions = [(menu.addAction('从 ZIP 或 JSON 文件导入…', self.choose_import), '从 ZIP 或 JSON 文件导入…'),
                               (menu.addAction('从角色文件夹导入…', self.choose_import_directory), '从角色文件夹导入…')]
        self.import_button.setMenu(menu)
        self.ready = True

    def retranslate(self):
        super().retranslate()
        for action, source in getattr(self, 'import_actions', ()):
            action.setText(tr(source))

    def choose_import_directory(self):
        path = QFileDialog.getExistingDirectory(self, tr('选择角色文件夹'))
        if path:
            self.import_file(path)

    def resolve_conflict(self, existing):
        dialog = ProfileConflictDialog(self, existing.name)
        return dialog.selection if dialog.exec() == QDialog.DialogCode.Accepted else None

    def import_file(self, path, *, conflict=None):
        try:
            with open_profile(path) as source:
                self.before_import()
                source_key = content_key(source)
                if self.loader(source.path).revision != source.revision:
                    raise ValueError('目标文件已被修改，请刷新后重新选择')
                existing = next((item for item in self.library.scan().presets if item.id == source.id), None)
                existing_key = content_key(existing) if existing is not None else None
                if existing is not None and existing_key != source_key and conflict is None:
                    conflict = self.resolve_conflict(existing)
                    if conflict is None:
                        return False
                if content_key(self.loader(source.path)) != source_key or (existing is not None and (
                        self.loader(existing.path).revision != existing.revision or content_key(existing) != existing_key)):
                    raise ValueError('目标文件已被修改，请刷新后重新选择')
                with self.library.import_transaction(source.path, conflict=conflict) as installed:
                    self.apply(installed)
                    selected = self.loader(installed.path)
        except (OSError, ValueError, TypeError, RecursionError, RuntimeError) as exc:
            self.select_loaded()
            self.set_message(Message(self.texts['import_error'], error=exc))
            return False
        self.set_loaded(selected)
        self.set_message(self.texts['loaded'])
        return True

    def choose_export(self, *, config=None):
        if self.loaded is None:
            return False
        name = self.loaded.name
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or 'character'
        path, _ = QFileDialog.getSaveFileName(self, tr('导出分享此角色'), filename+'.zip', tr('角色分享包 (*.zip)'))
        if not path:
            return False
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix('.zip')
        return self.export_current(name, destination=destination, config=config) is not None

    def export_current(self, name, *, destination, config=None):
        try:
            config = self.draft() if config is None else config
            output = self.library.export_share(config, destination, name=name,
                preset_id=self.loaded.id, **self.export_options())
        except (OSError, ValueError, TypeError, RecursionError, RuntimeError) as exc:
            self.set_message(Message(self.texts['export_error'], error=exc))
            return None
        self.set_message(Message('已导出分享包：{path}', path=str(output)))
        return output

    def refresh(self, selected_id=None):
        try:
            report = self.library.scan()
            if not report.presets and not report.errors:
                preset = self.library.export(default_bell(load_defaults()), '手势之铃', preset_id=BELL_PROFILE_ID)
                if self.ready:
                    self.apply(preset)
                    self.loaded = preset
                report = self.library.scan()
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.set_message(exc)
            return False
        return super().refresh(selected_id, report=report)
