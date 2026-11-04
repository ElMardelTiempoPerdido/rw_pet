"""拖动表情常显参数，不属于拖动动作风格或高级参数面板"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QSizePolicy, QWidget

from ..drag_expression_config import EXPRESSION_KINDS
from ..eye_config import EYE_KINDS
from .form_layout import ContentForm
from .inputs import WheelSafeSpinBox
from .settings_style import NOTE_STYLE

PREFIX = 'oracle.drag_expressions.'


def build_drag_expression_settings(dialog, root, config):
    panel = dialog.drag_expression_panel = QWidget()
    panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    form = ContentForm(panel)
    form.setContentsMargins(0, 0, 0, 0)
    form.setVerticalSpacing(root.verticalSpacing())
    form.addRow(QLabel('拖动表情'))
    dialog.spin(form, '拖动出现表情概率', PREFIX+'probability', config.probability*100,
                0, 100, decimals=1, suffix=' %')
    table = QWidget()
    grid = QGridLayout(table)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(8)
    for column, label in enumerate(('眼睛形态', '启用', '权重', '仅大幅拖动时出现')):
        grid.addWidget(QLabel(label), 0, column)
    for row, (kind, label) in enumerate(EYE_KINDS[1:], 1):
        choice = getattr(config, kind)
        name = QLabel(label)
        name.setTextFormat(Qt.TextFormat.PlainText)
        grid.addWidget(name, row, 0)
        for column, field in ((1, 'enabled'), (3, 'large_only')):
            toggle = QCheckBox()
            toggle.setChecked(getattr(choice, field))
            toggle.setAccessibleName(label+' '+('启用' if field == 'enabled' else '仅大幅拖动时出现'))
            dialog.controls[PREFIX+kind+'.'+field] = toggle
            grid.addWidget(toggle, row, column)
        weight = WheelSafeSpinBox()
        weight.setRange(0, 1000)
        weight.setValue(choice.weight)
        weight.setKeyboardTracking(False)
        weight.setAccessibleName(label+' '+'权重')
        dialog.controls[PREFIX+kind+'.weight'] = weight
        grid.addWidget(weight, row, 2)
        dialog.controls[PREFIX+kind+'.enabled'].toggled.connect(dialog.sync_dependencies)
    grid.setColumnStretch(4, 1)
    form.addRow(table)
    # note = QLabel('只从已启用且权重大于 0 的眼形中抽取；全部关闭时不出现表情')
    # note.setStyleSheet(NOTE_STYLE)
    # note.setWordWrap(True)
    # note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    # form.addRow(note)
    dialog.controls[PREFIX+'probability'].setToolTip('每次随机尝试时的触发概率，与手势、睁眼、语音和投影独立')
    # table.setToolTip('大幅拖动按近期鼠标移动范围判定，不受人偶缩放或机械臂伸展限制')
    root.addRow(panel)


def sync_drag_expression_settings(dialog, character):
    controls = dialog.controls
    controls[PREFIX+'probability'].setEnabled(character.has_eyes)
    for kind in EXPRESSION_KINDS:
        enabled = controls[PREFIX+kind+'.enabled']
        enabled.setEnabled(character.has_eyes)
        for field in ('weight', 'large_only'):
            controls[PREFIX+kind+'.'+field].setEnabled(character.has_eyes and enabled.isChecked())
