"""完整预设入口与其外观来源提示，复用预设库的选择和文件操作"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy

from ...i18n import tr
from ...presets.profile import load_profile
from ...presets.profile_library import ProfileLibrary
from .preset_panel import PresetPanel
from .settings_style import NOTE_STYLE


PROFILE_TEXTS = {
    'label': '完整预设', 'import_button': '导入完整预设…', 'export_button': '导出完整预设…',
    'hint': '包含行为参数和外观副本，保留本机偏好；选择后点击保存生效',
    'read_error': '无法读取完整预设库：{error}', 'current': '当前配置（不关联完整预设）',
    'duplicates': '重复完整预设「{name}」，使用日期最新的有效版本：\n{paths}',
    'load_error': '无法载入完整预设：{error}', 'loaded': '已载入完整预设及包内外观，点击保存后生效',
    'import_title': '导入完整预设', 'filter': '完整预设 (*.json)',
    'import_error': '导入完整预设失败：{error}', 'export_title': '导出完整预设',
    'name': '完整预设名称', 'default_name': '我的迭代器', 'export_error': '导出完整预设失败：{error}',
}


class ProfilePresetPanel(PresetPanel):
    editAppearance = Signal()

    def __init__(self, draft, apply, reference, *, library=None):
        self.reference = reference
        super().__init__(draft, apply, library=library or ProfileLibrary(), loader=load_profile,
                         texts=PROFILE_TEXTS, export_options=lambda: {'appearance_source': reference()})
        self.reference_label = QLabel()
        self.reference_label.setTextFormat(Qt.TextFormat.PlainText)
        self.reference_label.setWordWrap(True)
        self.reference_label.setStyleSheet(NOTE_STYLE)
        self.reference_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.layout().addWidget(self.reference_label)
        self.appearance_button = QPushButton('选择或调整外观')
        self.appearance_button.setAutoDefault(False)
        self.appearance_button.clicked.connect(self.editAppearance)
        self.layout().addWidget(self.appearance_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.refresh_reference()

    @property
    def dynamic_text_widgets(self):
        return (*super().dynamic_text_widgets, self.reference_label)

    def retranslate(self):
        super().retranslate()
        if hasattr(self, 'reference_label'):
            self.refresh_reference()

    def refresh_reference(self):
        source = self.reference()
        if source is None:
            text = tr('外观来源：当前编辑的外观，导出时创建独立副本')
        else:
            text = tr('外观来源：{name}\n导出时携带当前编辑后的副本，不自动跟随外观库更新', name=source.name)
        self.reference_label.setText(text)
        self.reference_label.setToolTip(str(source.path) if source else '')
