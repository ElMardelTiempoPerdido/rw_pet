"""拖动的四条独立反应通道，共用角色参数保存和资源可用性处理"""
from .behavior_fields import number_row, tooltips


DRAG_PERCENT_FIELDS = ('gesture_min_amplitude', 'gesture_max_amplitude', 'flutter_sync_probability')


def build_drag_timing_settings(dialog, form, config):
    prefix = 'oracle.drag_reactions.'
    ranges = (
        ('gesture_delay', '首次手势延迟最短', '首次手势延迟最长', 0),
        ('gesture_interval', '手势间隔最短', '手势间隔最长', .025),
        ('gesture_duration', '手势持续时间最短', '手势持续时间最长', .1),
        ('eye_delay', '首次睁眼延迟最短', '首次睁眼延迟最长', 0),
        ('eye_interval', '睁眼尝试间隔最短', '睁眼尝试间隔最长', .025),
        ('eye_duration', '睁眼保持时间最短', '睁眼保持时间最长', .1),
        ('voice_delay', '首次语音延迟最短', '首次语音延迟最长', 0),
        ('voice_interval', '语音尝试间隔最短', '语音尝试间隔最长', .025),
        ('projection_delay', '首次投影等待最短', '首次投影等待最长', 0),
        ('projection_interval', '投影尝试间隔最短', '投影尝试间隔最长', .025),
        ('projection_duration', '投影保持时间最短', '投影保持时间最长', .1),
        ('projection_move', '投影挪动间隔最短', '投影挪动间隔最长', .025),
    )
    for name, low_label, high_label, minimum in ranges:
        for column, bound, label in zip(dialog.two_columns(form), ('min', 'max'), (low_label, high_label)):
            field = name+'_'+bound+'_seconds'
            dialog.spin(column, label, prefix+field, getattr(config, field), minimum, 300,
                        decimals=3, step=.1, suffix=' 秒')
    rows = (
        (('gesture_speed', '手势速度倍率', .25, 3, 2, ' ×'),
         ('flutter_sync_probability', '随机扑腾同步倾向', 0, 100, 1, ' %')),
        (('gesture_min_amplitude', '手势幅度最小值', 0, 100, 1, ' %'),
         ('gesture_max_amplitude', '手势幅度最大值', 0, 100, 1, ' %')),
        (('projection_frame_seconds', '投影换帧间隔', .025, 10, 3, ' 秒'),
         ('projection_lift_delay_seconds', '投影后抬手延迟', 0, 300, 3, ' 秒')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    tooltips(dialog, prefix, ('gesture_interval_min_seconds', 'gesture_interval_max_seconds'),
             '上一组手势结束后再等待；未抽中手势也等待此间隔，不影响语音和睁眼计时')
    tooltips(dialog, prefix, ('gesture_speed',), '缩放三种摆手动作的速度，保留每次动作的随机节奏；不增加臂长、摆角或驱动力上限')
    tooltips(dialog, prefix, ('gesture_min_amplitude', 'gesture_max_amplitude'),
             '在肩外安全扇形内抽取抬手幅度，偏向较小值；两手有轻微差异，100% 仍受物理限位约束')
    tooltips(dialog, prefix, ('flutter_sync_probability',), '仅控制随机扑腾中两手同起同落的倾向，不改变固定交替动作的概率')
    tooltips(dialog, prefix, ('eye_interval_min_seconds', 'eye_interval_max_seconds'), '本次睁眼保持结束后，再等待并独立尝试；未睁眼时直接等待')
    tooltips(dialog, prefix, ('voice_interval_min_seconds', 'voice_interval_max_seconds'), '按语音片段时长加此间隔安排下次尝试；松手或取消后不补播')
    tooltips(dialog, prefix, ('projection_delay_min_seconds', 'projection_delay_max_seconds',
                              'projection_interval_min_seconds', 'projection_interval_max_seconds'),
             '只累计双手空闲时的等待，摆手和投影期间暂停；仍受投影冷却限制，松手后清除等待')
    tooltips(dialog, prefix, ('projection_lift_delay_seconds',), '投影显示后才抬手；若延迟超过投影时长，本次不抬手')


def sync_drag_timing_dependencies(dialog, *, gestures, eyes, voice, projection):
    c = dialog.controls
    prefix = 'oracle.drag_reactions.'
    for path, control in c.items():
        if not path.startswith(prefix):
            continue
        name = path[len(prefix):]
        if name.startswith('gesture_') and name != 'gesture_probability':
            control.setEnabled(gestures)
        elif name == 'flutter_sync_probability':
            control.setEnabled(gestures and c[prefix+'flutter_probability'].value() > 0
                               and c[prefix+'alternating_probability'].value() < 100)
        elif name.startswith('eye_') and name != 'eye_open_probability':
            control.setEnabled(eyes and c[prefix+'eye_open_probability'].value() > 0)
        elif name.startswith('voice_') and name != 'voice_probability':
            control.setEnabled(voice and c[prefix+'voice_probability'].value() > 0)
        elif name.startswith('projection_'):
            control.setEnabled(projection)
