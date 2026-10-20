"""斗篷槽位的参数组，使用外观字段的统一自动保存与恢复流程"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QSizePolicy, QWidget

from ..cape_config import CAPE_RANGES
from .outfit_settings import OutfitChoice
from .settings_style import parameter_group_background
from .form_layout import ContentForm


PREFIX = 'oracle.custom_appearance.cape.'


def build_cape_settings(settings, form, cape):
    group = QWidget()
    parameter_group_background(group)
    group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    row = ContentForm(group)
    row.setContentsMargins(12, 12, 12, 12)
    row.setVerticalSpacing(14)
    row.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    row.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    left, right = settings.two_columns(row)
    settings.check(left, '启用斗篷', PREFIX+'enabled', cape.enabled)
    settings.color(right, '斗篷颜色', PREFIX+'color', cape.color)
    left, right = settings.two_columns(row)
    settings.spin(left, '斗篷长度', PREFIX+'length', cape.length, *CAPE_RANGES['length'],
                  decimals=1, step=1., suffix=' px')
    settings.controls[PREFIX+'length'].setToolTip('自然下垂时，从肩部上缘到下摆最低点的长度')
    selector = OutfitChoice((('arc', '弧形'), ('v', 'V 型')), cape.neckline_shape)
    settings.controls[PREFIX+'neckline_shape'] = selector
    right.addRow('斗篷领口形状', selector)
    for labels in ((('领口宽度', 'neckline_width'), ('领口深度', 'neckline_depth')),
                   (('领口起始高度', 'neckline_height'), ('弧形圆润度', 'neckline_roundness')),
                   (('V 型尖端圆角', 'neckline_tip_radius'),)):
        for column, (label, name) in zip(settings.two_columns(row), labels):
            ratio = name == 'neckline_roundness'
            settings.spin(column, label, PREFIX+name, getattr(cape, name), *CAPE_RANGES[name],
                          decimals=2 if ratio else 1, step=.05 if ratio else .5,
                          suffix='' if ratio else ' px')
    settings.controls[PREFIX+'neckline_height'].setToolTip(
        '相对胸部中心，正值向头部、负值向下摆；深度从此高度向下测量，修改宽度不会改变此高度')
    left, right = settings.two_columns(row)
    settings.check(left, '显示底边彩边', PREFIX+'hem_trim_enabled', cape.hem_trim_enabled)
    settings.color(right, '底边彩边颜色', PREFIX+'hem_trim_color', cape.hem_trim_color)
    for column, label, name in zip(settings.two_columns(row),
                                    ('底边彩边宽度', '彩边与底边距离'), ('hem_trim_width', 'hem_trim_gap')):
        settings.spin(column, label, PREFIX+name, getattr(cape, name), *CAPE_RANGES[name],
                      decimals=1, step=.5, suffix=' px')
    settings.controls[PREFIX+'hem_trim_gap'].setToolTip('0 为贴边包边，大于 0 时向斗篷内侧留出间隔')
    for name in ('enabled', 'hem_trim_enabled'):
        settings.controls[PREFIX+name].toggled.connect(lambda: sync_cape_settings(settings))
    selector.currentIndexChanged.connect(lambda: sync_cape_settings(settings))
    form.addRow(group)
    settings.cape_group = group
    sync_cape_settings(settings)


def sync_cape_settings(settings):
    c = settings.controls
    enabled = c[PREFIX+'enabled'].isChecked()
    arc = c[PREFIX+'neckline_shape'].currentData() == 'arc'
    trim = c[PREFIX+'hem_trim_enabled'].isChecked()
    for key, control in c.items():
        if key.startswith(PREFIX) and key != PREFIX+'enabled':
            name = key.removeprefix(PREFIX)
            active = enabled
            if name == 'neckline_roundness':
                active = active and arc
            elif name == 'neckline_tip_radius':
                active = active and not arc
            elif name in ('hem_trim_color', 'hem_trim_width', 'hem_trim_gap'):
                active = active and trim
            control.setEnabled(active)
