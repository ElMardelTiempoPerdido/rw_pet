"""行为参数的普通数值与范围行，提交仍交给设置窗口统一处理"""
from PySide6.QtWidgets import QLabel

from .number_range import NumberRange


def number_row(dialog, form, config, prefix, fields):
    """每项占半行，字段名为一对时显示范围；None 保留半列空白"""
    for column, field in zip(dialog.two_columns(form), fields):
        if field is None:
            continue
        name, label, minimum, maximum, decimals, suffix = field
        if isinstance(name, tuple):
            range_row(dialog, column, config, prefix, name, label, minimum, maximum,
                      decimals=decimals, step=.1 if decimals >= 2 else 1, suffix=suffix)
            continue
        value = getattr(config, name)
        if suffix == ' %':
            value *= 100
        dialog.spin(column, label, prefix+name, value, minimum, maximum, decimals=decimals,
                    step=.1 if decimals >= 2 else 1, suffix=suffix)


def range_row(dialog, form, config, prefix, names, label, minimum, maximum, *, decimals=1, step=1, suffix=''):
    controls = []
    for name in names:
        value = getattr(config, name)
        if suffix == ' %':
            value *= 100
        controls.append(dialog.spin_control(prefix+name, value, minimum, maximum,
                                           decimals=decimals, step=step, suffix=suffix))
    field = NumberRange(*controls)
    title = QLabel(label)
    title.setBuddy(field)  # 资源缺失时，两端共用同一处“不可用”标签
    form.addRow(title, field)
    return field


def tooltips(dialog, prefix, names, text):
    for name in names:
        dialog.controls[prefix+name].setToolTip(text)
