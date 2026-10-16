"""个人调整的保存开关、外观历史和参数恢复入口"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from ...i18n import tr
from ...presets.common import get_value


class PersonalControls(QWidget):
    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.autosave = QCheckBox('自动保存修改')
        self.autosave.setToolTip('自动保存并应用当前角色的调整；关闭后切换角色或关闭设置会丢弃未保存修改；本机设置仍需点击保存并应用')
        self.save = QPushButton('保存当前调整')
        self.save.setAutoDefault(False)
        row.addWidget(self.autosave)
        row.addWidget(self.save)
        row.addStretch(1)
        row.addWidget(QLabel('右键参数可恢复默认值'))


class AppearanceHistoryControls(QWidget):
    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.undo = QPushButton('回退到导入前的上一外观')
        self.recent = QPushButton('回退到指定的历史外观…')
        self.reset = QPushButton('恢复默认外观')
        self.reset.setToolTip('恢复当前角色设置原本提供的外观，保留行为参数')
        # for button in (self.undo, self.recent, self.reset):
        for button in (self.undo, self.recent):
            button.setAutoDefault(False)
            row.addWidget(button)
        row.addStretch(1)


def show_history(button, history, restore):
    menu = QMenu(button)
    for index, item in enumerate(history):
        name = item['name'] or tr('切换前的外观')
        stamp = datetime.fromisoformat(item['time']).astimezone().strftime('%m-%d %H:%M:%S')
        action = menu.addAction(f'{name} - {stamp}')
        action.triggered.connect(lambda checked=False, i=index: restore(i))
    menu.exec(button.mapToGlobal(button.rect().bottomLeft()))


def bind_parameter_resets(settings, workflow, preview=None):
    """右键恢复复用字段路径，复合编辑器的每个子参数也可独立恢复"""
    def bind(widget, path):
        if widget.property('default_reset_bound'):
            return
        widget.setProperty('default_reset_bound', True)
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def context(point):
            menu = widget.createStandardContextMenu() if hasattr(widget, 'createStandardContextMenu') else QMenu(widget)
            if menu.actions():
                menu.addSeparator()
            default = get_value(workflow.default_config(), path)
            action = menu.addAction(tr('恢复此项默认值'))
            action.setToolTip(str(default))
            action.triggered.connect(lambda: workflow.reset_parameter(path))
            menu.exec(widget.mapToGlobal(point))
            menu.deleteLater()
        widget.customContextMenuRequested.connect(context)
        if hasattr(widget, 'lineEdit') and widget.lineEdit() is not None:
            bind(widget.lineEdit(), path)

    def children(editor, prefix):
        if hasattr(editor, 'parameter_controls'):
            for field, control in editor.parameter_controls.items():
                bind(control, prefix+'.'+field)
            return
        names = {'enabled': 'enabled', 'x_input': 'offset_x', 'y_input': 'offset_y',
                 'width_input': 'width', 'height_input': 'height', 'rotation_input': 'rotation',
                 'kind': 'kind', 'tone': 'tone', 'visible': 'visible', 'color': 'color',
                 'state': 'default_open', 'file_label': 'image_path'}
        for attribute, field in names.items():
            child = getattr(editor, attribute, None)
            if isinstance(child, QWidget):
                bind(child, prefix+'.'+field)

    if preview is not None:
        for group in (preview.face_editors, preview.ear_editors, preview.eye_editors):
            for name, editor in group.items():
                children(editor, 'oracle.custom_appearance.'+name)
        return
    for key, control in settings.controls.items():
        bind(control, key)
        children(control, key)
        if hasattr(getattr(control, 'group', None), 'buttons'):
            for button in control.group.buttons():
                bind(button, key)
    for key, editors in settings.color_editors.items():
        for editor in editors:
            bind(editor, key)
