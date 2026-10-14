"""外观库选择与导入导出，选中后只填入父设置窗口的草稿"""
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ...i18n import tr
from ...presets.appearance import load_appearance
from ...presets.library import AppearanceLibrary
from ...shared.messages import Message
from .inputs import WheelSafeComboBox
from .settings_style import NOTE_STYLE


class AppearancePresetPanel(QWidget):
    def __init__(self, draft, apply, *, library=None):
        super().__init__()
        self.library = library or AppearanceLibrary()
        self.draft, self.apply = draft, apply
        self.loaded = None
        self.report = None
        self.message = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel('外观预设'))
        self.selector = WheelSafeComboBox()
        self.selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.selector.setMinimumContentsLength(10)
        self.selector.setSizeAdjustPolicy(self.selector.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.selector, 1)
        self.refresh_button = QPushButton('刷新')
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        actions = QHBoxLayout()
        self.import_button = QPushButton('导入外观…')
        self.export_button = QPushButton('导出外观…')
        self.directory_button = QPushButton('打开预设目录')
        for button in (self.import_button, self.export_button, self.directory_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.refresh_button.setAutoDefault(False)
        actions.addStretch(1)
        layout.addLayout(actions)
        hint = QLabel('选择预设会填入外观参数，保存后生效；分享时请复制整个预设文件夹')
        hint.setStyleSheet(NOTE_STYLE)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.warning = QLabel()
        self.status = QLabel()
        for label in (self.warning, self.status):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            layout.addWidget(label)
        self.warning.setStyleSheet('color: #a64949; font-size: 12px;')
        self.status.setStyleSheet(NOTE_STYLE)
        self.selector.activated.connect(self.choose)
        self.refresh_button.clicked.connect(lambda: self.refresh())
        self.import_button.clicked.connect(self.choose_import)
        self.export_button.clicked.connect(self.choose_export)
        self.directory_button.clicked.connect(self.open_directory)
        self.refresh()

    @property
    def dynamic_text_widgets(self):
        return (self.selector, self.warning, self.status)

    def refresh(self, selected_id=None):
        if selected_id is None and self.loaded is not None:
            selected_id = self.loaded.id
        try:
            self.report = self.library.scan()
        except (OSError, ValueError) as exc:
            self.set_message(Message('无法读取外观库：{error}', error=exc))
            return False
        self.selector.clear()
        self.selector.addItem(tr('当前外观（不关联预设）'), None)
        for preset in self.report.presets:
            self.selector.addItem(preset.name, preset)
            index = self.selector.count()-1
            self.selector.setItemData(index, str(preset.path), Qt.ItemDataRole.ToolTipRole)
            if preset.id == selected_id:
                self.selector.setCurrentIndex(index)
        if self.selector.currentIndex() == 0:
            self.loaded = None
        self.retranslate()
        return True

    def retranslate(self):
        self.selector.setItemText(0, tr('当前外观（不关联预设）'))
        messages = []
        if self.report is not None:
            for group in self.report.duplicates:
                messages.append(tr('重复外观「{name}」，使用日期最新的有效版本：\n{paths}',
                                   name=group[0].name, paths='\n'.join(str(item.path) for item in group)))
            for path, error in self.report.errors:
                messages.append(tr('已跳过无效预设：{path}\n{error}', path=str(path), error=error))
        self.warning.setText('\n\n'.join(messages))
        self.warning.setVisible(bool(messages))
        self.set_message(self.message)

    def set_message(self, message):
        self.message = message
        self.status.setText(tr(message))
        self.status.setVisible(bool(message))

    def choose(self, index):
        selected = self.selector.itemData(index)
        if selected is None:
            self.loaded = None
            return
        try:
            # 再次读取文件，防止刷新后被移动、修改或删除
            preset = load_appearance(selected.path)
            self.apply(preset)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.selector.setCurrentIndex(next((i for i in range(1, self.selector.count())
                if self.loaded is not None and self.selector.itemData(i).id == self.loaded.id), 0))
            self.set_message(Message('无法载入外观：{error}', error=exc))
            return
        self.loaded = preset
        self.set_message('已载入外观，点击保存后生效')

    def choose_import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('导入外观'), '', tr('外观配置 (*.json)'))
        if path:
            self.import_file(path)

    def import_file(self, path):
        try:
            preset = self.library.import_file(path)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.set_message(Message('导入外观失败：{error}', error=exc))
            return
        if self.refresh(preset.id):
            self.choose(self.selector.currentIndex())

    def choose_export(self):
        name, accepted = QInputDialog.getText(self, tr('导出外观'), tr('外观名称'),
                                             text=self.loaded.name if self.loaded else tr('我的外观'))
        if accepted:
            self.export_current(name)

    def export_current(self, name):
        try:
            preset = self.library.export(self.draft(), name,
                                         preset_id=self.loaded.id if self.loaded else None)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.set_message(Message('导出外观失败：{error}', error=exc))
            return
        self.loaded = preset
        self.refresh(preset.id)
        self.set_message(Message('已导出至：{path}', path=str(preset.path.parent)))
        return preset

    def open_directory(self):
        try:
            self.library.directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.directory.resolve()))):
                raise OSError(tr('无法打开文件夹'))
        except OSError as exc:
            self.set_message(exc)
