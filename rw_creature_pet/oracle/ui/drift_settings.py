"""反重力漫游参数，不重复登记日常活动中的跨边设置"""
from .behavior_fields import number_row, range_row, tooltips
from .behavior_proportions import proportion_group

DRIFT_PERCENT_FIELDS = ('duration_variation', 'long_bout_probability')


def build_drift_settings(dialog, form, oracle):
    config = oracle.drift
    prefix = 'oracle.drift.'
    left, right = dialog.two_columns(form)
    dialog.spin(left, '漫游概率', 'oracle.antigravity_probability', oracle.antigravity_probability * 100,
                0, 100, decimals=1, suffix=' %')
    dialog.spin(right, '漫游冷却时间', prefix+'cooldown_seconds', config.cooldown_seconds,
                0, 3600, decimals=2, step=.1, suffix=' 秒')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '漫游时长', 'oracle.antigravity_duration_seconds', oracle.antigravity_duration_seconds,
                1, 3600, decimals=1, suffix=' 秒')
    dialog.spin(right, '漫游时长浮动', prefix+'duration_variation', config.duration_variation * 100,
                0, 50, decimals=1, suffix=' %')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '漂浮移速', 'oracle.drift_speed', oracle.drift_speed, .3, 1.8, decimals=2, step=.1)
    range_row(dialog, right, config, prefix, ('speed_min_factor', 'speed_max_factor'),
              '漂浮移速-随机倍率', .1, 2, decimals=2, step=.1, suffix=' ×')
    proportion_group(dialog, form, config, prefix, ('long_bout_probability',),
                     ('普通连续漂浮', '长段连续漂浮'), mode='binary')
                     # tooltip='每轮连续漂浮开始时，按此比例选择普通或长段时长，运动方式相同')
    rows = (
        ((('bout_min_seconds', 'bout_max_seconds'), '普通连续漂浮时间', .1, 3600, 2, ' 秒'),
         (('long_bout_min_seconds', 'long_bout_max_seconds'), '长段连续漂浮时间', .1, 3600, 2, ' 秒')),
        ((('move_min_distance', 'move_max_distance'), '漫游每段距离', 30, 1000, 1, ' px'),),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    proportion_group(dialog, form, config, prefix, ('short_pause_weight', 'normal_pause_weight', 'long_pause_weight'),
                     ('短暂停顿', '普通停顿', '长歇'))
    number_row(dialog, form, config, prefix, (
        (('short_pause_min_seconds', 'short_pause_max_seconds'), '短暂停顿时间', 0, 3600, 2, ' 秒'),
        (('normal_pause_min_seconds', 'normal_pause_max_seconds'), '普通停顿时间', 0, 3600, 2, ' 秒')))
    number_row(dialog, form, config, prefix, (
        (('long_pause_min_seconds', 'long_pause_max_seconds'), '长歇时间', 0, 3600, 2, ' 秒'),))
    # tooltips(dialog, prefix, ('cooldown_seconds',), '一次漫游结束后，至少等待此时间才允许再次自主触发')
    # tooltips(dialog, prefix, ('duration_variation',), '以漫游时长为中心上下浮动，例如 10% 表示 90%～110%；0 为固定时长')
    # tooltips(dialog, prefix, ('bout_min_seconds', 'bout_max_seconds'),
    #          '选中普通连续漂浮时使用此时长；在安全的路线终点停下，读珠或漫游到期可以提前接管')
    # tooltips(dialog, prefix, ('long_bout_min_seconds', 'long_bout_max_seconds'),
    #          '选中长段连续漂浮时使用此时长；在安全的路线终点停下，读珠或漫游到期可以提前接管')
    # tooltips(dialog, prefix, ('move_min_distance', 'move_max_distance'), '沿当前边每段路线的计划距离，实际落点受活动带与珍珠避让限制')
    # tooltips(dialog, prefix, ('speed_min_factor', 'speed_max_factor'), '每段独立抽取一次倍率，乘以漂浮移速；加减速、转弯与臂长限制保持有效')
