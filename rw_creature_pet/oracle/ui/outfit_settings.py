"""附加外观的逐部件表单，字段直接接入设置窗口的保存与恢复流程"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...i18n import language_manager, tr
from ..outfit_layout import Anchor, Slot, allowed_slots, resolved_slot
from .inputs import WheelSafeComboBox
from .settings_style import NOTE_STYLE, parameter_group_background
from .form_layout import ContentForm


MAID_PART_LABELS = (
    ('head', '显示头饰'),
    ('lace', '显示肩部花边'),
    ('apron', '显示围裙'),
    ('ribbon_up', '显示头部蝴蝶结'),
    ('ribbon_down', '显示胸口蝴蝶结'),
)

ANCHOR_LABELS = ((Anchor.HEAD_CROWN, '头顶'), (Anchor.BODY_COLLAR, '身体领口'),
                 (Anchor.GOWN_COLLAR, '衣袍领口'))
LAYER_LABELS = ((Slot.BEHIND_HEAD, '头部下方'), (Slot.FRONT_HEAD, '头部上方'),
                (Slot.BEFORE_SLEEVES, '衣袍上方且袖子下方'),
                (Slot.AFTER_SLEEVES, '袖子上方且斗篷下方'),
                (Slot.AFTER_CAPE, '斗篷上方且项链下方'), (Slot.FRONT, '最前层'))


class OutfitChoice(WheelSafeComboBox):
    """保留完整值集合供角色载入，只在下拉列表展示当前部位可用项"""
    def __init__(self, choices, value):
        super().__init__()
        self.choices = choices
        self.setSizeAdjustPolicy(self.SizeAdjustPolicy.AdjustToContents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for key, label in choices:
            self.addItem(tr(label), key)
        self.setCurrentIndex(self.findData(value))
        language_manager().changed.connect(self.retranslate)

    def retranslate(self):
        for key, label in self.choices:
            self.setItemText(self.findData(key), tr(label))

    def restrict(self, anchor):
        allowed = allowed_slots(anchor)
        selected = resolved_slot(anchor, self.currentData())
        for index in range(self.count()):
            valid = self.itemData(index) in allowed
            self.view().setRowHidden(index, not valid)
            self.model().item(index).setEnabled(valid)
        self.setCurrentIndex(self.findData(selected))


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
        row = ContentForm(group)
        row.setContentsMargins(12, 12, 12, 12)
        row.setVerticalSpacing(14)
        row.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        row.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        left, right = settings.two_columns(row)
        settings.check(left, title, prefix+'enabled', values.enabled)
        settings.check(right, '水平对称复制', prefix+'mirror', values.mirror)
        left, right = settings.two_columns(row)
        for column, label, name, choices in ((left, '锚点', 'anchor', ANCHOR_LABELS),
                                             (right, '层级', 'layer', LAYER_LABELS)):
            control = OutfitChoice(choices, getattr(values, name))
            settings.controls[prefix+name] = control
            column.addRow(label, control)
        settings.controls[prefix+'anchor'].setToolTip(
            '头顶随头部运动，身体领口随胸肩运动，衣袍领口随衣袍摆动；切换锚点保留 X/Y 位移')
        settings.controls[prefix+'layer'].setToolTip(
            '层级按锚点所属部位提供；围裙在身体部位仍裁剪到衣物范围，移到头顶时解除衣物裁剪')
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
        settings.controls[prefix+'anchor'].currentIndexChanged.connect(
            lambda _index, p=prefix: sync_part_layers(settings, p))
        sync_part_layers(settings, prefix)
    form.addRow(panel)
    settings.controls['oracle.outfit'].group.buttonToggled.connect(settings.sync_dependencies)


def sync_part_layers(settings, prefix):
    settings.controls[prefix+'layer'].restrict(settings.controls[prefix+'anchor'].currentData())


def sync_outfit_dependencies(settings):
    selected = settings.controls['oracle.outfit'].value()
    for outfit, panel in settings.outfit_parameter_panels.items():
        panel.setVisible(selected == outfit)
    for prefix in settings.outfit_part_groups:
        sync_part_layers(settings, prefix)
        enabled = settings.controls[prefix+'enabled'].isChecked()
        for field in ('anchor', 'layer', 'mirror', 'offset_x', 'offset_y', 'hue', 'saturation', 'brightness'):
            settings.controls[prefix+field].setEnabled(enabled)
