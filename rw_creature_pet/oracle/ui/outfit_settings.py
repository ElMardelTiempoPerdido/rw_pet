"""附加外观的逐部件表单，字段直接接入设置窗口的保存与恢复流程"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .settings_style import NOTE_STYLE, parameter_group_background


MAID_PART_LABELS = (
    ('head', '显示头饰'),
    ('lace', '显示肩部花边'),
    ('apron', '显示围裙'),
    ('ribbon_up', '显示头部蝴蝶结'),
    ('ribbon_down', '显示胸口蝴蝶结'),
)


def build_outfit_settings(settings, form, config):
    panel = QWidget()
    panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    note = QLabel('位移使用逻辑像素，沿部件自身方向调整；正 X 向右、正 Y 向下，对称复制包含位移')
    note.setWordWrap(True)
    note.setStyleSheet(NOTE_STYLE)
    layout.addWidget(note)
    settings.outfit_parameter_panels = {'maid': panel}
    settings.outfit_part_groups = {}
    for part_id, title in MAID_PART_LABELS:
        values = getattr(config.outfit_settings.maid, part_id)
        prefix = 'oracle.outfit_settings.maid.'+part_id+'.'
        group = QWidget()
        parameter_group_background(group)
        row = QFormLayout(group)
        row.setContentsMargins(12, 12, 12, 12)
        row.setVerticalSpacing(14)
        row.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        row.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        left, right = settings.two_columns(row)
        settings.check(left, title, prefix+'enabled', values.enabled)
        settings.check(right, '水平对称复制', prefix+'mirror', values.mirror)
        left, right = settings.two_columns(row)
        for column, label, name in ((left, 'X 位移', 'offset_x'), (right, 'Y 位移', 'offset_y')):
            settings.spin(column, label, prefix+name, getattr(values, name), -32, 32,
                          decimals=1, step=.5, suffix=' px')
        columns = settings.parameter_columns(row, 3)
        for column, label, name, limit, suffix in zip(columns,
                ('色相', '饱和度', '明度'), ('hue', 'saturation', 'brightness'), (180, 100, 100), ('°', '%', '%')):
            settings.spin(column, label, prefix+name, getattr(values, name), -limit, limit, step=1, suffix=suffix)
            settings.controls[prefix+name].setToolTip('相对原图的增量，0 保持原色；灰白区域不受色相和饱和度影响')
        settings.controls[prefix+'enabled'].toggled.connect(settings.sync_dependencies)
        settings.outfit_part_groups[prefix] = group
        layout.addWidget(group)
    form.addRow(panel)
    settings.controls['oracle.outfit'].group.buttonToggled.connect(settings.sync_dependencies)


def sync_outfit_dependencies(settings):
    selected = settings.controls['oracle.outfit'].value()
    for outfit, panel in settings.outfit_parameter_panels.items():
        panel.setVisible(selected == outfit)
    for prefix in settings.outfit_part_groups:
        enabled = settings.controls[prefix+'enabled'].isChecked()
        for field in ('mirror', 'offset_x', 'offset_y', 'hue', 'saturation', 'brightness'):
            settings.controls[prefix+field].setEnabled(enabled)
