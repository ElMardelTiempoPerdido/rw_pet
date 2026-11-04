"""日常活动维度的参数控件，共用角色设置的保存与默认值入口"""
from .behavior_fields import number_row
from .behavior_proportions import proportion_group


def build_daily_activity_settings(dialog, form, oracle):
    config = oracle.daily_activity
    prefix = 'oracle.daily_activity.'
    proportion_group(dialog, form, config, prefix, ('idle_weight', 'meditate_weight', 'move_weight'),
                     ('停留', '冥想', '移动'), tooltip='未选择跨边、漫游或读珠时，按此比例选择活动')
    number_row(dialog, form, oracle, 'oracle.', (
        ('float_speed', '通常移动速度', .3, 2., 2, ''),
        ('base_speed', '底座滑动速度', 1.5, 4., 2, '')))
    rows = (
        ((('idle_min_seconds', 'idle_max_seconds'), '通常停留时间', .1, 3600, 1, ' 秒'),
         (('long_idle_min_seconds', 'long_idle_max_seconds'), '长停留时间', .1, 3600, 1, ' 秒')),
        ((('move_min_distance', 'move_max_distance'), '同边移动距离', 30, 1000, 1, ' px'),
         ('move_lean_degrees', '通常移动侧倾幅度', 0, 25, 1, ' °')),
        ((('meditate_min_seconds', 'meditate_max_seconds'), '冥想时间', .1, 3600, 1, ' 秒'),),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    for bound in ('min', 'max'):
        dialog.controls[prefix+'idle_'+bound+'_seconds'].setToolTip('启动或活动结束后，身体停稳才开始计时')
        dialog.controls[prefix+'long_idle_'+bound+'_seconds'].setToolTip('选择继续停留或找不到可行路线时，等待此范围内的随机时间')
        dialog.controls[prefix+'move_'+bound+'_distance'].setToolTip('同边短途移动的计划距离，实际距离会受活动带、可达范围和珍珠避让限制')
        dialog.controls[prefix+'meditate_'+bound+'_seconds'].setToolTip('身体和视线停稳后，保持冥想的随机时间')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '跨到相邻边概率', 'oracle.cross_edge_probability', oracle.cross_edge_probability * 100,
                0, 100, decimals=1, suffix=' %')
    dialog.spin(right, '跨边冷却时间', prefix+'cross_edge_cooldown_seconds',
                config.cross_edge_cooldown_seconds, 0, 3600, decimals=1, suffix=' 秒')
    _, right = dialog.two_columns(form)
    dialog.spin(right, '漫游跨边尝试间隔', prefix+'cross_edge_check_seconds',
                config.cross_edge_check_seconds, 1, 3600, decimals=1, suffix=' 秒')
    dialog.controls[prefix+'cross_edge_cooldown_seconds'].setToolTip('普通移动与漫游共用，到达相邻边后才开始冷却')
    dialog.controls[prefix+'cross_edge_check_seconds'].setToolTip('漫游只在选择下一段路线时尝试跨边，两次尝试至少间隔此时间')
    dialog.controls[prefix+'move_lean_degrees'].setToolTip('随横向移动速度逐渐侧倾，不影响鼠标躲避倾角或失重漫游姿态')
