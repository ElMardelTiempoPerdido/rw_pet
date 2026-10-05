"""Bell 用户设置：显式保存，首次启动与托盘入口使用同一窗口。"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QThread, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (QAbstractSpinBox, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QScrollArea,
                               QSizeGrip, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget, QFrame)

from ..settings_store import load_defaults, validate_game_directory
from ..i18n import WidgetTexts, language_manager, tr
from ..shared.messages import Message
from ..ui_config import UiConfig
from .assets import prepare_oracle_assets
from .config import DISPLAY_SCALES, EDGE_NAMES, validate_edges
from .settings_style import PixelRule, apply_settings_style, pixel_box, settings_font, PixelRuleThin, NOTE_STYLE

PERCENTAGES = {'audio.volume', 'oracle.projection_opacity', 'oracle.glow_opacity',
               'oracle.edge_fraction', 'oracle.base_fraction', 'oracle.arm_scale',
               'oracle.cross_edge_probability', 'oracle.antigravity_probability',
               'oracle.pearl_playback_probability', 'oracle.drag_projection_probability',
               'overseer.appearance_probability', 'overseer.relocation_probability'}


class _WheelScrollsPage:
    def wheelEvent(self, event):
        # SpinBox/ComboBox 不消费滚轮，即使正在编辑。显式转交当前页
        # 避免平台差异导致只忽略事件却无法继续滚动
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            viewport = parent.viewport()
            forwarded = QWheelEvent(QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                                    event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(),
                                    event.modifiers(), event.phase(), event.inverted(), event.source(),
                                    event.pointingDevice())
            QCoreApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
        else:
            event.ignore()


class WheelSafeSpinBox(_WheelScrollsPage, QSpinBox):
    pass


class WheelSafeDoubleSpinBox(_WheelScrollsPage, QDoubleSpinBox):
    pass


class WheelSafeComboBox(_WheelScrollsPage, QComboBox):
    pass


class _DirectoryHint(QLabel):
    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(self.heightForWidth(self.width()))
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()


class OutfitSelector(QWidget):
    def __init__(self, value):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for name, label in (('normal', '常规'), ('maid', '女仆套装')):
            button = QRadioButton(label)
            self.buttons[name] = button
            self.group.addButton(button)
            layout.addWidget(button)
        self.setValue(value)

    def setValue(self, value):
        self.buttons[value].setChecked(True)

    def value(self):
        return next(name for name, button in self.buttons.items() if button.isChecked())


class _ParameterColumn(QFormLayout):
    """参数列：输入框靠右，标签使用它左侧的全部剩余宽度。"""

    def addRow(self, *args):
        if len(args) == 2:
            label, control = args
            if isinstance(label, str):
                label = QLabel(label)
            label.setWordWrap(True)
            policy = label.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            label.setSizePolicy(policy)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(label, 1)
            if isinstance(control, QWidget):
                label.setBuddy(control)
                row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            else:
                row.addLayout(control)
            super().addRow(row)
        else:
            # 无单独标签的复选框仍靠左，不作为右对齐输入框处理。
            super().addRow(*args)


def _parameter_columns():
    """单参数行与双参数行共用列宽和列间距，空的右列也保留一半空间。"""
    panel = QWidget()
    row = QHBoxLayout(panel)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(24)
    columns = []
    for _ in range(2):
        cell = QWidget()
        column = _ParameterColumn(cell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setVerticalSpacing(0)
        column.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        column.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(cell, 1)
        columns.append(column)
    return panel, tuple(columns)


class _ParameterForm(QFormLayout):
    """分类页中的单个输入项占左列；说明、分割线与复合选择器保持整行。"""

    def addRow(self, *args):
        if len(args) == 2 and isinstance(args[1], (QAbstractSpinBox, QComboBox, QLineEdit, QPushButton)):
            panel, (left, _) = _parameter_columns()
            left.addRow(*args)
            super().addRow(panel)
        else:
            super().addRow(*args)


class ColorButton(QPushButton):
    def __init__(self, value, title):
        super().__init__()
        self.title = title
        self.setAutoDefault(False)
        self.setValue(value)
        self.clicked.connect(self.choose_color)

    def value(self):
        return self._color

    def setValue(self, value):
        color = QColor(value)
        self._color = color.name()
        self.setText(self._color.upper())
        swatch = QPixmap(16, 16)
        swatch.fill(color)
        painter = QPainter(swatch)
        painter.setPen(QColor('#707070'))
        painter.drawRect(0, 0, 15, 15)
        painter.end()
        self.setIcon(QIcon(swatch))

    def choose_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, tr(self.title),
                                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.setValue(color.name())


class AssetPreparation(QThread):
    def __init__(self, config, parent):
        super().__init__(parent)
        self.config, self.result, self.error = config, None, ''

    def run(self):
        try:
            self.result = prepare_oracle_assets(self.config)
        except Exception as exc:
            self.error = Message('资源准备失败：{error}', error=exc)


class OracleSettingsDialog(QDialog):
    def __init__(self, config, store, *, first_run=False, message='', assets=None, commit=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('桌宠初始化设置' if first_run else '桌宠设置')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.original, self.store = config, store
        language_manager().set_language(config.ui.language)
        self.assets, self.commit = assets, commit
        self.saved_config = self.prepared_assets = self.worker = None
        self.controls = {}
        self.reset_tab_buttons = []
        self._reset_values = {}
        self._shutdown = False
        self._drag_offset = None
        self._workarea = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 18)
        layout.setSpacing(16)
        self.header = QWidget()
        self.header.installEventFilter(self)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(self.windowTitle())
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header_layout.addWidget(title, 1)
        self.close_button = QPushButton('×')
        self.close_button.setAccessibleName('关闭设置')
        self.close_button.setFixedWidth(30)
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject)
        header_layout.addWidget(self.close_button)
        layout.addWidget(self.header)
        layout.addWidget(PixelRule())
        self.form = QWidget()
        form_layout = QVBoxLayout(self.form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(22)
        game = QFormLayout()
        game.setHorizontalSpacing(12)
        game.setVerticalSpacing(14)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.game_dir = QLineEdit(str(config.game_dir))
        self.game_dir.setPlaceholderText('选择 Rain World 安装目录')
        self.browse_button = QPushButton('浏览...')
        self.browse_button.setMinimumWidth(78)
        self.browse_button.setAutoDefault(False)
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.game_dir, 1)
        row.addWidget(self.browse_button)
        game.addRow('雨世界目录', row)
        hint = _DirectoryHint('请选择这台电脑上雨世界的安装目录\n'
                      '一般名称为 Rain World，其中包含 RainWorld_Data、RainWorld.exe 等内容\n'
                      '首次启动时，需要一点时间从安装目录中读取资源')
        hint.setStyleSheet(NOTE_STYLE)
        hint.setWordWrap(True)
        # 保留按实际宽度计算文字高度，避免 sizeHint 预留过多行高形成上下空白。
        hint_policy = hint.sizePolicy()
        hint_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        hint.setSizePolicy(hint_policy)
        self.directory_hint = hint
        self.game_dir.setToolTip(hint.text())
        game.addRow('', hint)
        form_layout.addLayout(game)
        self.tabs = QTabWidget()
        form_layout.addWidget(self.tabs, 1)
        general = self.tab('常规')
        scale = WheelSafeComboBox()
        scale.setFixedWidth(100)
        for value in DISPLAY_SCALES:
            scale.addItem(f'{value:g}×', value)
        scale.setCurrentIndex(DISPLAY_SCALES.index(config.desktop.scale))
        self.controls['desktop.scale'] = scale
        general.addRow('桌宠显示大小', scale)
        self.check(general, '人偶想去哪去哪', 'desktop.autonomous', config.desktop.autonomous)

        auto_note = QLabel('*勾选时，人偶会自主移动；关闭后仍可原地阅读珍珠、观察窗口变化')
        auto_note.setStyleSheet(NOTE_STYLE)
        auto_note.setWordWrap(True)
        auto_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        general.addRow(auto_note)

        self.check(general, '启用鼠标拖动', 'interaction.drag_enabled', config.interaction.drag_enabled)
        self.check(general, '隐藏电缆', 'oracle.hide_cords', config.oracle.hide_cords)
        self.controls['oracle.hide_cords'].setToolTip('可能会节省一些计算开销')
        general.addRow(PixelRuleThin())

        left, right = self.two_columns(general)
        self.check(left, '开启人偶语音', 'audio.enabled', config.audio.enabled)
        self.spin(right, '语音音量', 'audio.volume', config.audio.volume * 100, 0, 100, suffix=' %')
        self.controls['audio.enabled'].toggled.connect(self.controls['audio.volume'].setEnabled)
        self.controls['audio.volume'].setEnabled(config.audio.enabled)
        general.addRow(PixelRuleThin())

        left, right = self.two_columns(general)
        self.check(left, '开启外发光', 'oracle.glow_enabled', config.oracle.glow_enabled)
        self.spin(right, '发光不透明度', 'oracle.glow_opacity', config.oracle.glow_opacity * 100,
                  0, 100, suffix=' %')
        glow_color = ColorButton(config.oracle.glow_color, '选择外发光颜色')
        glow_color.setFixedWidth(100)
        self.controls['oracle.glow_color'] = glow_color
        left, right = self.two_columns(general)
        left.addRow('发光颜色', glow_color)
        self.spin(right, '发光半径', 'oracle.glow_radius', config.oracle.glow_radius,
                  1, 24, decimals=1, step=1, suffix=' px')

        self.controls['oracle.glow_enabled'].toggled.connect(self.sync_dependencies)

        general.addRow(PixelRuleThin())

        test_note = QLabel('【注意】当前桌宠为未开发完成的测试版本，可能出现各种问题\n'
                           '如需反馈bug或蹲蹲功能更新/正式版，欢迎添加此群 → 672754728\n\n'
                           '此桌宠为非官方粉丝作品，项目及其衍生版本禁止用于任何商业活动\n'
                           '原作名称/角色与素材归各自权利人所有，请支持 RainWorld！ >ㅅ<')
        test_note.setStyleSheet(NOTE_STYLE)
        test_note.setWordWrap(True)
        test_note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        test_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        general.addRow(test_note)

        appearance = self.tab('外观')
        outfit = OutfitSelector(config.oracle.outfit)
        self.controls['oracle.outfit'] = outfit
        appearance.addRow(outfit)
        appearance.addRow(PixelRuleThin())
        self.spin(appearance, '机械臂缩放', 'oracle.arm_scale', config.oracle.arm_scale * 100,
                  35, 75, decimals=1, suffix=' %')
        self.controls['oracle.arm_scale'].setToolTip(
            '相对于原作臂段长度，默认 60%；修改后会重新安置人偶并更新机械臂可达范围。')

        pearls = self.tab('珍珠')
        o = config.oracle
        self.check(pearls, '显示矩阵珍珠', 'oracle.pearl_matrix_enabled', o.pearl_matrix_enabled)
        left, right = self.two_columns(pearls)
        self.spin(left, '矩阵珍珠数量', 'oracle.pearl_matrix_count', o.pearl_matrix_count, 0, 64)
        self.spin(right, '人偶避让矩阵半径', 'oracle.pearl_matrix_avoid_radius',
                  o.pearl_matrix_avoid_radius, 0, 300, suffix=' px')
        self.controls['oracle.pearl_matrix_avoid_radius'].setToolTip(
            '*人偶会尽量与矩阵珍珠保持此距离，以避免重叠')
        pearls.addRow(PixelRuleThin())

        self.check(pearls, '显示环绕珍珠', 'oracle.pearl_orbits_enabled', o.pearl_orbits_enabled)
        for pair in ((('内圈数量', 'pearl_inner_count'), ('外圈数量', 'pearl_outer_count')),
                     (('固定珍珠数量', 'pearl_fixed_count'), ('卫星珍珠数量', 'pearl_satellite_count'))):
            for column, (label, field) in zip(self.two_columns(pearls), pair):
                self.spin(column, label, 'oracle.' + field, getattr(o, field), 0, 32)
        pearls.addRow(PixelRuleThin())

        self.spin(pearls, '珍珠播放动画概率', 'oracle.pearl_playback_probability',
                  o.pearl_playback_probability * 100, 0, 100, suffix=' %')
        self.controls['oracle.pearl_playback_probability'].setToolTip(
            '*人偶将珍珠拉进阅读时，触发播放音乐动画的概率（只有特效，并不会播放音乐')
        left, right = self.two_columns(pearls)
        self.spin(left, '播放光晕特效大小', 'oracle.pearl_bubble_max_size',
                  o.pearl_bubble_max_size, 6, 64, decimals=1, suffix=' px')
        bubble_color = ColorButton(o.pearl_bubble_color, '播放光晕特效颜色')
        bubble_color.setFixedWidth(100)
        self.controls['oracle.pearl_bubble_color'] = bubble_color
        right.addRow('播放光晕特效颜色', bubble_color)

        halo = self.tab('投影')
        self.spin(halo, '投影不透明度', 'oracle.projection_opacity', o.projection_opacity * 100, 0, 100, suffix=' %')
        opacity_note = QLabel('*此透明度应用于珍珠文字、光环、电弧等全息投影类特效')
        opacity_note.setStyleSheet(NOTE_STYLE)
        opacity_note.setWordWrap(True)
        halo.addRow(opacity_note)
        halo.addRow(PixelRuleThin())

        left, right = self.two_columns(halo)
        self.check(left, '显示光环', 'oracle.halo_enabled', o.halo_enabled)
        self.spin(right, '光环大小', 'oracle.halo_scale', o.halo_scale, .25, 1.5, decimals=2, step=.05)
        halo.addRow(PixelRuleThin())

        left, right = self.two_columns(halo)
        self.check(left, '显示电弧', 'oracle.halo_arcs_enabled', o.halo_arcs_enabled)
        self.spin(right, '电弧数量上限', 'oracle.halo_arc_max_count', o.halo_arc_max_count, 1, 10)
        halo.addRow(PixelRuleThin())
        left, right = self.two_columns(halo)
        self.spin(left, '拖动投影触发概率', 'oracle.drag_projection_probability',
                  o.drag_projection_probability*100, 0, 100, decimals=1, suffix=' %')
        self.spin(right, '拖动投影冷却时间', 'oracle.drag_projection_cooldown_seconds',
                  o.drag_projection_cooldown_seconds, 0, 3600, decimals=1, suffix=' 秒')
        # projection_note = QLabel('摆手结束后才尝试投影；概率为 0 时关闭。冷却从触发时开始，松手不重置。')
        # projection_note.setStyleSheet(NOTE_STYLE)
        # projection_note.setWordWrap(True)
        # halo.addRow(projection_note)

        activity = self.tab('移动')
        self.edge_selection(activity, o)

        self.spin(activity, '屏幕边缘活动带宽度', 'oracle.edge_fraction', o.edge_fraction * 100, 20, 35, decimals=1,
                  suffix=' %')
        activity.addRow(PixelRuleThin())

        self.spin(activity, '通常移动速度', 'oracle.float_speed', o.float_speed, .3, 2., decimals=2, step=.1)

        self.spin(activity, '跨到相邻边概率', 'oracle.cross_edge_probability', o.cross_edge_probability * 100, 0, 100,
                  decimals=1, suffix=' %')

        activity.addRow(PixelRuleThin())
        self.spin(activity, '反重力漫游概率', 'oracle.antigravity_probability', o.antigravity_probability * 100, 0, 100,
                  decimals=1, suffix=' %')
        left, right = self.two_columns(activity)
        self.spin(left, '漫游移动速度', 'oracle.drift_speed', o.drift_speed, .3, 1.8, decimals=2, step=.1)
        self.spin(right, '漫游时长', 'oracle.antigravity_duration_seconds', o.antigravity_duration_seconds,
                  1, max(3600, o.antigravity_duration_seconds), decimals=1, suffix=' 秒')

        watcher = self.tab('监视者')
        c = config.overseer
        left, right = self.two_columns(watcher)
        self.check(left, '允许出现监视者', 'overseer.enabled', c.enabled)
        color = ColorButton(c.color, '监视者颜色')
        color.setFixedWidth(100)
        self.controls['overseer.color'] = color
        right.addRow('主色', color)
        watcher.addRow(PixelRuleThin())
        self.spin(watcher, '出现检查间隔', 'overseer.check_interval', c.check_interval,
                  .1, 86400, decimals=2, suffix=' 秒')
        self.spin(watcher, '出现概率', 'overseer.appearance_probability', c.appearance_probability*100,
                  0, 100, decimals=1, suffix=' %')
        note = QLabel('*每隔此时间，按以上概率触发监视者出现')
        note.setWordWrap(True)
        note.setStyleSheet(NOTE_STYLE)
        watcher.addRow(note)
        for prefix, labels, minimum in (('duration', ('持续时间 - 最短', '持续时间 - 最长'), .1),
                                         ('cooldown', ('冷却时间 - 最短', '冷却时间 - 最长'), 0)):
            for column, suffix, label in zip(self.two_columns(watcher), ('min', 'max'), labels):
                key = prefix+'_'+suffix
                self.spin(column, label, 'overseer.'+key, getattr(c, key), minimum,
                          86400, decimals=2, suffix=' 秒')
        watcher.addRow(PixelRuleThin())
        left, right = self.two_columns(watcher)
        self.spin(left, '鼠标缩回距离', 'overseer.withdraw_distance', c.withdraw_distance,
                  1, 10000, decimals=1, suffix=' px')
        self.spin(right, '鼠标安全距离', 'overseer.reemerge_distance', c.reemerge_distance,
                  1, 10000, decimals=1, suffix=' px')
        left, right = self.two_columns(watcher)
        self.spin(left, '人偶缩回距离', 'overseer.puppet_withdraw_distance', c.puppet_withdraw_distance,
                  1, 10000, decimals=1, suffix=' px')
        self.spin(right, '人偶安全距离', 'overseer.puppet_reemerge_distance', c.puppet_reemerge_distance,
                  1, 10000, decimals=1, suffix=' px')
        self.spin(watcher, '缩回后换位概率', 'overseer.relocation_probability', c.relocation_probability*100,
                  0, 100, decimals=1, suffix=' %')
        hint = QLabel('*安全距离应当大于缩回距离')
        hint.setWordWrap(True)
        hint.setStyleSheet(NOTE_STYLE)
        watcher.addRow(hint)
        self.controls['overseer.enabled'].toggled.connect(self.sync_dependencies)

        self.controls['oracle.pearl_matrix_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.pearl_matrix_count'].valueChanged.connect(self.sync_dependencies)
        self.controls['oracle.pearl_playback_probability'].valueChanged.connect(self.sync_dependencies)
        self.controls['oracle.pearl_orbits_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.halo_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.halo_arcs_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.pearl_fixed_count'].valueChanged.connect(self.sync_dependencies)
        self.sync_dependencies()
        self.initial_values = {key: self.value(control) for key, control in self.controls.items()}
        layout.addWidget(self.form, 1)
        self._status_message = message or ('点击保存启动桌宠' if first_run else
                                         '*修改显示大小、珍珠或活动参数时，人偶会重置位置')
        self.status = QLabel()
        self.status.setStyleSheet(NOTE_STYLE)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.reset_all_button = self.buttons.addButton('恢复全部默认设置', QDialogButtonBox.ButtonRole.ResetRole)
        self.reset_all_button.setAutoDefault(False)
        self.reset_all_button.setToolTip('恢复所有分类及游戏目录的默认设置，点击保存后生效。')
        self.reset_all_button.clicked.connect(lambda: self.restore_defaults())
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText('保存并启动' if first_run else '保存并应用')
        self.save_button.setProperty('primary', True)
        self.save_button.setDefault(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.buttons, 1)
        footer.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(footer)
        apply_settings_style(self)
        self.resize(800, 750)
        self._texts = WidgetTexts(self, exclude=(self.status,))
        # Qt 会在 LanguageChange 中恢复标准按钮文字，在它处理完后重设自定义标题
        self.buttons.installEventFilter(self)
        language_manager().changed.connect(self.retranslate)
        self.retranslate()

    def set_status(self, message):
        self._status_message = message
        self.status.setText(tr(message))

    def retranslate(self):
        self._texts.retranslate()
        self.set_status(self._status_message)
        language = language_manager().language
        self.original = replace(self.original, ui=UiConfig(language))
        if hasattr(self, 'pending'):
            self.pending = replace(self.pending, ui=self.original.ui)
        self.setFont(settings_font())
        self.status.setFont(self.font())
        for control in self.controls.values():
            if isinstance(control, QComboBox):
                control.view().setFont(self.font())
            if isinstance(control, (QSpinBox, QDoubleSpinBox)):
                widest = max(control.fontMetrics().horizontalAdvance(control.textFromValue(value) + control.suffix())
                             for value in (control.minimum(), control.maximum()))
                control.setFixedWidth(max(100, widest + 30))
        # 长英文标签可换行，列内的数值仍靠右；不重建控件或修改输入值
        for label in self.form.findChildren(QLabel):
            label.setFont(self.font())  # 带局部字号样式的说明也更新字体族
            label.setWordWrap(True)
        if language == 'en' and self.width() < 780:
            rect = self._workarea if self._workarea is not None else self.screen().availableGeometry()
            self.resize(max(self.width(), min(780, rect.width()-32)), self.height())
            # 加宽不能把原本靠屏幕右侧的关闭按钮推到工作区外
            self.move(max(rect.left(), min(self.x(), rect.right()-self.width()+1)),
                      max(rect.top(), min(self.y(), rect.bottom()-self.height()+1)))

    def tab(self, title):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        panel = QWidget()
        form = _ParameterForm(panel)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(18, 22, 18, 22)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(20)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        area.setWidget(panel)
        index = self.tabs.addTab(area, title)
        reset = QPushButton('恢复本页默认设置')
        reset.setAutoDefault(False)
        reset.clicked.connect(lambda checked=False, i=index: self.restore_defaults(i))
        self.reset_tab_buttons.append(reset)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(reset)
        form.addRow(row)
        return form

    def restore_defaults(self, index=None):
        """仅重置面板字段；按控件所属页划分，不按共享的 oracle 配置组划分"""
        if self.worker is not None:
            return
        try:
            defaults = load_defaults()
        except (OSError, ValueError, TypeError) as exc:
            self.set_status(Message('无法读取默认设置：{error}', error=exc))
            return
        page = self.tabs.widget(index) if index is not None else None
        for key, control in self.controls.items():
            if page is not None and not page.isAncestorOf(control):
                continue
            group, field = key.split('.')
            value = getattr(getattr(defaults, group), field)
            shown = value * 100 if key in PERCENTAGES else value
            if isinstance(control, QCheckBox):
                control.setChecked(shown)
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(shown))
            else:
                if isinstance(control, (QSpinBox, QDoubleSpinBox)):
                    if isinstance(control, QSpinBox):
                        shown = round(shown)
                    control.setRange(min(control.minimum(), shown), max(control.maximum(), shown))
                control.setValue(shown)
            # 重置也是一次显式编辑，默认值即使显示成同一个舍入值，也必须替换旧值；
            # 随后未编辑的控件则继续保留 TOML 原始精度
            self._reset_values[key] = value
            self.initial_values[key] = self.value(control)
        if page is None or page.isAncestorOf(self.start_edge_group.checkedButton()):
            self.start_edge_buttons[defaults.oracle.base_side].setChecked(True)
            for edge, check in self.edge_checks.items():
                check.setChecked(edge in defaults.oracle.allowed_edges)
        if page is None:
            self.game_dir.setText(str(defaults.game_dir))
        self.sync_dependencies()
        self.set_status('已恢复全部默认设置，点击保存后生效。' if page is None else
                        '已恢复本页默认设置，点击保存后生效。')

    @staticmethod
    def two_columns(form):
        """添加等宽双列行；标签/复选框靠左，输入框靠列右侧"""
        panel, columns = _parameter_columns()
        form.addRow(panel)
        return columns

    def check(self, form, label, key, value):
        control = QCheckBox(label)
        control.setChecked(value)
        self.controls[key] = control
        form.addRow(control)

    def edge_selection(self, form, config):
        labels = {'top': '顶部', 'right': '右侧', 'bottom': '底部', 'left': '左侧'}
        row = QHBoxLayout()
        row.setSpacing(14)
        self.start_edge_group = QButtonGroup(self)
        self.start_edge_buttons = {}
        for edge in ('top', 'bottom', 'left', 'right'):
            button = QRadioButton(labels[edge])
            button.setProperty('edge', edge)
            button.setChecked(edge == config.base_side)
            self.start_edge_group.addButton(button)
            self.start_edge_buttons[edge] = button
            button.toggled.connect(
                lambda checked, name=edge: self.edge_checks[name].setChecked(True) if checked else None)
            row.addWidget(button)
        row.addStretch(1)
        form.addRow('启动时所在边缘', row)
        self.spin(form, '启动时在边上的位置', 'oracle.base_fraction', config.base_fraction*100,
                  0, 100, decimals=1, step=1, suffix=' %')
        pos_note = QLabel('*顶部/底部从左到右计算，左侧/右侧从上到下计算，50%为居中')
        pos_note.setStyleSheet(NOTE_STYLE)
        pos_note.setWordWrap(True)
        form.addRow(pos_note)

        form.addRow(PixelRuleThin())

        positions = {'top': (0, 1), 'right': (1, 2), 'bottom': (2, 1), 'left': (1, 0)}
        panel = QWidget()
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(18)
        self.edge_checks = {}
        for edge in EDGE_NAMES:
            check = QCheckBox(labels[edge])
            check.setChecked(edge in config.allowed_edges)
            self.edge_checks[edge] = check
            grid.addWidget(check, *positions[edge], Qt.AlignmentFlag.AlignCenter)
        screen = QLabel('（屏幕）')
        screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(screen, 1, 1)
        form.addRow('人偶活动范围', panel)
        note = QLabel('*至少选择一条边缘，选择多条边缘时，应当是连续的，以保证人偶能够正常到达')
        note.setStyleSheet(NOTE_STYLE)
        note.setWordWrap(True)
        form.addRow(note)

    def spin(self, form, label, key, value, minimum, maximum, *, decimals=0, step=1, suffix=''):
        control = WheelSafeDoubleSpinBox() if decimals else WheelSafeSpinBox()
        if decimals:
            control.setDecimals(decimals)
        shown_value = value if decimals else round(value)
        # 合法的 TOML 高级数值可能超出面板常用范围；打开时不能被钳成另一个值
        control.setRange(min(minimum, shown_value), max(maximum, shown_value))
        control.setSingleStep(step)
        control.setValue(shown_value)
        control.setSuffix(suffix)
        control.setKeyboardTracking(False)
        self.controls[key] = control
        form.addRow(label, control)

    @staticmethod
    def value(control):
        if isinstance(control, QCheckBox):
            return control.isChecked()
        if isinstance(control, QComboBox):
            return control.currentData()
        return control.value()

    def sync_dependencies(self, *args):
        c = self.controls
        for key in c:
            if key.startswith('overseer.') and key not in ('overseer.enabled', 'overseer.color'):
                c[key].setEnabled(c['overseer.enabled'].isChecked())
        for key in ('oracle.glow_color', 'oracle.glow_radius', 'oracle.glow_opacity'):
            c[key].setEnabled(c['oracle.glow_enabled'].isChecked())
        c['oracle.pearl_matrix_count'].setEnabled(c['oracle.pearl_matrix_enabled'].isChecked())
        c['oracle.pearl_matrix_avoid_radius'].setEnabled(
            c['oracle.pearl_matrix_enabled'].isChecked() and c['oracle.pearl_matrix_count'].value() > 0)
        c['oracle.pearl_playback_probability'].setEnabled(c['oracle.pearl_matrix_avoid_radius'].isEnabled())
        for key in ('oracle.pearl_bubble_max_size', 'oracle.pearl_bubble_color'):
            c[key].setEnabled(c['oracle.pearl_playback_probability'].isEnabled()
                              and c['oracle.pearl_playback_probability'].value() > 0)
        for name in ('inner', 'outer'):
            c[f'oracle.pearl_{name}_count'].setEnabled(c['oracle.pearl_orbits_enabled'].isChecked())
        c['oracle.pearl_satellite_count'].setEnabled(c['oracle.pearl_fixed_count'].value() > 0)
        halo = c['oracle.halo_enabled'].isChecked()
        c['oracle.halo_scale'].setEnabled(halo)
        c['oracle.halo_arcs_enabled'].setEnabled(halo)
        c['oracle.halo_arc_max_count'].setEnabled(halo and c['oracle.halo_arcs_enabled'].isChecked())

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, tr('选择 Rain World 安装目录'), self.game_dir.text(),
                                                QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.game_dir.setText(path)

    def candidate(self):
        text = self.game_dir.text().strip().strip('"')
        if not text:
            raise ValueError('请先选择 RainWorld 安装目录')
        directory = Path(text).expanduser().resolve()
        validate_game_directory(directory)
        groups = {name: {} for name in ('desktop', 'interaction', 'audio', 'oracle', 'overseer')}
        base_side = self.start_edge_group.checkedButton().property('edge')
        edges = [edge for edge, check in self.edge_checks.items() if check.isChecked()]
        groups['oracle'].update(base_side=base_side, allowed_edges=validate_edges(edges, base_side))
        for key, control in self.controls.items():
            value = self.value(control)
            group, field = key.split('.')
            if value == self.initial_values[key]:
                if key in self._reset_values:
                    groups[group][field] = self._reset_values[key]
                continue  # 不把未编辑的精确数值按控件显示位数重新舍入
            groups[group][field] = value / 100 if key in PERCENTAGES else value
        return replace(self.original, game_dir=directory,
                       **{name: replace(getattr(self.original, name), **values) for name, values in groups.items()})

    def busy(self, value):
        self.form.setEnabled(not value)
        self.buttons.setEnabled(not value)
        self.close_button.setEnabled(not value)

    def save(self):
        if self.worker is not None:
            return
        try:
            self.pending = self.candidate()
        except (OSError, ValueError, TypeError) as exc:
            self.set_status(exc)
            return
        self.busy(True)
        self.set_status('正在获取游戏资源，请稍候...')
        if self.assets is not None and self.pending.game_dir == self.original.game_dir:
            self.finish_save(self.assets)
        else:
            self.worker = AssetPreparation(self.pending, self)
            self.worker.finished.connect(self.assets_ready)
            self.worker.start()

    def assets_ready(self):
        worker, self.worker = self.worker, None
        if worker is None:
            return
        worker.deleteLater()
        if self._shutdown:
            return
        if worker.error:
            self.busy(False)
            self.set_status(worker.error)
            return
        self.finish_save(worker.result)

    def finish_save(self, assets):
        try:
            if self.commit is not None:
                self.commit(self.pending, assets)
            else:
                self.store.save(self.pending)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.busy(False)
            self.set_status(Message('保存失败：{error}', error=exc))
            return
        self.saved_config, self.prepared_assets = self.pending, assets
        self.accept()

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)

    def shutdown(self):
        self._shutdown = True
        if self.worker is not None:
            self.worker.finished.disconnect(self.assets_ready)
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        pixel_box(painter, self.rect(), radius=16)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'directory_hint'):
            # 小工作区优先给参数留空间；完整目录说明仍可悬停查看
            self.directory_hint.setVisible(self.height() >= 540)

    def eventFilter(self, watched, event):
        if watched is getattr(self, 'buttons', None) and event.type() == QEvent.Type.LanguageChange:
            QTimer.singleShot(0, self, self._texts.retranslate)
        if watched is getattr(self, 'header', None):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self.windowHandle() is None or not self.windowHandle().startSystemMove():
                    self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
        return super().eventFilter(watched, event)

    def fit_workarea(self, rect):
        self._workarea = rect
        self.resize(min(self.width(), max(320, rect.width()-32)), min(self.height(), max(320, rect.height()-48)))
        self.move(rect.center().x()-self.width()//2, rect.center().y()-self.height()//2)
