"""鼠标关注沿用通用参数，人偶躲避风格使用独立配置"""
from .behavior_fields import number_row, tooltips

AVOIDANCE_PERCENT_FIELDS = ('probability', 'move_probability', 'lean_move_probability')


def build_mouse_avoidance_settings(dialog, form, config):
    prefix = 'oracle.mouse_avoidance.'
    rows = (
        (('probability', '躲避触发概率', 0, 100, 1, ' %'),
         (('delay_min_seconds', 'delay_max_seconds'), '躲避触发延迟', 0, 60, 2, ' 秒')),
        (('enter_distance', '躲避进入距离', 1, 980, 1, ' px'),
         ('exit_distance', '躲避退出距离', 21, 1000, 1, ' px')),
        ((('retry_min_seconds', 'retry_max_seconds'), '连续躲避间隔', .05, 60, 2, ' 秒'),
         ('leave_grace_seconds', '回正延迟', 0, 60, 2, ' 秒')),
        ((('lean_min_degrees', 'lean_max_degrees'), '侧倾幅度', 0, 85, 1, ' °'),
         ('lean_sample_power', '倾角大小偏好', .1, 10, 2, '')),
        (('pointer_lag_seconds', '侧倾滞后', .01, 5, 2, ' 秒'),
         ('lean_speed', '侧倾速度', 1, 360, 1, ' °/s')),
        (('lean_move_probability', '侧倾伴随移动概率', 0, 100, 1, ' %'),
         (('lean_move_min_distance', 'lean_move_max_distance'), '伴随移动距离', 3, 1000, 1, ' px')),
        ((('impatience_min_seconds', 'impatience_max_seconds'), '不耐烦时间', .1, 60, 2, ' 秒'),
        ('move_probability', '不耐烦后移动概率', 0, 100, 1, ' %')),
        ((('move_min_distance', 'move_max_distance'), '躲避移动距离', 6, 1000, 1, ' px'),
         (('speed_min', 'speed_max'), '躲避移动速度', .1, 5, 2, '')),
        (('move_angle_jitter', '躲避移动偏角', 0, 80, 1, ' °'),),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    tooltips(dialog, prefix, ('delay_min_seconds', 'delay_max_seconds', 'probability'),
             '发现鼠标后，等待此时间后开始躲避')
    tooltips(dialog, prefix, ('leave_grace_seconds',), '鼠标离开后，延迟此时间才回正')
    tooltips(dialog, prefix, ('pointer_lag_seconds',), '影响检测鼠标位置并侧倾躲避的跟随灵敏度，值越大越迟缓')
    tooltips(dialog, prefix, ('retry_min_seconds', 'retry_max_seconds'), '所有类型躲避行为的抽取间隔')
    tooltips(dialog, prefix, ('impatience_min_seconds', 'impatience_max_seconds'), '鼠标靠近持续此时间后，人偶进入不耐烦状态')
    tooltips(dialog, prefix, ('move_probability',), '不耐烦后，每次抽取短移动的概率')

    tooltips(dialog, prefix, ('lean_move_probability',), '倾斜躲避同时触发移动的概率')
    tooltips(dialog, prefix, ('move_angle_jitter',), '向远离鼠标方向移动躲避时，路线会此范围内随机偏转')

    tooltips(dialog, prefix, ('lean_sample_power',), '大于1更偏好小倾角，小于1 更偏好大倾角')
    tooltips(dialog, prefix, ('lean_speed',), '侧倾躲避鼠标时，每秒改变的角度')
