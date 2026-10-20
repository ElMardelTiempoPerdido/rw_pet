"""角色设置入口，复用预设库的选择和文件操作"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton

from ...presets.profile import load_profile
from ...presets.profile_library import ProfileLibrary
from ...presets.startup import BELL_PROFILE_ID, default_bell
from ...settings_store import load_defaults
from .preset_panel import PresetPanel


PROFILE_TEXTS = {
    'label': '当前使用角色', 'import_button': '导入角色设置…', 'export_button': '导出角色设置…',
    'hint': '【角色设置】包含迭代器的【外观】与【影响行动风格的设置项】',
    'read_error': '无法读取角色设置库：{error}', 'current': '当前角色设置（不关联文件）',
    'duplicates': '重复角色设置「{name}」，最新有效版本列在第一项：\n{paths}',
    'load_error': '无法载入角色设置：{error}', 'loaded': '已加载当前选中的角色设置！',
    'import_title': '导入角色设置', 'filter': '角色设置 (*.json)',
    'import_error': '导入角色设置失败：{error}', 'export_title': '导出角色设置',
    'name': '角色设置名称', 'default_name': '迭代器名称111', 'export_error': '导出角色设置失败：{error}',
}


class ProfilePresetPanel(PresetPanel):
    createCharacter = Signal()

    def __init__(self, draft, apply, reference, *, library=None):
        self.ready = False
        super().__init__(draft, apply, library=library or ProfileLibrary(), loader=load_profile,
                         texts=PROFILE_TEXTS, export_options=lambda: {'appearance_source': reference()})
        self.create_button = QPushButton('新建角色…')
        self.create_button.setAutoDefault(False)
        self.create_button.clicked.connect(self.createCharacter)
        self.layout().itemAt(1).layout().insertWidget(0, self.create_button)
        self.ready = True

    def refresh(self, selected_id=None):
        try:
            report = self.library.scan()
            if not report.presets:
                preset = self.library.export(default_bell(load_defaults()), '手势之铃', preset_id=BELL_PROFILE_ID)
                if self.ready:
                    self.apply(preset)
                    self.loaded = preset
                report = self.library.scan()
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.set_message(exc)
            return False
        return super().refresh(selected_id, report=report)
