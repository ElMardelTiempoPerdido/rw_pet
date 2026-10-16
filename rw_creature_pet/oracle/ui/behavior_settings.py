"""行为页的四组参数，复用设置窗口的字段、保存和默认值处理"""
from PySide6.QtWidgets import QLabel, QSizePolicy

from .settings_style import NOTE_STYLE, PixelRuleThin


DRAG_PROBABILITIES = (
    ('gesture_probability', '手势触发概率'),
    ('eye_open_probability', '拖动时睁眼概率'),
    ('flutter_probability', '双手动作占比'),
    ('alternating_probability', '双手交替动作占比'),
    ('voice_probability', '拖动时语音概率'),
)


def build_behavior_settings(dialog, form, config):
    o, interaction = config.oracle, config.interaction
    heading = QLabel('移动与漫游')
    heading.setStyleSheet(NOTE_STYLE)
    form.addRow(heading)
    left, right = dialog.two_columns(form)
    dialog.spin(left, '通常移动速度', 'oracle.float_speed', o.float_speed, .3, 2., decimals=2, step=.1)
    dialog.spin(right, '底座滑动速度', 'oracle.base_speed', o.base_speed, 1.5, 4., decimals=2, step=.1)
    left, right = dialog.two_columns(form)
    dialog.spin(left, '跨到相邻边概率', 'oracle.cross_edge_probability', o.cross_edge_probability * 100,
                0, 100, decimals=1, suffix=' %')
    dialog.spin(right, '反重力漫游概率', 'oracle.antigravity_probability', o.antigravity_probability * 100,
                0, 100, decimals=1, suffix=' %')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '漫游移动速度', 'oracle.drift_speed', o.drift_speed, .3, 1.8, decimals=2, step=.1)
    dialog.spin(right, '漫游时长', 'oracle.antigravity_duration_seconds', o.antigravity_duration_seconds,
                1, 3600, decimals=1, suffix=' 秒')

    form.addRow(PixelRuleThin())
    heading = QLabel('鼠标观察与避让')
    heading.setStyleSheet(NOTE_STYLE)
    form.addRow(heading)
    dialog.check(form, '人偶可能会躲避鼠标', 'interaction.hover_avoidance_enabled', interaction.hover_avoidance_enabled)
    left, right = dialog.two_columns(form)
    dialog.spin(left, '面向鼠标概率', 'interaction.hover_probability', interaction.hover_probability * 100,
                0, 100, decimals=1, suffix=' %')
    dialog.spin(right, '注视鼠标时睁眼概率', 'interaction.hover_open_probability', interaction.hover_open_probability * 100,
                0, 100, decimals=1, suffix=' %')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '鼠标停留半径', 'interaction.hover_radius', interaction.hover_radius,
                1, 2000, decimals=1, suffix=' px')
    dialog.spin(right, '鼠标停留时间', 'interaction.hover_dwell_seconds', interaction.hover_dwell_seconds,
                0, 60, decimals=1, step=.1, suffix=' 秒')
    hover_note = QLabel('*鼠标进入此范围时，人偶可能会观察鼠标')
    hover_note.setStyleSheet(NOTE_STYLE)
    hover_note.setWordWrap(True)
    hover_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    form.addRow(hover_note)

    form.addRow(PixelRuleThin())
    heading = QLabel('拖动反应')
    heading.setStyleSheet(NOTE_STYLE)
    form.addRow(heading)
    reaction = o.drag_reactions
    prefix = 'oracle.drag_reactions.'
    dialog.check(form, '启用拖动反应', prefix+'enabled', reaction.enabled)
    dialog.controls[prefix+'enabled'].setToolTip('控制拖动时的手势、睁眼、语音和投影反应，不影响鼠标拖动本身')
    for start in range(0, len(DRAG_PROBABILITIES), 2):
        for column, (name, label) in zip(dialog.two_columns(form), DRAG_PROBABILITIES[start:start+2]):
            dialog.spin(column, label, prefix+name, getattr(reaction, name) * 100,
                        0, 100, decimals=1, suffix=' %')
    dialog.controls[prefix+'flutter_probability'].setToolTip('手势触发后选择双手动作的概率，其余情况为单手动作')
    dialog.controls[prefix+'alternating_probability'].setToolTip('已选择双手动作时，采用交替摆手的概率，其余情况为随机扑腾')
    dialog.controls[prefix+'voice_probability'].setToolTip('拖动反应中尝试播放语音的概率，实际播放还需在常规页开启人偶语音')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '拖动投影触发概率', 'oracle.drag_projection_probability', o.drag_projection_probability * 100,
                0, 100, decimals=1, suffix=' %')
    dialog.spin(right, '拖动投影冷却时间', 'oracle.drag_projection_cooldown_seconds', o.drag_projection_cooldown_seconds,
                0, 3600, decimals=1, suffix=' 秒')
    for key in (prefix+'enabled', prefix+'gesture_probability', prefix+'flutter_probability',
                'oracle.drag_projection_probability'):
        control = dialog.controls[key]
        signal = control.toggled if key.endswith('enabled') else control.valueChanged
        signal.connect(dialog.sync_dependencies)

    form.addRow(PixelRuleThin())
    heading = QLabel('珍珠互动')
    heading.setStyleSheet(NOTE_STYLE)
    form.addRow(heading)
    left, right = dialog.two_columns(form)
    dialog.spin(left, '人偶避让矩阵半径', 'oracle.pearl_matrix_avoid_radius', o.pearl_matrix_avoid_radius,
                0, 300, suffix=' px')
    dialog.controls['oracle.pearl_matrix_avoid_radius'].setToolTip(
        '*人偶会尽量与矩阵珍珠保持此距离，以避免重叠')
    dialog.spin(right, '珍珠播放动画概率', 'oracle.pearl_playback_probability', o.pearl_playback_probability * 100,
                0, 100, suffix=' %')
    dialog.controls['oracle.pearl_playback_probability'].setToolTip(
        '*人偶将珍珠拉进阅读时，触发播放音乐动画的概率（只有特效，并不会播放音乐')
    left, right = dialog.two_columns(form)
    for column, label, name in ((left, '珍珠跟随范围宽度', 'pearl_follow_width'),
                               (right, '珍珠跟随范围高度', 'pearl_follow_height')):
        dialog.spin(column, label, 'oracle.'+name, getattr(o, name), 160, 4000, decimals=1, step=10, suffix=' px')
        dialog.controls['oracle.'+name].setToolTip('以人偶为中心的矩形范围，超出范围的珍珠会跟随迁移；数值为逻辑像素')


def sync_behavior_dependencies(dialog):
    c = dialog.controls
    prefix = 'oracle.drag_reactions.'
    enabled = c[prefix+'enabled'].isChecked()
    for name, _ in DRAG_PROBABILITIES:
        c[prefix+name].setEnabled(enabled)
    gestures = enabled and c[prefix+'gesture_probability'].value() > 0
    c[prefix+'flutter_probability'].setEnabled(gestures)
    c[prefix+'alternating_probability'].setEnabled(gestures and c[prefix+'flutter_probability'].value() > 0)
    c['oracle.drag_projection_probability'].setEnabled(enabled)
    c['oracle.drag_projection_cooldown_seconds'].setEnabled(enabled and c['oracle.drag_projection_probability'].value() > 0)
