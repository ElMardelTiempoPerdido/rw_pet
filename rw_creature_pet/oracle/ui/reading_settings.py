"""读珠选择、节奏和观察方式；不开放运动安全与矩阵占槽约束"""
from .behavior_fields import number_row, tooltips


READING_PERCENT_FIELDS = ('drift_probability', 'avoidance_probability', 'eye_open_probability', 'matrix_probability')


def build_reading_settings(dialog, form, config):
    prefix = 'oracle.reading.'
    ranges = (
        ('interval', '两轮读珠间隔最短', '两轮读珠间隔最长', 0),
        ('drift_delay', '漫游首次读珠等待最短', '漫游首次读珠等待最长', .1),
        ('drift_interval', '漫游读珠尝试间隔最短', '漫游读珠尝试间隔最长', .1),
        ('notice', '读珠准备时间最短', '读珠准备时间最长', .1),
        ('observe', '普通阅读时间最短', '普通阅读时间最长', .1),
        ('playback', '播放动画阅读时间最短', '播放动画阅读时间最长', .1),
    )
    for name, low_label, high_label, minimum in ranges:
        for column, bound, label in zip(dialog.two_columns(form), ('min', 'max'), (low_label, high_label)):
            field = name+'_'+bound+'_seconds'
            dialog.spin(column, label, prefix+field, getattr(config, field), minimum, 3600,
                        decimals=2, step=.1, suffix=' 秒')
    rows = (
        (('drift_probability', '漫游时读珠概率', 0, 100, 1, ' %'),
         ('avoidance_probability', '侧倾停稳后读珠概率', 0, 100, 1, ' %')),
        (('eye_open_probability', '阅读时睁眼概率', 0, 100, 1, ' %'),
         ('matrix_probability', '选取矩阵珠比例', 0, 100, 1, ' %')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    tooltips(dialog, prefix, ('interval_min_seconds', 'interval_max_seconds'),
             '从上一轮珍珠归位后计时，限制所有自主读珠；到期仍需等待行为选择，手动观察不受影响')
    tooltips(dialog, prefix, ('drift_probability',), '漫游读珠尝试到期且当前路线到位后独立抽签；未抽中则继续漫游并重新等待')
    tooltips(dialog, prefix, ('matrix_probability',), '同时存在矩阵珠与固定珠时的选择比例；只有一种时使用现有种类，环绕珠和卫星珠不参与')
    tooltips(dialog, prefix, ('playback_min_seconds', 'playback_max_seconds'), '矩阵珠触发播放动画时替代普通阅读时长；不播放声音')
    dialog.controls[prefix+'drift_probability'].valueChanged.connect(dialog.sync_dependencies)


def build_pearl_interaction_settings(dialog, form, config):
    prefix = 'oracle.reading.'
    rows = (
        (('approach_weight', '靠近观察权重', 0, 100, 1, ''),
         ('recall_weight', '原地召近权重', 0, 100, 1, '')),
        (('orbit_weight', '绕珠观察权重', 0, 100, 1, ''),),
        (('observe_distance', '靠近观察距离', 32, 150, 1, ' px'),
         ('recall_distance', '召近阅读距离', 30, 150, 1, ' px')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    tooltips(dialog, prefix, ('approach_weight', 'recall_weight', 'orbit_weight'),
             '仅用于固定珠的自动观察，按相对权重选择，不能同时为 0；矩阵珠始终召近，禁止移动或无可行路线时也改为召近')
    tooltips(dialog, prefix, ('observe_distance', 'recall_distance'), '期望距离，单位为逻辑像素；活动区、身体和机械臂避让优先，找不到安全位置则结束并归位')


def sync_reading_dependencies(dialog, character):
    c = dialog.controls
    matrix = c['oracle.pearl_matrix_enabled'].isChecked() and c['oracle.pearl_matrix_count'].value() > 0
    fixed = c['oracle.pearl_fixed_count'].value() > 0
    for path, control in c.items():
        if path.startswith('oracle.reading.'):
            control.setEnabled(matrix or fixed)
    prefix = 'oracle.reading.'
    c[prefix+'eye_open_probability'].setEnabled((matrix or fixed) and character.has_eyes)
    c[prefix+'matrix_probability'].setEnabled(matrix and fixed)
    c[prefix+'avoidance_probability'].setEnabled((matrix or fixed) and c['interaction.hover_avoidance_enabled'].isChecked())
    for name in ('drift_delay', 'drift_interval'):
        for bound in ('min', 'max'):
            c[prefix+name+'_'+bound+'_seconds'].setEnabled((matrix or fixed) and c[prefix+'drift_probability'].value() > 0)
    for name in ('approach_weight', 'recall_weight', 'orbit_weight', 'observe_distance'):
        c[prefix+name].setEnabled(fixed)
    for bound in ('min', 'max'):
        c[prefix+'playback_'+bound+'_seconds'].setEnabled(matrix and c['oracle.pearl_playback_probability'].value() > 0)
