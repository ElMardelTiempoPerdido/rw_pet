"""预设库共用的选择、刷新、导入导出和草稿提交边界"""
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ...i18n import tr
from ...presets.catalog import same_preset, selection_options
from ...shared.messages import Message
from .inputs import WheelSafeComboBox
from .settings_style import NOTE_STYLE
from .preset_dialogs import PresetSaveDialog


class PresetPanel(QWidget):
    loadedChanged = Signal(object)

    def __init__(self, draft, apply, *, library, loader, texts, export_options=None, inline_selection=True):
        super().__init__()
        self.library, self.loader, self.texts = library, loader, texts
        self.export_options = export_options or (lambda: {})
        self.draft, self.apply = draft, apply
        self.loaded = None
        self.owner_name = ''
        self.dirty = False
        self.after_export = lambda preset: None
        self.report = None
        self.message = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.selection_panel = QWidget(self)
        row = QHBoxLayout(self.selection_panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(self.texts['label']))
        self.selector = WheelSafeComboBox()
        self.selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.selector.setMinimumContentsLength(10)
        self.selector.setSizeAdjustPolicy(self.selector.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.selector, 1)
        self.refresh_button = QPushButton('刷新')
        row.addWidget(self.refresh_button)
        layout.addWidget(self.selection_panel)
        self.selection_panel.setVisible(inline_selection)
        actions = QHBoxLayout()
        self.import_button = QPushButton(self.texts['import_button'])
        self.export_button = QPushButton(self.texts['export_button'])
        self.directory_button = QPushButton('打开文件夹')
        for button in (self.import_button, self.export_button, self.directory_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        share_actions = None
        if self.texts.get('share_hint'):
            actions.removeWidget(self.export_button)
            share_actions = QHBoxLayout()
            share_actions.addWidget(self.export_button)
            self.share_hint = QLabel(self.texts['share_hint'])
            self.share_hint.setWordWrap(True)
            self.share_hint.setStyleSheet(NOTE_STYLE)
            self.share_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            share_actions.addWidget(self.share_hint, 1)
        self.refresh_button.setAutoDefault(False)
        actions.addStretch(1)
        layout.addLayout(actions)
        if share_actions is not None:
            layout.addLayout(share_actions)
        # hint = QLabel(self.texts['hint'])
        # hint.setStyleSheet(NOTE_STYLE)
        # hint.setWordWrap(True)
        # layout.addWidget(hint)
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

    def refresh(self, selected_id=None, *, report=None):
        try:
            self.report = report if report is not None else self.library.scan()
        except (OSError, ValueError) as exc:
            self.set_message(Message(self.texts['read_error'], error=exc))
            return False
        self.selector.clear()
        loaded = self.loaded if selected_id is None and not self.owner_name else None
        for preset, retained in selection_options(self.report.presets, loaded):
            self.selector.addItem(preset.name, preset)
            index = self.selector.count()-1
            self.selector.setItemData(index, str(preset.path), Qt.ItemDataRole.ToolTipRole)
            self.selector.setItemData(index, retained, Qt.ItemDataRole.UserRole+1)
            if preset.id == selected_id:
                self.selector.setCurrentIndex(index)
        if selected_id is None:
            self.select_loaded()
        self.retranslate()
        return True

    def select_loaded(self):
        """刷新不替换当前草稿，也不把同 ID 的新版本冒充成已载入版本"""
        if self.loaded is None or self.owner_name:
            self.selector.setCurrentIndex(-1)
            return
        for index in range(self.selector.count()):
            item = self.selector.itemData(index)
            if same_preset(item, self.loaded):
                self.selector.setCurrentIndex(index)
                return
        self.selector.addItem(self.loaded.name+tr('（已载入版本）'), self.loaded)
        index = self.selector.count()-1
        self.selector.setItemData(index, True, Qt.ItemDataRole.UserRole+1)
        self.selector.setItemData(index, str(self.loaded.path), Qt.ItemDataRole.ToolTipRole)
        self.selector.setCurrentIndex(index)

    def set_loaded(self, preset):
        self.loaded = preset
        self.loadedChanged.emit(preset)
        self.refresh()

    def retranslate(self):
        for index in range(self.selector.count()):
            item = self.selector.itemData(index)
            suffix = tr('（已载入版本）') if self.selector.itemData(index, Qt.ItemDataRole.UserRole+1) else ''
            self.selector.setItemText(index, item.name+suffix)
        index = self.selector.currentIndex()
        if self.dirty and index >= 0:
            self.selector.setItemText(index, self.selector.itemText(index)+' *')
        messages = []
        if self.report is not None:
            for group in self.report.duplicates:
                messages.append(tr(self.texts['duplicates'],
                                   name=group[0].name, paths='\n'.join(str(item.path) for item in group)))
            for path, error in self.report.errors:
                messages.append(tr('已跳过无效配置文件：{path}\n{error}', path=str(path), error=error))
        self.warning.setText('\n\n'.join(messages))
        self.warning.setVisible(bool(messages))
        self.set_message(self.message)

    def set_message(self, message):
        self.message = message
        self.status.setText(tr(message))
        self.status.setVisible(bool(message))

    def clear_selection(self):
        # 角色必须始终保持选中，刷新不会解除当前角色
        self.select_loaded()

    def choose(self, index):
        selected = self.selector.itemData(index)
        if selected is None:
            self.clear_selection()
            return
        try:
            # 再次读取文件，防止刷新后被移动、修改或删除
            preset = self.loader(selected.path)
            if self.loader(preset.path).revision != preset.revision:
                raise ValueError('目标文件已被修改，请刷新后重新选择')
            self.apply(preset)
        except (OSError, ValueError, TypeError, RecursionError, RuntimeError) as exc:
            self.select_loaded()
            self.set_message(Message(self.texts['load_error'], error=exc))
            return False
        self.set_loaded(preset)
        self.set_message(self.texts['loaded'])
        return True

    def choose_import(self):
        path, _ = QFileDialog.getOpenFileName(self, tr(self.texts['import_title']), '', tr(self.texts['filter']))
        if path:
            self.import_file(path)

    def import_file(self, path):
        try:
            source = self.loader(path)
            report = self.library.scan()
            # 导入旧副本时仍使用同 ID 的最新有效版本，在提示前明确真正的载入对象
            existing = next((item for item in report.presets if item.id == source.id), None)
            preset = existing if existing and existing.timestamp >= source.timestamp else source
            if (self.loader(source.path).revision != source.revision or
                    self.loader(preset.path).revision != preset.revision):
                raise ValueError('目标文件已被修改，请刷新后重新选择')
            copied = self.library.import_file(source.path)
            preset = preset if preset is existing else copied
            self.apply(preset)
        except (OSError, ValueError, TypeError, RecursionError, RuntimeError) as exc:
            self.select_loaded()
            self.set_message(Message(self.texts['import_error'], error=exc))
            return False
        self.set_loaded(preset)
        self.set_message(self.texts['loaded'])
        return True

    def choose_export(self, *, config=None):
        if not self.refresh():
            return False
        dialog = PresetSaveDialog(self, self.report.presets, self.loaded,
                                  self.texts['export_title'], self.texts['default_name'])
        def save(name, target):
            result = self.export_current(name, target=target, config=config)
            return result is not None, self.message
        dialog.on_save = save
        return dialog.exec() == QDialog.DialogCode.Accepted

    def export_current(self, name, *, target=None, config=None):
        try:
            config = self.draft() if config is None else config
            if target is None:
                preset = self.library.export(config, name, **self.export_options())
            else:
                preset = self.library.update(config, target, name=name, **self.export_options())
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.set_message(Message(self.texts['export_error'], error=exc))
            return
        self.set_loaded(preset)
        try:
            self.after_export(preset)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.set_message(Message('文件已导出，但当前调整尚未保存：{error}', error=exc))
            return preset
        self.set_message(Message('已导出至：{path}', path=str(preset.path.parent)))
        return preset

    def open_directory(self):
        try:
            self.library.directory.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.directory.resolve()))):
                raise OSError(tr('无法打开文件夹'))
        except OSError as exc:
            self.set_message(exc)
