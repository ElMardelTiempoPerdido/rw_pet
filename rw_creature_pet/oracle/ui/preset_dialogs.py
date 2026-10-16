"""外观与角色设置共用的分享文件另存、更新选择"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout)

from ...i18n import tr
from .inputs import WheelSafeComboBox
from .settings_style import apply_settings_style


def acknowledge_character_upgrade(parent=None):
    box = QMessageBox(parent)
    box.setWindowTitle(tr('保留原有设置'))
    box.setText(tr('检测到旧版的珍珠、行动等设置。确认后，会将这些设置保留为「手势之铃」的个人调整。\n'
                   '你仍可右键点击参数，恢复为该角色提供的默认值。'))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText(tr('确认'))
    apply_settings_style(box)
    box.exec()


class AppearanceImportDialog(QDialog):
    """浏览仅改变候选，确认后才导入当前角色"""
    def __init__(self, panel):
        super().__init__(panel.window())
        self.panel = panel
        self.setWindowTitle(tr('导入外观到当前角色设置'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        hint = QLabel(tr('仅替换当前角色的外观，保留行为参数；可通过外观历史恢复'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.selector = WheelSafeComboBox()
        self.selector.setMinimumContentsLength(24)
        layout.addWidget(self.selector)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setTextFormat(Qt.TextFormat.PlainText)
        self.warning.setStyleSheet('color: #a64949;')
        layout.addWidget(self.warning)
        file_button = QPushButton(tr('从文件选择…'))
        file_button.setAutoDefault(False)
        file_button.clicked.connect(self.choose_file)
        layout.addWidget(file_button)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('导入'))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        panel.refresh()
        if panel.report:
            for preset in panel.report.presets:
                self.selector.addItem(preset.name, preset.path)
                self.selector.setItemData(self.selector.count()-1, str(preset.path), Qt.ItemDataRole.ToolTipRole)
        self.warning.setText(panel.warning.text() or (tr('没有可用的外观，请从文件选择') if not self.selector.count() else ''))
        self.selector.currentIndexChanged.connect(self.refresh)
        self.refresh()
        apply_settings_style(self)
        self.resize(540, self.sizeHint().height())

    def refresh(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.selector.currentData() is not None)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('选择外观文件'), '', tr('外观配置 (*.json)'))
        if not path:
            return
        try:
            preset = self.panel.loader(path)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.warning.setText(tr('无法载入外观：{error}', error=exc))
            return
        index = self.selector.findData(preset.path)
        if index < 0:
            self.selector.addItem(preset.name, preset.path)
            index = self.selector.count()-1
            self.selector.setItemData(index, str(preset.path), Qt.ItemDataRole.ToolTipRole)
        self.selector.setCurrentIndex(index)
        self.refresh()

    def submit(self):
        path = self.selector.currentData()
        if path is not None and self.panel.import_file(path):
            self.accept()
        else:
            self.warning.setText(tr(self.panel.message))


class NewCharacterDialog(QDialog):
    def __init__(self, parent, create):
        super().__init__(parent)
        self.create = create
        self.setWindowTitle(tr('古人工程师模拟器'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        hint = QLabel(tr('这个迭代器叫什么名字？'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.name = QLineEdit(tr('新建迭代器111'))
        self.name.setMaxLength(80)
        form.addRow(tr('名称'), self.name)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('创建'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_settings_style(self)
        self.resize(540, self.sizeHint().height())

    def submit(self):
        try:
            self.create(self.name.text())
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.error.setText(tr('无法新建角色：{error}', error=exc))
            return
        self.accept()


class PresetSaveDialog(QDialog):
    def __init__(self, parent, presets, source, title, default_name):
        super().__init__(parent)
        self.on_save = None
        self.setWindowTitle(tr(title))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        form = QFormLayout()
        form.setSpacing(12)
        self.mode = WheelSafeComboBox()
        self.mode.addItem(tr('另存为新文件'), 'new')
        if presets:
            self.mode.addItem(tr('更新已有文件'), 'update')
        form.addRow(tr('保存方式'), self.mode)
        self.target = WheelSafeComboBox()
        self.target.setMinimumContentsLength(20)
        for preset in presets:
            self.target.addItem(preset.name, preset)
            self.target.setItemData(self.target.count()-1, str(preset.path), Qt.ItemDataRole.ToolTipRole)
        self.name = QLineEdit(source.name if source else tr(default_name))
        self.name.setMaxLength(80)
        form.addRow(tr('覆盖文件'), self.target)
        form.addRow(tr('名称'), self.name)
        
        layout.addLayout(form)
        self.path = QLabel()
        self.path.setWordWrap(True)
        self.path.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.path)
        # hint = QLabel(tr('更新会替换所选文件的内容；另存会创建一份独立的新文件'))
        # hint.setWordWrap(True)
        # layout.addWidget(hint)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.error.hide()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr('保存'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self.select_target)
        self.target.currentIndexChanged.connect(self.select_target)
        index = next((i for i, preset in enumerate(presets) if source is not None and preset.id == source.id), -1)
        if index >= 0:
            self.target.setCurrentIndex(index)
            self.mode.setCurrentIndex(1)
        self.refresh()
        apply_settings_style(self)
        self.resize(540, self.sizeHint().height())

    def select_target(self):
        if self.mode.currentData() == 'update' and self.target.currentData() is not None:
            self.name.setText(self.target.currentData().name)
        self.refresh()

    def refresh(self):
        updating = self.mode.currentData() == 'update'
        self.target.setEnabled(updating)
        preset = self.target.currentData()
        self.path.setText(str(preset.path) if updating and preset else '')
        self.path.setVisible(updating)

    @property
    def selection(self):
        return self.name.text(), self.target.currentData() if self.mode.currentData() == 'update' else None

    def submit(self):
        if self.on_save is not None:
            success, error = self.on_save(*self.selection)
            if not success:
                self.error.setText(tr(error))
                self.error.show()
                return
        self.accept()
