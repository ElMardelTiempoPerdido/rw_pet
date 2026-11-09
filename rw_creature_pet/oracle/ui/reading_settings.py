"""读珠选择、节奏和观察方式；不开放运动安全与矩阵占槽约束"""
from .behavior_fields import number_row, range_row, tooltips
from .behavior_proportions import proportion_group

READING_PERCENT_FIELDS = ('eye_open_probability', 'matrix_probability')


def build_reading_settings(dialog, form, oracle):
    config = oracle.reading
    prefix = 'oracle.reading.'
    rows = (
        (('start_probability', '读珍珠概率', 0, 100, 1, ' %'),
         (('attempt_min_seconds', 'attempt_max_seconds'), '读珍珠抽取间隔', 0, 3600, 2, ' 秒')),
        ((('observe_min_seconds', 'observe_max_seconds'), '普通阅读时间', .1, 3600, 2, ' 秒'),
         ('eye_open_probability', '阅读时睁眼概率', 0, 100, 1, ' %')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    proportion_group(dialog, form, config, prefix, ('matrix_probability',), ('固定珠', '矩阵珠'), mode='binary')
    # tooltip='两类珍珠同时存在时，按此比例选择；只有一种时使用现有种类，环绕珠和卫星珠不参与')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '珍珠播放动画概率', 'oracle.pearl_playback_probability', oracle.pearl_playback_probability * 100,
                0, 100, suffix=' %')
    range_row(dialog, right, config, prefix, ('playback_min_seconds', 'playback_max_seconds'),
              '播放动画阅读时间', .1, 3600, decimals=2, step=.1, suffix=' 秒')
    dialog.controls['oracle.pearl_playback_probability'].setToolTip(
        '类似赞美诗珍珠的播放光晕特效（并不会实际播放bgm')
    # tooltips(dialog, prefix, ('start_probability',),
    #          '停留、漫游和躲避停稳后共用此概率；到达尝试时间且可以阅读时抽取一次，手动观察不受影响')
    # tooltips(dialog, prefix, ('attempt_min_seconds', 'attempt_max_seconds'),
    #          '启动、未抽中阅读或珍珠归位后，等待此范围内的随机时间再尝试；切换行动不重置，到期也不会打断正在进行的行动')
    # tooltips(dialog, prefix, ('playback_min_seconds', 'playback_max_seconds'), '矩阵珠触发播放动画时替代普通阅读时长；不播放声音')
    dialog.controls[prefix + 'start_probability'].valueChanged.connect(dialog.sync_dependencies)


def build_pearl_interaction_settings(dialog, form, oracle):
    config = oracle.reading
    prefix = 'oracle.reading.'
    proportion_group(dialog, form, config, prefix, ('approach_weight', 'recall_weight', 'orbit_weight'),
                     ('靠近珍珠', '移来珍珠', '环绕珍珠'))
    rows = (
        (('observe_distance', '靠近观察距离', 32, 150, 1, ' px'),
         ('recall_distance', '召近阅读距离', 30, 150, 1, ' px')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    # tooltips(dialog, prefix, ('observe_distance', 'recall_distance'),
    #          '期望距离，单位为逻辑像素；活动区、身体和机械臂避让优先，找不到安全位置则结束并归位')


def sync_reading_dependencies(dialog, character):
    c = dialog.controls
    matrix = c['oracle.pearl_matrix_enabled'].isChecked() and c['oracle.pearl_matrix_count'].value() > 0
    fixed = c['oracle.pearl_fixed_count'].value() > 0
    for path, control in c.items():
        if path.startswith('oracle.reading.'):
            control.setEnabled(matrix or fixed)
    prefix = 'oracle.reading.'
    c[prefix + 'eye_open_probability'].setEnabled((matrix or fixed) and character.has_eyes)
    c[prefix + 'matrix_probability'].setEnabled(matrix and fixed)
    for bound in ('min', 'max'):
        c[prefix + 'attempt_' + bound + '_seconds'].setEnabled(
            (matrix or fixed) and c[prefix + 'start_probability'].value() > 0)
    for name in ('approach_weight', 'recall_weight', 'orbit_weight', 'observe_distance'):
        c[prefix + name].setEnabled(matrix or fixed)
    for bound in ('min', 'max'):
        c[prefix + 'playback_' + bound + '_seconds'].setEnabled(
            matrix and c['oracle.pearl_playback_probability'].value() > 0)
