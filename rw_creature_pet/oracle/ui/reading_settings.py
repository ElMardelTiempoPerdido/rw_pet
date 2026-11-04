"""读珠选择、节奏和观察方式；不开放运动安全与矩阵占槽约束"""
from .behavior_fields import number_row, range_row, tooltips
from .behavior_proportions import proportion_group


READING_PERCENT_FIELDS = ('drift_probability', 'avoidance_probability', 'eye_open_probability', 'matrix_probability')


def build_reading_settings(dialog, form, oracle):
    config = oracle.reading
    prefix = 'oracle.reading.'
    rows = (
        (('start_probability', '停留后读珠概率', 0, 100, 1, ' %'),
         (('interval_min_seconds', 'interval_max_seconds'), '两轮读珠间隔', 0, 3600, 2, ' 秒')),
        (('avoidance_probability', '侧倾停稳后读珠概率', 0, 100, 1, ' %'),),
        (('drift_probability', '漫游时读珠概率', 0, 100, 1, ' %'),
         (('drift_delay_min_seconds', 'drift_delay_max_seconds'), '漫游首次读珠等待', .1, 3600, 2, ' 秒')),
        (None, (('drift_interval_min_seconds', 'drift_interval_max_seconds'), '漫游读珠尝试间隔', .1, 3600, 2, ' 秒')),
        ((('notice_min_seconds', 'notice_max_seconds'), '读珠准备时间', .1, 3600, 2, ' 秒'),
         (('observe_min_seconds', 'observe_max_seconds'), '普通阅读时间', .1, 3600, 2, ' 秒')),
        (('eye_open_probability', '阅读时睁眼概率', 0, 100, 1, ' %'),),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    proportion_group(dialog, form, config, prefix, ('matrix_probability',), ('固定珠', '矩阵珠'), mode='binary',
                     tooltip='两类珍珠同时存在时，按此比例选择；只有一种时使用现有种类，环绕珠和卫星珠不参与')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '珍珠播放动画概率', 'oracle.pearl_playback_probability', oracle.pearl_playback_probability * 100,
                0, 100, suffix=' %')
    range_row(dialog, right, config, prefix, ('playback_min_seconds', 'playback_max_seconds'),
              '播放动画阅读时间', .1, 3600, decimals=2, step=.1, suffix=' 秒')
    dialog.controls['oracle.pearl_playback_probability'].setToolTip(
        '人偶召近矩阵珠阅读时，触发播放动画的概率；只有特效，不播放音乐')
    tooltips(dialog, prefix, ('start_probability',),
             '普通停留结束且未选择跨边或漫游时，开始读珠的概率；不影响漫游期间、鼠标避让期间或手动触发的读珠')
    tooltips(dialog, prefix, ('interval_min_seconds', 'interval_max_seconds'),
             '从上一轮珍珠归位后计时，限制所有自主读珠；到期仍需等待行为选择，手动观察不受影响')
    tooltips(dialog, prefix, ('drift_probability',), '漫游读珠尝试到期且当前路线到位后独立抽签；未抽中则继续漫游并重新等待')
    tooltips(dialog, prefix, ('playback_min_seconds', 'playback_max_seconds'), '矩阵珠触发播放动画时替代普通阅读时长；不播放声音')
    dialog.controls[prefix+'drift_probability'].valueChanged.connect(dialog.sync_dependencies)


def build_pearl_interaction_settings(dialog, form, oracle):
    config = oracle.reading
    prefix = 'oracle.reading.'
    proportion_group(dialog, form, config, prefix, ('approach_weight', 'recall_weight', 'orbit_weight'),
                     ('靠近观察', '原地召近', '绕珠观察'),
                     tooltip='观察固定珠时按此比例选择；矩阵珠始终召近，不能移动或没有可行路线时也会改为召近')
    rows = (
        (('observe_distance', '靠近观察距离', 32, 150, 1, ' px'),
         ('recall_distance', '召近阅读距离', 30, 150, 1, ' px')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    left, _ = dialog.two_columns(form)
    dialog.spin(left, '人偶避让矩阵半径', 'oracle.pearl_matrix_avoid_radius', oracle.pearl_matrix_avoid_radius,
                0, 300, suffix=' px')
    dialog.controls['oracle.pearl_matrix_avoid_radius'].setToolTip(
        '*人偶会尽量与矩阵珍珠保持此距离，以避免重叠')
    left, right = dialog.two_columns(form)
    for column, label, name in ((left, '珍珠跟随范围宽度', 'pearl_follow_width'),
                               (right, '珍珠跟随范围高度', 'pearl_follow_height')):
        dialog.spin(column, label, 'oracle.'+name, getattr(oracle, name), 160, 4000, decimals=1, step=10, suffix=' px')
        dialog.controls['oracle.'+name].setToolTip('以人偶为中心的矩形范围，超出范围的珍珠会跟随迁移；数值为逻辑像素')
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
