"""行为参数共用的双列表单行，提交仍交给设置窗口统一处理"""


def number_row(dialog, form, config, prefix, fields):
    for column, (name, label, minimum, maximum, decimals, suffix) in zip(dialog.two_columns(form), fields):
        value = getattr(config, name)
        if suffix == ' %':
            value *= 100
        dialog.spin(column, label, prefix+name, value, minimum, maximum, decimals=decimals,
                    step=.1 if decimals >= 2 else 1, suffix=suffix)


def tooltips(dialog, prefix, names, text):
    for name in names:
        dialog.controls[prefix+name].setToolTip(text)
