"""Bell 用户设置：显式保存，首次启动与托盘入口使用同一窗口。"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QThread, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QScrollArea,
                               QSizeGrip, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..settings_store import validate_game_directory
from .assets import prepare_oracle_assets
from .config import DISPLAY_SCALES, EDGE_NAMES, validate_edges
from .settings_style import PixelRule, apply_settings_style, pixel_box

NOTE_STYLE = "font-size: 12px;color:#707070;"


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
        color = QColorDialog.getColor(QColor(self._color), self, self.title)
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
            self.error = f'资源准备失败：{exc}'


class OracleSettingsDialog(QDialog):
    def __init__(self, config, store, *, first_run=False, message='', assets=None, commit=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('桌宠初始化设置' if first_run else '桌宠设置')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.original, self.store = config, store
        self.assets, self.commit = assets, commit
        self.saved_config = self.prepared_assets = self.worker = None
        self.controls = {}
        self._shutdown = False
        self._drag_offset = None
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
        hint = QLabel('请选择这台电脑上雨世界的安装目录\n'
                      '一般名称为 Rain World，其中包含 RainWorld_Data、RainWorld.exe 等内容\n'
                      '首次启动时，需要一点时间从安装目录中读取资源')
        hint.setStyleSheet(NOTE_STYLE)
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.directory_hint = hint
        self.game_dir.setToolTip(hint.text())
        game.addRow('', hint)
        form_layout.addLayout(game)
        self.tabs = QTabWidget()
        form_layout.addWidget(self.tabs, 1)
        general = self.tab('常规设置')
        scale = WheelSafeComboBox()
        scale.setFixedWidth(100)
        for value in DISPLAY_SCALES:
            scale.addItem(f'{value:g}×', value)
        scale.setCurrentIndex(DISPLAY_SCALES.index(config.desktop.scale))
        self.controls['desktop.scale'] = scale
        general.addRow('桌宠显示大小', scale)
        self.check(general, '人偶想去哪去哪', 'desktop.autonomous', config.desktop.autonomous)
        self.check(general, '开启鼠标拖动', 'interaction.drag_enabled', config.interaction.drag_enabled)
        self.check(general, '隐藏线缆', 'oracle.hide_cords', config.oracle.hide_cords)
        self.controls['oracle.hide_cords'].setToolTip('隐藏粗线与头部细线，并停止线缆物理计算；机械臂保持显示。')
        self.check(general, '开启人偶语音', 'audio.enabled', config.audio.enabled)
        self.spin(general, '语音音量', 'audio.volume', config.audio.volume * 100, 0, 100, suffix=' %')
        self.controls['audio.enabled'].toggled.connect(self.controls['audio.volume'].setEnabled)
        self.controls['audio.volume'].setEnabled(config.audio.enabled)
        self.check(general, '开启外发光', 'oracle.glow_enabled', config.oracle.glow_enabled)
        glow_color = ColorButton(config.oracle.glow_color, '选择外发光颜色')
        glow_color.setFixedWidth(130)
        self.controls['oracle.glow_color'] = glow_color
        general.addRow('发光颜色', glow_color)
        self.spin(general, '发光半径', 'oracle.glow_radius', config.oracle.glow_radius,
                  1, 24, decimals=1, step=1, suffix=' px')
        # glow_note = QLabel('实体：人偶、珍珠、机械臂和线缆\n'
        #                   '光环、电弧与文字投影不发光')
        # glow_note.setWordWrap(True)
        # glow_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # general.addRow(glow_note)
        self.controls['oracle.glow_enabled'].toggled.connect(self.sync_dependencies)

        test_note = QLabel('【注意】当前桌宠为未开发完成的测试版本，可能出现各种问题\n'
                           '如需反馈bug或蹲蹲功能更新/正式版，欢迎添加此群 → 672754728\n\n'
                           '此桌宠为非官方粉丝作品，项目及其衍生版本禁止用于任何商业活动\n'
                           '原作名称/角色与素材归各自权利人所有，请支持 RainWorld！ >ㅅ<')
        test_note.setStyleSheet(NOTE_STYLE)
        test_note.setWordWrap(True)
        test_note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        test_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        general.addRow(test_note)

        pearls = self.tab('珍珠设置')
        o = config.oracle
        self.check(pearls, '显示矩阵珍珠', 'oracle.pearl_matrix_enabled', o.pearl_matrix_enabled)
        for label, field, limit in (('矩阵数量', 'pearl_matrix_count', 64),):
            self.spin(pearls, label, 'oracle.' + field, getattr(o, field), 0, limit)
        self.spin(pearls, '人偶避让矩阵半径', 'oracle.pearl_matrix_avoid_radius',
                  o.pearl_matrix_avoid_radius, 0, 300, suffix=' px')
        self.controls['oracle.pearl_matrix_avoid_radius'].setToolTip(
            '自主移动的停留点与矩阵中心保持的距离，单位为逻辑像素；0 表示关闭。')
        self.spin(pearls, '珍珠播放动画概率', 'oracle.pearl_playback_probability',
                  o.pearl_playback_probability*100, 0, 100, suffix=' %')
        self.controls['oracle.pearl_playback_probability'].setToolTip(
            '矩阵珠召近后，每次阅读抽取一次概率。动画使用 Soft Gesture 强度曲线，不播放声音；0 关闭。')
        self.spin(pearls, '播放光泡最大直径', 'oracle.pearl_bubble_max_size',
                  o.pearl_bubble_max_size, 6, 64, decimals=1, suffix=' px')
        self.controls['oracle.pearl_bubble_max_size'].setToolTip(
            '强度为 0 时直径为 6 逻辑像素，强度为 1 时达到此上限；随桌宠显示倍率缩放。')
        bubble_color = ColorButton(o.pearl_bubble_color, '选择播放光泡颜色')
        bubble_color.setFixedWidth(130)
        self.controls['oracle.pearl_bubble_color'] = bubble_color
        pearls.addRow('播放光泡颜色', bubble_color)
        self.check(pearls, '显示环绕珍珠', 'oracle.pearl_orbits_enabled', o.pearl_orbits_enabled)
        for label, field in (('内圈数量', 'pearl_inner_count'), ('外圈数量', 'pearl_outer_count'),
                             ('固定珍珠数量', 'pearl_fixed_count'), ('卫星珍珠数量', 'pearl_satellite_count')):
            self.spin(pearls, label, 'oracle.' + field, getattr(o, field), 0, 32)
        halo = self.tab('光环与电弧')
        self.check(halo, '显示光环', 'oracle.halo_enabled', o.halo_enabled)
        self.spin(halo, '光环大小', 'oracle.halo_scale', o.halo_scale, .25, 1.5, decimals=2, step=.05)
        self.check(halo, '开启电弧', 'oracle.halo_arcs_enabled', o.halo_arcs_enabled)
        self.spin(halo, '电弧数量上限', 'oracle.halo_arc_max_count', o.halo_arc_max_count, 1, 10)
        self.spin(halo, '投影不透明度', 'oracle.projection_opacity', o.projection_opacity * 100, 0, 100, suffix=' %')
        opacity_note = QLabel('投影不透明度同时用于珍珠文字、光环和电弧。')
        opacity_note.setWordWrap(True)
        halo.addRow(opacity_note)
        activity = self.tab('迭代器人偶活动')
        self.edge_selection(activity, o)
        self.spin(activity, '屏幕边缘活动带宽度', 'oracle.edge_fraction', o.edge_fraction * 100, 20, 35, decimals=1,
                  suffix=' %')
        self.spin(activity, '普通移动速度', 'oracle.float_speed', o.float_speed, .3, 2., decimals=2, step=.1)
        self.spin(activity, '漫游移动速度', 'oracle.drift_speed', o.drift_speed, .3, 1.8, decimals=2, step=.1)
        self.spin(activity, '跨到相邻边概率', 'oracle.cross_edge_probability', o.cross_edge_probability * 100, 0, 100,
                  decimals=1, suffix=' %')
        self.spin(activity, '反重力漫游概率', 'oracle.antigravity_probability', o.antigravity_probability * 100, 0, 100,
                  decimals=1, suffix=' %')
        self.spin(activity, '漫游时长', 'oracle.antigravity_duration_seconds', o.antigravity_duration_seconds,
                  1, max(3600, o.antigravity_duration_seconds), decimals=1, suffix=' 秒')
        # note = QLabel('*此概率用于人偶自主行动的选择，设置为0时，可以从工具栏手动触发漫游。')
        # note.setStyleSheet(NOTE_STYLE)
        # note.setWordWrap(True)
        # activity.addRow(note)
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
        self.status = QLabel(message or ('保存后启动桌宠。' if first_run else
                                         '*修改显示大小、珍珠或活动参数时，人偶会重置位置到当前边缘'))
        self.status.setStyleSheet(NOTE_STYLE)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
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
        # 约为旧版满行输入的 1/4；长的秒数额外预留单位和步进按钮
        for control in self.controls.values():
            if isinstance(control, (QSpinBox, QDoubleSpinBox)):
                widest = max(control.fontMetrics().horizontalAdvance(control.textFromValue(value) + control.suffix())
                             for value in (control.minimum(), control.maximum()))
                control.setFixedWidth(max(100, widest + 30))
        self.resize(620, 650)

    def tab(self, title):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        panel = QWidget()
        form = QFormLayout(panel)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(18, 22, 18, 22)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(20)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        area.setWidget(panel)
        self.tabs.addTab(area, title)
        return form

    def check(self, form, label, key, value):
        control = QCheckBox(label)
        control.setChecked(value)
        self.controls[key] = control
        form.addRow(control)

    def edge_selection(self, form, config):
        labels = {'top': '顶部', 'right': '右侧', 'bottom': '底部', 'left': '左侧'}
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
        form.addRow('人偶移动范围', panel)
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
        form.addRow('启动时的位置', row)
        note = QLabel('*至少选择一条边缘，选择多条边缘时，应当是连续的，以保证人偶能够正常到达')
        note.setStyleSheet(NOTE_STYLE)
        note.setWordWrap(True)
        form.addRow(note)

    def spin(self, form, label, key, value, minimum, maximum, *, decimals=0, step=1, suffix=''):
        control = WheelSafeDoubleSpinBox() if decimals else WheelSafeSpinBox()
        if decimals:
            control.setDecimals(decimals)
        control.setRange(minimum, maximum)
        control.setSingleStep(step)
        control.setValue(value if decimals else round(value))
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
        for key in ('oracle.glow_color', 'oracle.glow_radius'):
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
        path = QFileDialog.getExistingDirectory(self, '选择 Rain World 安装目录', self.game_dir.text())
        if path:
            self.game_dir.setText(path)

    def candidate(self):
        text = self.game_dir.text().strip().strip('"')
        if not text:
            raise ValueError('请先选择 RainWorld 安装目录')
        directory = Path(text).expanduser().resolve()
        validate_game_directory(directory)
        groups = {name: {} for name in ('desktop', 'interaction', 'audio', 'oracle')}
        base_side = self.start_edge_group.checkedButton().property('edge')
        edges = [edge for edge, check in self.edge_checks.items() if check.isChecked()]
        groups['oracle'].update(base_side=base_side, allowed_edges=validate_edges(edges, base_side))
        percentages = {'audio.volume', 'oracle.projection_opacity', 'oracle.edge_fraction',
                       'oracle.cross_edge_probability', 'oracle.antigravity_probability',
                       'oracle.pearl_playback_probability'}
        for key, control in self.controls.items():
            value = self.value(control)
            if value == self.initial_values[key]:
                continue  # 不把未编辑的精确数值按控件显示位数重新舍入
            group, field = key.split('.')
            groups[group][field] = value / 100 if key in percentages else value
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
            self.status.setText(str(exc))
            return
        self.busy(True)
        self.status.setText('正在获取游戏资源，请稍候...')
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
            self.status.setText(worker.error)
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
            self.status.setText(f'保存失败：{exc}')
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
        if watched is self.header:
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
        self.resize(min(self.width(), max(320, rect.width() - 32)), min(self.height(), max(320, rect.height() - 48)))
        self.move(rect.center().x() - self.width() // 2, rect.center().y() - self.height() // 2)
