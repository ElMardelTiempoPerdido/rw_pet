"""日常活动维度的参数控件，共用角色设置的保存与默认值入口"""


def build_daily_activity_settings(dialog, form, config):
    prefix = 'oracle.daily_activity.'
    ranges = (
        ('通常停留最短时间', '通常停留最长时间', 'idle', 'seconds', .1, 3600, ' 秒'),
        ('长停留最短时间', '长停留最长时间', 'long_idle', 'seconds', .1, 3600, ' 秒'),
        ('同边移动最短距离', '同边移动最长距离', 'move', 'distance', 30, 1000, ' px'),
        ('冥想最短时间', '冥想最长时间', 'meditate', 'seconds', .1, 3600, ' 秒'),
    )
    for low_label, high_label, name, unit, minimum, maximum, suffix in ranges:
        for column, label, bound in zip(dialog.two_columns(form), (low_label, high_label), ('min', 'max')):
            field = name+'_'+bound+'_'+unit
            dialog.spin(column, label, prefix+field, getattr(config, field), minimum, maximum,
                        decimals=1, suffix=suffix)
    for bound in ('min', 'max'):
        dialog.controls[prefix+'idle_'+bound+'_seconds'].setToolTip('启动或活动结束后，身体停稳才开始计时')
        dialog.controls[prefix+'long_idle_'+bound+'_seconds'].setToolTip('选择继续停留或找不到可行路线时，等待此范围内的随机时间')
        dialog.controls[prefix+'move_'+bound+'_distance'].setToolTip('同边短途移动的计划距离，实际距离会受活动带、可达范围和珍珠避让限制')
        dialog.controls[prefix+'meditate_'+bound+'_seconds'].setToolTip('身体和视线停稳后，保持冥想的随机时间')
    weights = (('停留倾向权重', 'idle_weight'), ('移动倾向权重', 'move_weight'),
               ('冥想倾向权重', 'meditate_weight'))
    for start in range(0, len(weights), 2):
        for column, (label, name) in zip(dialog.two_columns(form), weights[start:start+2]):
            dialog.spin(column, label, prefix+name, getattr(config, name), 0, 100, decimals=1)
            dialog.controls[prefix+name].setToolTip('未选择跨边、漫游或读珠时，按三个权重的比例选择活动；不要求合计为 100，不能同时为 0')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '跨边冷却时间', prefix+'cross_edge_cooldown_seconds',
                config.cross_edge_cooldown_seconds, 0, 3600, decimals=1, suffix=' 秒')
    dialog.spin(right, '漫游跨边尝试间隔', prefix+'cross_edge_check_seconds',
                config.cross_edge_check_seconds, 1, 3600, decimals=1, suffix=' 秒')
    dialog.controls[prefix+'cross_edge_cooldown_seconds'].setToolTip('普通移动与漫游共用，到达相邻边后才开始冷却')
    dialog.controls[prefix+'cross_edge_check_seconds'].setToolTip('漫游只在选择下一段路线时尝试跨边，两次尝试至少间隔此时间')
    left, _ = dialog.two_columns(form)
    dialog.spin(left, '通常移动侧倾幅度', prefix+'move_lean_degrees', config.move_lean_degrees,
                0, 25, decimals=1, suffix=' °')
    dialog.controls[prefix+'move_lean_degrees'].setToolTip('随横向移动速度逐渐侧倾，不影响鼠标躲避倾角或失重漫游姿态')
