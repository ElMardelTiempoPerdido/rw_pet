"""行为页的四组参数，复用设置窗口的字段、保存和默认值处理"""
from PySide6.QtWidgets import QLabel, QSizePolicy
from ..characters import CHARACTERS
from .voice_selector import VoiceSelector
from .behavior_styles import BehaviorStyles

from .settings_style import NOTE_STYLE, PixelRuleThin
from .daily_activity_settings import build_daily_activity_settings
from .drift_settings import build_drift_settings
from .mouse_settings import build_mouse_avoidance_settings
from .drag_settings import build_drag_settings, sync_drag_timing_dependencies
from .drag_expression_settings import build_drag_expression_settings, sync_drag_expression_settings
from .reading_settings import build_reading_settings, build_pearl_interaction_settings, sync_reading_dependencies


DRAG_PROBABILITIES = (
    ('gesture_probability', '摆手触发概率'),
    ('eye_open_probability', '拖动时睁眼概率'),
    ('flutter_probability', '双手动作占比'),
    ('alternating_probability', '双手交替动作占比'),
    ('voice_probability', '拖动触发语音概率'),
)


def build_behavior_settings(dialog, form, config):
    root = form
    dialog.behavior_styles = styles = BehaviorStyles(dialog)
    o, interaction = config.oracle, config.interaction
    voice = VoiceSelector(o.voice)
    dialog.controls['oracle.voice'] = voice
    left, _ = dialog.two_columns(form)
    left.addRow('使用的语音', voice)
    voice_note = QLabel('*您也可以在presets/voices下创建子目录，放置自定义的.wav文件，并在此选择')
    voice_note.setStyleSheet(NOTE_STYLE)
    voice_note.setWordWrap(True)
    voice_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    form.addRow(voice_note)
    voice.currentIndexChanged.connect(dialog.sync_dependencies)
    form.addRow(PixelRuleThin())
    dialog.section_heading(form, '移动与漫游')
    form = styles.add('daily_activity', root)
    build_daily_activity_settings(dialog, form, o)
    form = styles.add('drift', root)
    build_drift_settings(dialog, form, o)

    root.addRow(PixelRuleThin())
    dialog.section_heading(root, '鼠标观察')
    form = styles.add('mouse_attention', root)
    left, right = dialog.two_columns(form)
    dialog.spin(left, '关注鼠标范围半径', 'interaction.hover_radius', interaction.hover_radius,
                1, 2000, decimals=1, suffix=' px')
    dialog.spin(right, '鼠标停留时间', 'interaction.hover_dwell_seconds', interaction.hover_dwell_seconds,
                0, 60, decimals=1, step=.1, suffix=' 秒')
    left, right = dialog.two_columns(form)
    dialog.spin(left, '面向鼠标概率', 'interaction.hover_probability', interaction.hover_probability * 100,
                0, 100, decimals=1, suffix=' %')
    dialog.spin(right, '注视鼠标时睁眼概率', 'interaction.hover_open_probability', interaction.hover_open_probability * 100,
                0, 100, decimals=1, suffix=' %')
    # hover_note = QLabel('*鼠标进入此范围时，人偶可能会观察鼠标')
    # hover_note.setStyleSheet(NOTE_STYLE)
    # hover_note.setWordWrap(True)
    # hover_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    # form.addRow(hover_note)
    dialog.check(form, '可以摸摸小迭', 'interaction.petting_enabled', interaction.petting_enabled)
    left, right = dialog.two_columns(form)
    dialog.spin(left, '摸摸反应触发延迟', 'interaction.petting_seconds', interaction.petting_seconds,
                .1, 60, decimals=2, step=.1, suffix=' 秒')
    dialog.spin(right, '允许中断时间', 'interaction.petting_grace_seconds', interaction.petting_grace_seconds,
                0, 10, decimals=2, step=.1, suffix=' 秒')
    dialog.controls['interaction.petting_enabled'].setToolTip(
        '将鼠标悬浮在人偶上可以摸摸噢，不会打断人偶当前已经开始的动作')
    dialog.controls['interaction.petting_grace_seconds'].setToolTip(
        '摸摸人偶期间允许鼠标短暂离开范围，返回后可以继续')
    dialog.controls['interaction.petting_enabled'].toggled.connect(dialog.sync_dependencies)
    form = styles.add('mouse_avoidance', root)
    dialog.check(form, '人偶可能会躲避鼠标', 'interaction.hover_avoidance_enabled', interaction.hover_avoidance_enabled)
    build_mouse_avoidance_settings(dialog, form, o.mouse_avoidance)
    dialog.controls['interaction.hover_avoidance_enabled'].toggled.connect(dialog.sync_dependencies)

    root.addRow(PixelRuleThin())
    dialog.section_heading(root, '拖动反应')
    form = styles.add('drag_reactions', root)
    prefix = 'oracle.drag_reactions.'
    build_drag_settings(dialog, form, o)
    for key in (prefix+'enabled', prefix+'gesture_probability', prefix+'flutter_probability',
                prefix+'alternating_probability', prefix+'eye_open_probability', prefix+'voice_probability',
                'oracle.drag_projection_probability'):
        control = dialog.controls[key]
        signal = control.toggled if key.endswith('enabled') else control.valueChanged
        signal.connect(dialog.sync_dependencies)

    build_drag_expression_settings(dialog, root, o.drag_expressions)

    root.addRow(PixelRuleThin())
    dialog.section_heading(root, '珍珠互动')
    form = styles.add('reading_habits', root)
    build_reading_settings(dialog, form, o)
    form = styles.add('pearl_interaction', root)
    build_pearl_interaction_settings(dialog, form, o)


def sync_behavior_dependencies(dialog):
    c = dialog.controls
    for path in ('interaction.petting_seconds', 'interaction.petting_grace_seconds'):
        c[path].setEnabled(c['interaction.petting_enabled'].isChecked())
    character = CHARACTERS[c['oracle.body_appearance'].value()]
    for key, control in c.items():
        if key.startswith('oracle.mouse_avoidance.'):
            control.setEnabled(c['interaction.hover_avoidance_enabled'].isChecked())
    prefix = 'oracle.drag_reactions.'
    enabled = c[prefix+'enabled'].isChecked()
    for name, _ in DRAG_PROBABILITIES:
        c[prefix+name].setEnabled(enabled and character.has_hands)
    gestures = enabled and character.has_hands and c[prefix+'gesture_probability'].value() > 0
    c[prefix+'flutter_probability'].setEnabled(gestures)
    c[prefix+'alternating_probability'].setEnabled(gestures and c[prefix+'flutter_probability'].value() > 0)
    c['oracle.drag_projection_probability'].setEnabled(enabled and character.has_hands)
    c['oracle.drag_projection_cooldown_seconds'].setEnabled(enabled and character.has_hands and c['oracle.drag_projection_probability'].value() > 0)
    c[prefix+'eye_open_probability'].setEnabled(enabled and character.has_eyes)
    c['interaction.hover_open_probability'].setEnabled(character.has_eyes)
    c[prefix+'voice_probability'].setEnabled(enabled and c['oracle.voice'].currentData() != 'none')
    sync_drag_timing_dependencies(dialog, gestures=gestures,
        eyes=enabled and character.has_eyes, voice=enabled and c['oracle.voice'].currentData() != 'none',
        projection=enabled and character.has_hands and c['oracle.drag_projection_probability'].value() > 0)
    sync_reading_dependencies(dialog, character)
    sync_drag_expression_settings(dialog, character)
