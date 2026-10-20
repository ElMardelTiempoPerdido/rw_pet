"""鼠标关注沿用通用参数，人偶躲避风格使用独立配置"""
from .behavior_fields import number_row, tooltips

AVOIDANCE_PERCENT_FIELDS = ('probability', 'move_probability', 'lean_move_probability')


def build_mouse_avoidance_settings(dialog, form, config):
    prefix = 'oracle.mouse_avoidance.'
    rows = (
        (('delay_min_seconds', '躲避触发最短延迟', 0, 60, 2, ' 秒'),
         ('delay_max_seconds', '躲避触发最长延迟', 0, 60, 2, ' 秒')),
        (('probability', '躲避触发概率', 0, 100, 1, ' %'),
         ('move_probability', '不耐烦后移动概率', 0, 100, 1, ' %')),
        (('enter_distance', '躲避进入距离', 1, 980, 1, ' px'),
         ('exit_distance', '躲避退出距离', 21, 1000, 1, ' px')),
        (('leave_grace_seconds', '离开后的回正等待', 0, 60, 2, ' 秒'),
         ('pointer_lag_seconds', '侧倾跟随滞后', .01, 5, 2, ' 秒')),
        (('retry_min_seconds', '连续躲避最短间隔', .05, 60, 2, ' 秒'),
         ('retry_max_seconds', '连续躲避最长间隔', .05, 60, 2, ' 秒')),
        (('impatience_min_seconds', '不耐烦最短时间', .1, 60, 2, ' 秒'),
         ('impatience_max_seconds', '不耐烦最长时间', .1, 60, 2, ' 秒')),
        (('move_min_distance', '躲避移动最短距离', 6, 1000, 1, ' px'),
         ('move_max_distance', '躲避移动最长距离', 6, 1000, 1, ' px')),
        (('speed_min', '躲避移动最低速度', .1, 5, 2, ''),
         ('speed_max', '躲避移动最高速度', .1, 5, 2, '')),
        (('lean_move_probability', '侧倾伴随移动概率', 0, 100, 1, ' %'),
         ('move_angle_jitter', '移动方向随机偏角', 0, 80, 1, ' °')),
        (('lean_move_min_distance', '伴随移动最短距离', 3, 1000, 1, ' px'),
         ('lean_move_max_distance', '伴随移动最长距离', 3, 1000, 1, ' px')),
        (('lean_min_degrees', '侧倾幅度下限', 0, 85, 1, ' °'),
         ('lean_max_degrees', '侧倾幅度上限', 0, 85, 1, ' °')),
        (('lean_sample_power', '小倾角偏好', .1, 10, 2, ''),
         ('lean_speed', '侧倾目标跟随速度', 1, 360, 1, ' °/s')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    tooltips(dialog, prefix, ('delay_min_seconds', 'delay_max_seconds', 'probability'),
             '开始注视鼠标且鼠标进入躲避范围后，等待随机延迟再抽签；未触发时按连续躲避间隔重试')
    tooltips(dialog, prefix, ('enter_distance',), '距离从身体轮廓计算；实际进入距离不超过鼠标停留半径的一半')
    tooltips(dialog, prefix, ('exit_distance',), '至少比进入距离大 20 逻辑像素；鼠标远离当前和回正后的身体后，才开始回正等待')
    tooltips(dialog, prefix, ('leave_grace_seconds',), '短暂移出范围仍继续躲避；设为 0 时在离开退出范围后立即开始回正')
    tooltips(dialog, prefix, ('pointer_lag_seconds',), '越大越迟缓，影响侧倾对鼠标位置的跟随，不改变头部注视速度')
    tooltips(dialog, prefix, ('retry_min_seconds', 'retry_max_seconds'), '躲避触发重试、连续侧倾伴随移动和不耐烦移动的随机尝试间隔')
    tooltips(dialog, prefix, ('impatience_min_seconds', 'impatience_max_seconds'), '持续靠近时积累不耐烦的阈值；鼠标越近积累越快，移远时逐渐消退')
    tooltips(dialog, prefix, ('move_probability',), '不耐烦后每次尝试短途移动的概率，不影响下半身或漫游分支开始时的首次漂开')
    tooltips(dialog, prefix, ('move_min_distance', 'move_max_distance', 'lean_move_min_distance', 'lean_move_max_distance'),
             '移动的计划距离，落点受限时仍会缩短距离或微调方向；保持活动带和机械臂可达约束')
    tooltips(dialog, prefix, ('speed_min', 'speed_max'), '每段只抽取一次速度，单位为逻辑像素/帧，固定 40 Hz；导航仍负责平滑起停')
    tooltips(dialog, prefix, ('lean_move_probability',), '上半身躲避中，倾角和鼠标位置明显变化时，尝试伴随移动的概率；漫游只使用漂开')
    tooltips(dialog, prefix, ('move_angle_jitter',), '在远离鼠标的方向两侧随机偏转，实际路线仍须远离鼠标')
    tooltips(dialog, prefix, ('lean_min_degrees', 'lean_max_degrees'), '每轮抽取侧倾幅度，实际倾角随鼠标位置变化；不受通常移动侧倾限制，仍受空间限制')
    tooltips(dialog, prefix, ('lean_sample_power',), '1 为均匀抽取，大于 1 更偏好小倾角，小于 1 更偏好大倾角')
    tooltips(dialog, prefix, ('lean_speed',), '侧倾目标每秒最多改变的角度，身体仍会平滑跟随')
