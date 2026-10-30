"""反重力漫游参数，不重复登记日常活动中的跨边设置"""
from .behavior_fields import number_row, tooltips

DRIFT_PERCENT_FIELDS = ('duration_variation', 'long_bout_probability')


def build_drift_settings(dialog, form, config):
    prefix = 'oracle.drift.'
    rows = (
        (('cooldown_seconds', '漫游冷却时间', 0, 3600, 2, ' 秒'),
         ('duration_variation', '漫游时长浮动', 0, 50, 1, ' %')),
        (('entry_min_seconds', '入场等待最短时间', 0, 3600, 2, ' 秒'),
         ('entry_max_seconds', '入场等待最长时间', 0, 3600, 2, ' 秒')),
        (('resume_min_seconds', '恢复漫游最短等待', 0, 3600, 2, ' 秒'),
         ('resume_max_seconds', '恢复漫游最长等待', 0, 3600, 2, ' 秒')),
        (('short_pause_min_seconds', '短暂停顿最短时间', 0, 3600, 2, ' 秒'),
         ('short_pause_max_seconds', '短暂停顿最长时间', 0, 3600, 2, ' 秒')),
        (('normal_pause_min_seconds', '普通停顿最短时间', 0, 3600, 2, ' 秒'),
         ('normal_pause_max_seconds', '普通停顿最长时间', 0, 3600, 2, ' 秒')),
        (('long_pause_min_seconds', '长歇最短时间', 0, 3600, 2, ' 秒'),
         ('long_pause_max_seconds', '长歇最长时间', 0, 3600, 2, ' 秒')),
        (('short_pause_weight', '短暂停顿权重', 0, 100, 1, ''),
         ('normal_pause_weight', '普通停顿权重', 0, 100, 1, '')),
        (('long_pause_weight', '长歇权重', 0, 100, 1, ''),
         ('long_bout_probability', '长段漂浮概率', 0, 100, 1, ' %')),
        (('bout_min_seconds', '连续漂浮最短时间', .1, 3600, 2, ' 秒'),
         ('bout_max_seconds', '连续漂浮最长时间', .1, 3600, 2, ' 秒')),
        (('long_bout_min_seconds', '长段漂浮最短时间', .1, 3600, 2, ' 秒'),
         ('long_bout_max_seconds', '长段漂浮最长时间', .1, 3600, 2, ' 秒')),
        (('move_min_distance', '漫游每段最短距离', 30, 1000, 1, ' px'),
         ('move_max_distance', '漫游每段最长距离', 30, 1000, 1, ' px')),
        (('speed_min_factor', '漫游速度最低倍率', .1, 2, 2, ' ×'),
         ('speed_max_factor', '漫游速度最高倍率', .1, 2, 2, ' ×')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    tooltips(dialog, prefix, ('cooldown_seconds',), '一次漫游结束后，至少等待此时间才允许再次自主触发')
    tooltips(dialog, prefix, ('duration_variation',), '以漫游时长为中心上下浮动，例如 10% 表示 90%～110%；0 为固定时长')
    tooltips(dialog, prefix, ('entry_min_seconds', 'entry_max_seconds'), '进入失重漫游后，第一段移动前的随机等待')
    tooltips(dialog, prefix, ('resume_min_seconds', 'resume_max_seconds'), '读珠、跨边或鼠标躲避结束后，接续漫游前的随机等待')
    tooltips(dialog, prefix, ('short_pause_weight', 'normal_pause_weight', 'long_pause_weight'),
             '按相对权重选择停顿档位，不能同时为 0；通常避免连续两次长歇，只启用长歇时允许重复')
    tooltips(dialog, prefix, ('bout_min_seconds', 'bout_max_seconds', 'long_bout_min_seconds', 'long_bout_max_seconds'),
             '一轮连续漂浮的目标时长，到达安全的路线终点后才停下，不会半途急停；读珠或漫游到期可以提前接管')
    tooltips(dialog, prefix, ('move_min_distance', 'move_max_distance'), '沿当前边每段路线的计划距离，实际落点受活动带与珍珠避让限制')
    tooltips(dialog, prefix, ('speed_min_factor', 'speed_max_factor'), '每段独立抽取一次倍率，乘以漫游移动速度；加减速、转弯与臂长限制保持有效')
