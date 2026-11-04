"""拖动的四条独立反应通道，共用角色参数保存和资源可用性处理"""
from .behavior_fields import number_row, tooltips
from .behavior_proportions import proportion_group


DRAG_PERCENT_FIELDS = ('gesture_min_amplitude', 'gesture_max_amplitude', 'flutter_sync_probability')


def build_drag_settings(dialog, form, oracle):
    config = oracle.drag_reactions
    prefix = 'oracle.drag_reactions.'
    dialog.check(form, '启用拖动动作', prefix+'enabled', config.enabled)
    dialog.controls[prefix+'enabled'].setToolTip('控制拖动时的手势、睁眼、语音和投影反应，不影响鼠标拖动或拖动表情')
    # 每条反应通道的概率、计时与动作参数相邻，不混排不同通道
    rows = (
        (('gesture_probability', '手势触发概率', 0, 100, 1, ' %'),
         (('gesture_delay_min_seconds', 'gesture_delay_max_seconds'), '首次手势延迟', 0, 300, 3, ' 秒')),
        ((('gesture_interval_min_seconds', 'gesture_interval_max_seconds'), '手势间隔', .025, 300, 3, ' 秒'),
         (('gesture_duration_min_seconds', 'gesture_duration_max_seconds'), '手势持续时间', .1, 300, 3, ' 秒')),
        (('gesture_speed', '手势速度倍率', .25, 3, 2, ' ×'),
         (('gesture_min_amplitude', 'gesture_max_amplitude'), '手势幅度', 0, 100, 1, ' %')),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    proportion_group(dialog, form, config, prefix, ('flutter_probability', 'alternating_probability'),
                     ('单手划动', '双手扑腾', '双手交替'), mode='hands',
                     tooltip='触发手势后，按此比例选择动作；不影响睁眼、语音或投影')
    rows = (
        (('flutter_sync_probability', '随机扑腾同步倾向', 0, 100, 1, ' %'),),
        (('eye_open_probability', '拖动时睁眼概率', 0, 100, 1, ' %'),
         (('eye_delay_min_seconds', 'eye_delay_max_seconds'), '首次睁眼延迟', 0, 300, 3, ' 秒')),
        ((('eye_interval_min_seconds', 'eye_interval_max_seconds'), '睁眼尝试间隔', .025, 300, 3, ' 秒'),
         (('eye_duration_min_seconds', 'eye_duration_max_seconds'), '睁眼保持时间', .1, 300, 3, ' 秒')),
        (('voice_probability', '拖动时语音概率', 0, 100, 1, ' %'),
         (('voice_delay_min_seconds', 'voice_delay_max_seconds'), '首次语音延迟', 0, 300, 3, ' 秒')),
        ((('voice_interval_min_seconds', 'voice_interval_max_seconds'), '语音尝试间隔', .025, 300, 3, ' 秒'),),
    )
    for row in rows:
        number_row(dialog, form, config, prefix, row)
    number_row(dialog, form, oracle, 'oracle.', (
        ('drag_projection_probability', '拖动投影触发概率', 0, 100, 1, ' %'),
        ('drag_projection_cooldown_seconds', '拖动投影冷却时间', 0, 3600, 1, ' 秒')))
    for left, right in (
        (('projection_delay', '首次投影等待', 0), ('projection_interval', '投影尝试间隔', .025)),
        (('projection_duration', '投影保持时间', .1), ('projection_move', '投影挪动间隔', .025)),
    ):
        number_row(dialog, form, config, prefix, tuple(
            ((name+'_min_seconds', name+'_max_seconds'), label, minimum, 300, 3, ' 秒')
            for name, label, minimum in (left, right)))
    number_row(dialog, form, config, prefix,
        (('projection_frame_seconds', '投影换帧间隔', .025, 10, 3, ' 秒'),
         ('projection_lift_delay_seconds', '投影后抬手延迟', 0, 300, 3, ' 秒')))
    tooltips(dialog, prefix, ('flutter_probability',), '手势触发后选择双手动作的概率，其余情况为单手动作')
    tooltips(dialog, prefix, ('alternating_probability',), '已选择双手动作时，采用交替摆手的概率，其余情况为随机扑腾')
    tooltips(dialog, prefix, ('voice_probability',), '拖动反应中尝试播放语音的概率，实际播放还需在常规页开启人偶语音')
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
    tooltips(dialog, prefix, ('projection_lift_delay_seconds',), '触发投影后，经过此延迟时间后会抬手指着投影')


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
