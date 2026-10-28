"""用户设置：角色调整自动保存，本机偏好显式应用，首次启动与托盘共用入口"""
from dataclasses import replace
from math import ceil, floor
from pathlib import Path

from PySide6.QtCore import QEvent, QThread, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QMessageBox,
                               QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QScrollArea,
                               QSizeGrip, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout, QWidget, QFrame)

from ...settings_store import load_defaults, validate_game_directory
from ...i18n import WidgetTexts, language_manager, tr
from ...shared.messages import Message
from ...shared.screens import find_screen, screen_identity, screen_key
from ...ui_config import UiConfig
from ...overseer.config import APPEARANCE_COLORS, FILAMENT_COUNT_MIN, FILAMENT_COUNT_MAX, SIZE_RANGE, OverseerSlot
from ..assets import prepare_oracle_assets
from ..characters import CHARACTERS, PRINCE_COLOR_NAMES
from ..config import (COLOR_LABELS, CUSTOM_LENGTH_UNITS, DISPLAY_SCALES,
                      EDGE_NAMES, INNER_COLLAR_WIDTH_MAX, validate_edges)
from ..space import EDGE_FRACTION_MAX
from .space import screen_space, selected_screen, space_description
from .inputs import ColorButton, WheelSafeSpinBox, WheelSafeDoubleSpinBox, WheelSafeComboBox
from .sections import CollapsibleSection, SectionForm
from .form_layout import ContentForm
from .face_editor import FaceDecalEditor
from .clothing_editor import CLOTHING_LABELS, ClothingDecalEditor
from .face_preview import FacePreviewDialog
from .ear_editor import EAR_LABELS, EarPartEditor
from .eye_editor import EYE_LABELS, EyeEditor
from .soft_part_editor import SOFT_PART_LABELS, SoftPartEditor
from .appearance_presets import AppearancePresetPanel
from .profile_presets import ProfilePresetPanel
from .behavior_settings import DRAG_PROBABILITIES, build_behavior_settings, sync_behavior_dependencies
from .drift_settings import DRIFT_PERCENT_FIELDS
from .mouse_settings import AVOIDANCE_PERCENT_FIELDS
from .outfit_settings import build_outfit_settings, sync_outfit_dependencies
from .cape_settings import build_cape_settings, sync_cape_settings
from .preset_workflow import PresetWorkflow
from .preset_controls import PersonalControls, AppearanceHistoryControls, bind_parameter_resets
from ...presets.appearance import apply_appearance, appearance_paths
from ...presets.common import get_value, replace_fields
from ...presets.profile import apply_profile
from ...presets.fields import paths_for
from ...presets.registry import FieldScope
from ...presets.startup import prepare_character
from .settings_style import (PixelRule, apply_settings_style, pixel_box, settings_font, PixelRuleThin,
                             NOTE_STYLE, parameter_group_background)

PERCENTAGES = {'audio.volume', 'oracle.projection_opacity', 'oracle.glow_opacity',
               'oracle.edge_fraction', 'oracle.base_fraction', 'oracle.arm_scale',
               'oracle.cross_edge_probability', 'oracle.antigravity_probability',
               'oracle.pearl_playback_probability', 'oracle.drag_projection_probability',
               'oracle.reading.start_probability',
               'interaction.hover_probability', 'interaction.hover_open_probability',
               'overseer.appearance_probability', 'overseer.relocation_probability',
               'overseer.observation_probability'}
PERCENTAGES.update(('oracle.custom_appearance.robe_flare', 'oracle.custom_appearance.robe_hem_curve'))
PERCENTAGES.update('oracle.drag_reactions.'+name for name, _ in DRAG_PROBABILITIES)
PERCENTAGES.update('oracle.drift.'+name for name in DRIFT_PERCENT_FIELDS)
PERCENTAGES.update('oracle.mouse_avoidance.'+name for name in AVOIDANCE_PERCENT_FIELDS)

DISPLAY_UNITS = {key: (100., 0.) for key in PERCENTAGES}
DISPLAY_UNITS.update({'oracle.custom_appearance.'+name: units for name, units in CUSTOM_LENGTH_UNITS.items()})

SETTINGS_TABS = (
    ('general', '常规'), ('screen', '屏幕'), ('behavior', '行为'), ('pearls', '珍珠'),
    ('projection', '投影'), ('overseer', '监视者'), ('profile', '角色设置'), ('appearance', '外观细节'),
)

# 配色区每三个元素组成一行；None 保留空列，不改变其余列的宽度
# 仅控制设置面板的展示顺序，每个颜色字段保留一次
BELL_COLOR_ORDER = (
    'skin', 'eyes', 'third_eye',
    'head_shell', 'head_highlight', None,
    'robe_top', 'robe_bottom', None,
    'inner_robe','collar_trim', 'beads',
    'arm', 'arm_highlight', 'joints',
    'pearl', 'pearl_primary', 'pearl_secondary',
    'pearl_glyph', None, None,
)

CUSTOM_COLOR_ORDER = (
    'skin', 'head_shell', 'head_highlight',
    'robe_top', 'robe_bottom', None,
    'inner_robe','collar_trim', None,
    'arm', 'arm_highlight', 'joints',
    'pearl', 'pearl_primary', 'pearl_secondary',
    'pearl_glyph', None, None,
)


def display_value(key, value):
    if key not in DISPLAY_UNITS:
        return value
    scale, offset = DISPLAY_UNITS[key]
    return value*scale+offset


def stored_value(key, value):
    if key not in DISPLAY_UNITS:
        return value
    scale, offset = DISPLAY_UNITS[key]
    return (value-offset)/scale


class ScreenComboBox(WheelSafeComboBox):
    """实时设备候选；热插拔、翻译刷新都保留尚未保存的选择。"""
    def __init__(self, selection):
        super().__init__()
        self.setFixedWidth(180)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.refresh(selection=selection)
        app = QApplication.instance()
        for signal in (app.screenAdded, app.primaryScreenChanged):
            signal.connect(self.refresh)
        app.screenRemoved.connect(self.screen_removed)
        language_manager().changed.connect(self.refresh)

    def screen_removed(self, screen):
        self.refresh(excluded=screen)

    def refresh(self, *args, selection=None, excluded=None):
        key = (self.currentData() or '') if selection is None else selection
        app = QApplication.instance()
        screens = [s for s in app.screens() if s is not excluded]
        selected = find_screen(screens, key)
        blocked = self.blockSignals(True)
        self.clear()
        self.addItem(tr('主屏幕（自动）'), '')
        for screen in screens:
            name = screen.name().removeprefix('\\\\.\\')
            model = screen.model()
            label = f'{name} · {model}' if model and model.casefold() not in name.casefold() else name
            if screen is app.primaryScreen():
                label += tr('（主屏幕）')
            self.addItem(label, key if screen is selected else screen_key(screen))
            self.setItemData(self.count()-1, label, Qt.ItemDataRole.ToolTipRole)
        if key and selected is None:
            label = tr('未连接：{name}', name=screen_identity(key).get('name', key))
            self.addItem(label, key)
            self.setItemData(self.count()-1, label, Qt.ItemDataRole.ToolTipRole)
        self.setCurrentIndex(self.findData(key))
        self.blockSignals(blocked)


class _WrappingHint(QLabel):
    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(self.heightForWidth(self.width()))
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()


class OutfitSelector(QWidget):
    def __init__(self, value, *, choices=(('normal', '常规'), ('maid', '女仆套装')), horizontal=False):
        super().__init__()
        layout = QHBoxLayout(self) if horizontal else QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for name, label in choices:
            button = QRadioButton(label)
            self.buttons[name] = button
            self.group.addButton(button)
            layout.addWidget(button)
        if horizontal:
            layout.addStretch(1)
        self.setValue(value)

    def setValue(self, value):
        self.buttons[value].setChecked(True)

    def value(self):
        return next(name for name, button in self.buttons.items() if button.isChecked())


class _ParameterColumn(ContentForm):
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


class _ParameterRow(QWidget):
    """按实际列宽计算行高，避免重新显示时采用窄列换行的固有高度"""

    def sizeHint(self):
        size = super().sizeHint()
        height = self.heightForWidth(self.width())
        if height >= 0:
            size.setHeight(height)
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()

def _parameter_columns(count=2):
    """等宽参数列，未使用的列仍保留空间；默认双列，调色区使用三列"""
    panel = _ParameterRow()
    row = QHBoxLayout(panel)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(24)
    columns = []
    for _ in range(count):
        cell = QWidget()
        column = _ParameterColumn(cell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setVerticalSpacing(0)
        column.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        column.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(cell, 1)
        columns.append(column)
    return panel, tuple(columns)


class _ParameterForm(SectionForm):
    """分类页中的单个输入项占左列；说明、分割线与复合选择器保持整行。"""

    def addRow(self, *args):
        if len(args) == 2 and isinstance(args[1], (QAbstractSpinBox, QComboBox, QLineEdit, QPushButton)):
            panel, (left, _) = _parameter_columns()
            left.addRow(*args)
            super().addRow(panel)
        else:
            super().addRow(*args)


class OverseerSlotsEditor(QWidget):
    """固定编号的四个可选槽位，外观、形态和颜色随整张表单统一保存"""
    def __init__(self, slots, *, default_size=.6):
        super().__init__()
        self.default_size = default_size
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows, self.colors, self.slots = {}, {}, {}
        self.appearances = {}
        self.sizes, self.filament_counts, self.filament_labels = {}, {}, {}
        for key, label in enumerate(('监视者 1', '监视者 2', '监视者 3', '监视者 4'), 1):
            row = QWidget()
            parameter_group_background(row)
            line = QGridLayout(row)
            line.setContentsMargins(8, 6, 8, 6)
            line.addWidget(QLabel(label), 0, 0)
            line.setColumnStretch(0, 1)
            line.addWidget(QLabel('类型'), 0, 1, Qt.AlignmentFlag.AlignLeft)
            appearance = QComboBox()
            appearance.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            appearance.addItem('普通', 'standard')
            appearance.addItem('朋友？', 'friend')
            appearance.currentIndexChanged.connect(lambda index, key=key: self.change_appearance(key))
            line.addWidget(appearance, 0, 2, Qt.AlignmentFlag.AlignRight)
            line.addWidget(QLabel('颜色'), 0, 3, Qt.AlignmentFlag.AlignLeft)
            color = ColorButton(OverseerSlot().color, '监视者颜色')
            color.setFixedWidth(100)
            line.addWidget(color, 0, 4, Qt.AlignmentFlag.AlignRight)
            remove = QPushButton('移除')
            remove.setAutoDefault(False)
            remove.setProperty('destructive', True)
            remove.clicked.connect(lambda checked=False, key=key: self.remove_slot(key))
            line.addWidget(remove, 0, 5, Qt.AlignmentFlag.AlignRight)
            size = WheelSafeDoubleSpinBox()
            size.setRange(*SIZE_RANGE)
            size.setDecimals(2)
            size.setSingleStep(.05)
            size.setKeyboardTracking(False)
            line.addWidget(QLabel('体型'), 1, 1, Qt.AlignmentFlag.AlignLeft)
            line.addWidget(size, 1, 2)
            count_label = QLabel('触须数量')
            count = WheelSafeSpinBox()
            count.setRange(FILAMENT_COUNT_MIN, FILAMENT_COUNT_MAX)
            count.setKeyboardTracking(False)
            for field in (count_label, count):
                policy = field.sizePolicy()
                policy.setRetainSizeWhenHidden(True)
                field.setSizePolicy(policy)
            line.addWidget(count_label, 1, 3, Qt.AlignmentFlag.AlignLeft)
            line.addWidget(count, 1, 4)
            layout.addWidget(row)
            self.rows[key], self.colors[key] = row, color
            self.appearances[key] = appearance
            self.sizes[key], self.filament_counts[key], self.filament_labels[key] = size, count, count_label
        self.add_button = QPushButton('添加监视者')
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self.add_slot)
        layout.addWidget(self.add_button)
        self.setValue(slots)

    def value(self):
        return tuple(replace(slot, color=self.colors[key].value(), appearance=self.appearances[key].currentData(),
                             size=(slot.size if self.sizes[key].value() == round(slot.size, 2)
                                   else self.sizes[key].value()),
                             filament_count=self.filament_counts[key].value())
                     for key, slot in sorted(self.slots.items()))

    def change_appearance(self, key):
        if key not in self.slots:
            return
        slot = self.slots[key]
        appearance = self.appearances[key].currentData()
        # 主动切换为朋友？时填入黑色；读取已有配置不会触发此处理
        if ((appearance != slot.appearance and appearance == 'friend')
                or self.colors[key].value() == APPEARANCE_COLORS[slot.appearance]):
            self.colors[key].setValue(APPEARANCE_COLORS[appearance])
        self.slots[key] = replace(slot, appearance=appearance, color=self.colors[key].value())
        self.update_shape_fields(key)

    def update_shape_fields(self, key):
        standard = self.appearances[key].currentData() == 'standard'
        self.filament_counts[key].setVisible(standard)
        self.filament_counts[key].setEnabled(standard)
        self.filament_labels[key].setVisible(standard)

    def setValue(self, slots):
        self.slots = {slot.id: slot for slot in slots}
        for key, row in self.rows.items():
            row.setVisible(key in self.slots)
            if key in self.slots:
                self.colors[key].setValue(self.slots[key].color)
                selector = self.appearances[key]
                selector.blockSignals(True)
                selector.setCurrentIndex(selector.findData(self.slots[key].appearance))
                selector.blockSignals(False)
                self.sizes[key].setValue(self.slots[key].size)
                self.filament_counts[key].setValue(self.slots[key].filament_count)
                self.update_shape_fields(key)
        self.add_button.setEnabled(len(self.slots) < 4)

    def add_slot(self):
        key = next((key for key in self.rows if key not in self.slots), None)
        if key is not None:
            self.setValue((*self.value(), OverseerSlot(id=key, size=self.default_size)))

    def remove_slot(self, key):
        self.setValue(tuple(slot for slot in self.value() if slot.id != key))


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
    def __init__(self, config, store, *, first_run=False, message='', assets=None, commit=None, initialization=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('桌宠初始化设置' if first_run else '桌宠设置')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        initialization = initialization or prepare_character(config, store)
        config = initialization.config
        self.character_state = initialization.state
        self._migration_notice = initialization.notice
        self.original, self.store = config, store
        language_manager().set_language(config.ui.language)
        self.assets, self.commit = assets, commit
        self.saved_config = self.prepared_assets = self.worker = None
        self.controls = {}
        self.color_editors = {}
        self.reset_tab_buttons = []
        self._reset_values = {}
        self._appearance_source = None
        self._shutdown = False
        self._drag_offset = None
        self._workarea = None
        self._space_screen = None
        self._space_connections = []
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
        hint = _WrappingHint('请选择这台电脑上雨世界的安装目录\n'
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
        self.pages = {}
        forms = {key: self.tab(key, title, reset=key != 'profile') for key, title in SETTINGS_TABS}
        general = forms['general']
        scale = WheelSafeComboBox()
        scale.setFixedWidth(100)
        for value in DISPLAY_SCALES:
            scale.addItem(f'{value:g}×', value)
        scale.setCurrentIndex(DISPLAY_SCALES.index(config.desktop.scale))
        self.controls['desktop.scale'] = scale
        left, right = self.two_columns(general)
        left.addRow('桌宠显示大小', scale)
        self.check(right, '使用更加狗啃的像素化效果', 'oracle.coarse_pixels_4x', config.oracle.coarse_pixels_4x)
        self.controls['oracle.coarse_pixels_4x'].setToolTip('仅用于 4×：勾选后放大 1× 像素，默认放大 2× 像素')
        self.check(general, '人偶想去哪去哪', 'desktop.autonomous', config.desktop.autonomous)

        auto_note = QLabel('*勾选时，人偶会自主移动；关闭后仍可原地阅读珍珠、观察窗口变化')
        auto_note.setStyleSheet(NOTE_STYLE)
        auto_note.setWordWrap(True)
        auto_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        general.addRow(auto_note)

        general.addRow(PixelRuleThin())

        self.check(general, '启用鼠标拖动', 'interaction.drag_enabled', config.interaction.drag_enabled)
        general.addRow(PixelRuleThin())

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

        appearance = forms['appearance']
        body = OutfitSelector(config.oracle.body_appearance,
                              choices=(('bell', '手势之铃'), ('custom', '自定义迭代器'), ('prince', 'prince')), horizontal=True)
        self.controls['oracle.body_appearance'] = body
        # 类型由角色或导入的外观决定，保留统一字段读写但不提供手动切换入口
        body.setParent(self)
        body.hide()
        outfit = OutfitSelector(config.oracle.outfit, horizontal=True)
        self.controls['oracle.outfit'] = outfit
        self.outfit_section = self.section_heading(appearance, '附加外观')
        appearance.addRow(outfit)
        build_outfit_settings(self, appearance, config.oracle)
        # 主体分支是独立小节，不能被上方的附加外观折叠一起隐藏
        appearance.addRow(PixelRuleThin())
        self.bell_parameters = QWidget()
        bell = _ParameterForm(self.bell_parameters)
        bell.setContentsMargins(0, 0, 0, 0)
        bell.setVerticalSpacing(20)
        bell.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        appearance.addRow(self.bell_parameters)
        self.section_heading(bell, '配色')
        self.color_palette(bell, 'oracle.colors', config.oracle.colors, BELL_COLOR_ORDER,
                           bubble_color=config.oracle.pearl_bubble_color)
        self.prince_parameters = QWidget()
        prince = _ParameterForm(self.prince_parameters)
        prince.setContentsMargins(0, 0, 0, 0)
        prince.setVerticalSpacing(20)
        prince.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        appearance.addRow(self.prince_parameters)
        self.section_heading(prince, '配色')
        self.color_palette(prince, 'oracle.prince_colors', config.oracle.prince_colors, PRINCE_COLOR_NAMES,
                           bubble_color=config.oracle.pearl_bubble_color)
        self.custom_parameters = QWidget()
        custom = _ParameterForm(self.custom_parameters)
        custom.setContentsMargins(0, 0, 0, 0)
        custom.setVerticalSpacing(20)
        custom.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        appearance.addRow(self.custom_parameters)
        self.face_preview = None
        self._face_preview_pending = False
        self.face_editors = {}
        self.ear_editors = {}
        self.eye_editors = {}
        self.soft_part_editors = {}
        self.clothing_editors = {}

        self.section_heading(custom, '配色')
        self.color_palette(custom, 'oracle.custom_colors', config.oracle.custom_colors, CUSTOM_COLOR_ORDER,
                           bubble_color=config.oracle.pearl_bubble_color)
        custom.addRow(PixelRuleThin())

        preview_button = QPushButton('在预览视图中调整面部！')
        preview_button.setAutoDefault(False)
        preview_button.clicked.connect(self.open_face_preview)
        custom.addRow(preview_button)

        self.section_heading(custom, '眼睛')
        shape = config.oracle.custom_appearance
        for column, (name, title) in zip(self.two_columns(custom), EYE_LABELS.items()):
            editor = EyeEditor(title, getattr(shape, name))
            self.eye_editors[name] = editor
            self.controls['oracle.custom_appearance.'+name] = editor
            column.addRow(editor)
        custom.addRow(PixelRuleThin())

        self.section_heading(custom, '面部贴图')
        # png_note = QLabel('最大 32×32 像素，x 向右、y 向下')
        # png_note.setWordWrap(True)
        # png_note.setStyleSheet(NOTE_STYLE)
        # custom.addRow(png_note)
        for name, title in (('forehead', '额头标记 PNG'), ('face', '面部装饰 PNG')):
            editor = FaceDecalEditor(title, getattr(shape, name), self.store.path.parent/'appearance/images')
            self.face_editors[name] = editor
            self.controls['oracle.custom_appearance.'+name] = editor
            custom.addRow(editor)
        custom.addRow(PixelRuleThin())

        self.section_heading(custom, '耳机部件')
        for name, title in EAR_LABELS.items():
            editor = EarPartEditor(title, getattr(shape, name), self.store.path.parent/'appearance/images')
            self.ear_editors[name] = editor
            self.controls['oracle.custom_appearance.'+name] = editor
            custom.addRow(editor)
        custom.addRow(PixelRuleThin())

        self.section_heading(custom, '基础体型')
        left, right = self.two_columns(custom)
        key = 'oracle.custom_appearance.head_length'
        # 可输入的端点向有效范围内舍入，避免 0.1px 精度反算出越界比例
        self.spin(left, '头部长度', key, display_value(key, shape.head_length),
                  ceil(display_value(key, .7)*10)/10, floor(display_value(key, 1.5)*10)/10,
                  decimals=1, step=1, suffix=' px')
        self.spin(right, '颈部宽度', 'oracle.custom_appearance.neck_width', shape.neck_width,
                  1, 8, decimals=1, step=.5, suffix=' px')
        left, right = self.two_columns(custom)
        self.spin(left, '胸肩宽度', 'oracle.custom_appearance.chest_width', shape.chest_width,
                  8, 18, decimals=1, step=.5, suffix=' px')
        self.spin(right, '胸肩上缘高度', 'oracle.custom_appearance.chest_height', shape.chest_height,
                  4, 10, decimals=1, step=.5, suffix=' px')
        self.controls['oracle.custom_appearance.chest_height'].setToolTip(
            '胸部中心至胸肩最高点的距离；领口起始高度保持独立')
        self.spin(custom, '肩膀宽度', 'oracle.custom_appearance.shoulder_width', shape.shoulder_width,
                  4, 18, decimals=1, step=.5, suffix=' px')
        self.controls['oracle.custom_appearance.shoulder_width'].setToolTip(
            '左右袖根参考点之间的距离；调大时上肩向外展开、肩线更平，胸肩和袖口尺寸保持不变')
        left, right = self.two_columns(custom)
        self.spin(left, '袖根宽度', 'oracle.custom_appearance.sleeve_root_width', shape.sleeve_root_width,
                  2, 12, decimals=1, step=.5, suffix=' px')
        self.spin(right, '袖口宽度', 'oracle.custom_appearance.sleeve_cuff_width', shape.sleeve_cuff_width,
                  2, 16, decimals=1, step=.5, suffix=' px')
        left, right = self.two_columns(custom)
        self.spin(left, '袖口圆角', 'oracle.custom_appearance.sleeve_cuff_radius', shape.sleeve_cuff_radius,
                  0, 4, decimals=1, step=.5, suffix=' px')
        self.controls['oracle.custom_appearance.sleeve_cuff_radius'].setToolTip(
            '圆角半径；0 为直角，实际半径受袖宽与袖长限制')
        key = 'oracle.custom_appearance.robe_length'
        self.spin(right, '衣袍长度', key, display_value(key, shape.robe_length),
                  ceil(display_value(key, .7)*10)/10, floor(display_value(key, 1.5)*10)/10,
                  decimals=1, step=1, suffix=' px')
        left, right = self.two_columns(custom)
        self.spin(left, '衣袍下摆张开程度', 'oracle.custom_appearance.robe_flare', shape.robe_flare*100,
                  0, 200, step=5, suffix=' %')
        self.spin(right, '衣袍底边弯曲程度', 'oracle.custom_appearance.robe_hem_curve', shape.robe_hem_curve*100,
                  0, 200, step=5, suffix=' %')
        # note = QLabel('尺寸均为逻辑像素，宽度均为完整宽度；衣袍长度为未摆动时衣料顶端至下摆的距离，不随领口深度改变')
        # note.setWordWrap(True)
        # note.setStyleSheet(NOTE_STYLE)
        # custom.addRow(note)
        custom.addRow(PixelRuleThin())
        self.section_heading(custom, '内搭与高领')
        left, right = self.two_columns(custom)
        self.check(left, '显示内搭', 'oracle.custom_appearance.inner_robe_enabled', shape.inner_robe_enabled)
        self.check(right, '启用高领', 'oracle.custom_appearance.inner_collar_enabled', shape.inner_collar_enabled)
        self.spin(custom, '高领高度', 'oracle.custom_appearance.inner_collar_height', shape.inner_collar_height,
                  0, 8, decimals=1, step=.5, suffix=' px')
        left, right = self.two_columns(custom)
        self.spin(left, '高领上口宽度', 'oracle.custom_appearance.inner_collar_top_width', shape.inner_collar_top_width,
                  1, INNER_COLLAR_WIDTH_MAX, decimals=1, step=.5, suffix=' px')
        self.spin(right, '高领下口宽度', 'oracle.custom_appearance.inner_collar_bottom_width', shape.inner_collar_bottom_width,
                  1, INNER_COLLAR_WIDTH_MAX, decimals=1, step=.5, suffix=' px')
        for name in ('inner_robe_enabled', 'inner_collar_enabled'):
            self.controls['oracle.custom_appearance.'+name].toggled.connect(self.sync_dependencies)
        self.neckline_settings(custom, shape, config.oracle.custom_colors)
        custom.addRow(PixelRuleThin())
        self.section_heading(custom, '服装贴图')
        for name, title in CLOTHING_LABELS:
            editor = ClothingDecalEditor(title, getattr(shape, name), self.store.path.parent/'appearance/images')
            self.clothing_editors[name] = editor
            self.controls['oracle.custom_appearance.'+name] = editor
            custom.addRow(editor)
        custom.addRow(PixelRuleThin())
        self.section_heading(custom, '斗篷')
        build_cape_settings(self, custom, shape.cape)
        custom.addRow(PixelRuleThin())

        self.section_heading(custom, '柔性部件')
        # soft_note = QLabel('柔性部件用于围巾等垂挂装饰，保持鼠标穿透；尺寸为逻辑像素，X 向右、Y 向脚，随固定部位旋转')
        # soft_note.setWordWrap(True)
        # soft_note.setStyleSheet(NOTE_STYLE)
        # custom.addRow(soft_note)
        for name, title in SOFT_PART_LABELS:
            editor = SoftPartEditor(title, getattr(shape, name), self.store.path.parent/'appearance/images',
                                    columns=self.two_columns)
            self.soft_part_editors[name] = editor
            self.controls['oracle.custom_appearance.'+name] = editor
            custom.addRow(editor)
        body.group.buttonToggled.connect(self.sync_dependencies)

        pearls = forms['pearls']
        o = config.oracle
        self.check(pearls, '显示矩阵珍珠', 'oracle.pearl_matrix_enabled', o.pearl_matrix_enabled)
        self.spin(pearls, '矩阵珍珠数量', 'oracle.pearl_matrix_count', o.pearl_matrix_count, 0, 64)
        pearls.addRow(PixelRuleThin())

        self.check(pearls, '显示环绕珍珠', 'oracle.pearl_orbits_enabled', o.pearl_orbits_enabled)
        for pair in ((('内圈数量', 'pearl_inner_count'), ('外圈数量', 'pearl_outer_count')),
                     (('固定珍珠数量', 'pearl_fixed_count'), ('卫星珍珠数量', 'pearl_satellite_count'))):
            for column, (label, field) in zip(self.two_columns(pearls), pair):
                self.spin(column, label, 'oracle.' + field, getattr(o, field), 0, 32)
        pearls.addRow(PixelRuleThin())

        left, right = self.two_columns(pearls)
        self.spin(left, '播放光晕特效大小', 'oracle.pearl_bubble_max_size',
                  o.pearl_bubble_max_size, 6, 64, decimals=1, suffix=' px')
        self.pearl_bubble_color = self.color(right, '珍珠播放特效色', 'oracle.pearl_bubble_color', o.pearl_bubble_color)

        halo = forms['projection']
        left, right = self.two_columns(halo)
        self.spin(left, '投影不透明度', 'oracle.projection_opacity', o.projection_opacity * 100, 0, 100, suffix=' %')
        self.projection_color_panel = QWidget()
        projection_row = QHBoxLayout(self.projection_color_panel)
        projection_row.setContentsMargins(0, 0, 0, 0)
        self.projection_colors = {}
        for key, palette in (('oracle.colors', o.colors), ('oracle.custom_colors', o.custom_colors),
                             ('oracle.prince_colors', o.prince_colors)):
            control = self.color_control('投影颜色', key+'.pearl_glyph', palette.pearl_glyph)
            self.projection_colors[key+'.pearl_glyph'] = control
            projection_row.addWidget(control)
        right.addRow('投影颜色', self.projection_color_panel)
        self.projection_color_panel.setToolTip('编辑当前主体外观的投影颜色，各角色配色分别保存')
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

        screen_settings = forms['screen']
        screen = ScreenComboBox(config.desktop.screen)
        screen.setToolTip('保存后将桌宠移至所选显示器。未连接时暂用主屏幕，重新连接后自动返回。')
        self.controls['desktop.screen'] = screen
        screen_settings.addRow('所在屏幕', screen)
        left, right = self.two_columns(screen_settings)
        self.spin(left, '屏幕边缘活动带宽度', 'oracle.edge_fraction', o.edge_fraction * 100, 20, EDGE_FRACTION_MAX*100, decimals=1,
                  suffix=' %')
        self.controls['oracle.edge_fraction'].setToolTip('最高 49.9%，仍保留中央避让和机械臂可达范围限制')
        self.spin(right, '机械臂缩放', 'oracle.arm_scale', o.arm_scale * 100, 35, 75, decimals=1, suffix=' %')
        self.controls['oracle.arm_scale'].setToolTip(
            '相对于原作臂段长度，默认 60%；修改后会重新安置人偶并更新机械臂可达范围。')
        screen_settings.addRow(PixelRuleThin())
        self.edge_selection(screen_settings, o)

        build_behavior_settings(self, forms['behavior'], config)

        watcher = forms['overseer']
        c = config.overseer
        left, right = self.two_columns(watcher)
        self.check(left, '允许出现监视者', 'overseer.enabled', c.enabled)
        mode = WheelSafeComboBox()
        mode.addItem('随机出现', 'random')
        mode.addItem('常驻', 'resident')
        mode.setCurrentIndex(mode.findData(c.appearance_mode))
        self.controls['overseer.appearance_mode'] = mode
        right.addRow('监视者出现方式', mode)
        slots = OverseerSlotsEditor(c.slots, default_size=c.size)
        self.controls['overseer.slots'] = slots
        watcher.addRow(slots)
        watcher.addRow(PixelRuleThin())
        self.spin(watcher, '出现检查间隔', 'overseer.check_interval', c.check_interval,
                  .1, 86400, decimals=2, suffix=' 秒')
        self.spin(watcher, '出现概率', 'overseer.appearance_probability', c.appearance_probability * 100,
                  0, 100, decimals=1, suffix=' %')
        # note = QLabel('*每个槽位独立检查；常驻模式下忽略出现概率、持续时间和冷却')
        # note.setWordWrap(True)
        # note.setStyleSheet(NOTE_STYLE)
        # watcher.addRow(note)
        for prefix, labels, minimum in (('duration', ('持续时间 - 最短', '持续时间 - 最长'), .1),
                                        ('cooldown', ('冷却时间 - 最短', '冷却时间 - 最长'), 0)):
            for column, suffix, label in zip(self.two_columns(watcher), ('min', 'max'), labels):
                key = prefix + '_' + suffix
                self.spin(column, label, 'overseer.' + key, getattr(c, key), minimum,
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
        self.spin(watcher, '缩回后换位概率', 'overseer.relocation_probability', c.relocation_probability * 100,
                  0, 100, decimals=1, suffix=' %')
        hint = QLabel('*安全距离应当大于缩回距离')
        hint.setWordWrap(True)
        hint.setStyleSheet(NOTE_STYLE)
        watcher.addRow(hint)
        watcher.addRow(PixelRuleThin())
        self.spin(watcher, '监视者观察概率', 'overseer.observation_probability', c.observation_probability * 100,
                  0, 100, decimals=1, suffix=' %')
        self.spin(watcher, '间隔时间', 'overseer.observation_interval', c.observation_interval,
                  .1, 86400, decimals=2, suffix=' 秒')
        note = QLabel('*完全探出并能跟随鼠标时，每隔此时间可能会进行观察')
        note.setWordWrap(True)
        note.setStyleSheet(NOTE_STYLE)
        watcher.addRow(note)
        self.controls['overseer.enabled'].toggled.connect(self.sync_dependencies)
        mode.currentIndexChanged.connect(self.sync_dependencies)

        presets = forms['profile']
        self.profile_presets = ProfilePresetPanel(self.profile_draft, self.load_profile_preset,
                                                  lambda: self._appearance_source)
        presets.addRow(self.profile_presets)
        self.profile_defaults = QPushButton('恢复此角色默认值')
        self.profile_defaults.setAutoDefault(False)
        defaults_row = QHBoxLayout()
        defaults_row.addWidget(self.profile_defaults)
        defaults_row.addStretch(1)
        presets.addRow(defaults_row)
        presets.addRow(PixelRuleThin())
        self.appearance_presets = AppearancePresetPanel(self.appearance_draft, self.load_appearance_preset)
        presets.addRow(self.appearance_presets)
        self.appearance_history = AppearanceHistoryControls()
        presets.addRow(self.appearance_history)
        # appearance_button = QPushButton('调整外观细节')
        # appearance_button.setAutoDefault(False)
        # appearance_button.clicked.connect(lambda: self.tabs.setCurrentWidget(self.pages['appearance']))
        # presets.addRow(appearance_button)

        self.controls['oracle.pearl_matrix_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.pearl_matrix_count'].valueChanged.connect(self.sync_dependencies)
        self.controls['oracle.pearl_playback_probability'].valueChanged.connect(self.sync_dependencies)
        self.controls['oracle.pearl_orbits_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.halo_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.halo_arcs_enabled'].toggled.connect(self.sync_dependencies)
        self.controls['oracle.pearl_fixed_count'].valueChanged.connect(self.sync_dependencies)
        scale.currentIndexChanged.connect(self.sync_dependencies)
        self.sync_dependencies()
        self.initial_values = {key: self.value(control) for key, control in self.controls.items()}
        self.space_panel = QWidget()
        space_layout = QHBoxLayout(self.space_panel)
        space_layout.setContentsMargins(0, 0, 0, 0)
        self.space_hint = _WrappingHint()
        self.space_hint.setWordWrap(True)
        self.space_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.space_hint.setStyleSheet(NOTE_STYLE)
        policy = self.space_hint.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.space_hint.setSizePolicy(policy)
        space_layout.addWidget(self.space_hint, 1)
        self.recommend_button = QPushButton('填入推荐设置')
        self.recommend_button.setAutoDefault(False)
        self.recommend_button.setToolTip('仅填入机械臂缩放和活动带宽度，点击保存后生效')
        self.recommend_button.clicked.connect(self.fill_space_recommendation)
        space_layout.addWidget(self.recommend_button)
        form_layout.addWidget(self.space_panel)
        for key in ('desktop.scale', 'desktop.screen'):
            self.controls[key].currentIndexChanged.connect(self.refresh_space)
        for key in ('oracle.arm_scale', 'oracle.edge_fraction'):
            self.controls[key].valueChanged.connect(self.refresh_space)
        for check in self.edge_checks.values():
            check.toggled.connect(self.refresh_space)
        app = QApplication.instance()
        for signal in (app.screenAdded, app.screenRemoved, app.primaryScreenChanged):
            signal.connect(self.queue_space_refresh)
        layout.addWidget(self.form, 1)
        self.personal_controls = PersonalControls()
        layout.addWidget(self.personal_controls)
        self._status_message = message or ('点击保存启动桌宠' if first_run else
                                           '*修改显示大小、珍珠或活动参数时，人偶会重置位置')
        self.status = QLabel()
        self.status.setStyleSheet(NOTE_STYLE)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.reset_all_button = QPushButton('恢复程序默认设置')
        self.reset_all_button.setAutoDefault(False)
        self.reset_all_button.setToolTip('恢复所有分类及游戏目录的默认设置，点击保存后生效。')
        self.reset_all_button.clicked.connect(lambda: self.confirm_restore_defaults())
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText('保存并启动' if first_run else '保存并关闭')
        self.save_button.setProperty('primary', True)
        self.save_button.setDefault(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        self.apply_button = QPushButton('保存并应用', self)
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(lambda: self.save(close=False))
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self.reset_all_button)
        footer.addStretch(1)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.buttons)
        footer.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(footer)
        # 先归属设置窗口并加入布局，再设显隐，避免按钮短暂成为独立窗口
        self.apply_button.setVisible(not first_run)
        apply_settings_style(self)
        self.resize(800, 750)
        dynamic = tuple(widget for editor in self.image_editors
                        for widget in editor.dynamic_text_widgets)
        self._texts = WidgetTexts(self, exclude=(self.status, self.space_hint, self.appearance_owner, *dynamic,
                                                *self.appearance_presets.dynamic_text_widgets,
                                                *self.profile_presets.dynamic_text_widgets))
        # Qt 会在 LanguageChange 中恢复标准按钮文字，在它处理完后重设自定义标题
        self.buttons.installEventFilter(self)
        language_manager().changed.connect(self.retranslate)
        self.retranslate()
        for key, control in self.controls.items():
            if key.startswith(('oracle.custom_appearance.', 'oracle.custom_colors.', 'oracle.colors.', 'oracle.outfit_settings.')):
                signal = (control.group.buttonToggled if isinstance(control, OutfitSelector) else
                          control.currentIndexChanged if isinstance(control, QComboBox) else
                          control.toggled if isinstance(control, QCheckBox) else control.valueChanged)
                signal.connect(self.queue_face_preview)
        for key in ('oracle.body_appearance', 'oracle.outfit'):
            self.controls[key].group.buttonToggled.connect(self.queue_face_preview)
        self.finished.connect(self.close_face_preview)
        self.finished.connect(self.reset_sections)
        self.preset_workflow = PresetWorkflow(self)

    def showEvent(self, event):
        super().showEvent(event)
        if self._migration_notice:
            self._migration_notice = False
            QTimer.singleShot(0, self, self.confirm_legacy_parameters)

    def confirm_legacy_parameters(self):
        from .preset_dialogs import acknowledge_character_upgrade
        acknowledge_character_upgrade(self)
        if self.assets is not None:
            self.preset_workflow.flush()

    @property
    def image_editors(self):
        return (*self.face_editors.values(), *self.ear_editors.values(), *self.soft_part_editors.values(),
                *self.clothing_editors.values())

    def appearance_draft(self):
        """导出不依赖游戏路径或其他页签是否填写完整，只读取当前主体的外观草稿"""
        paths = appearance_paths(self.controls['oracle.body_appearance'].value())
        return self.scoped_draft(paths)

    def profile_draft(self):
        paths = (*paths_for(FieldScope.PROFILE),
                 *appearance_paths(self.controls['oracle.body_appearance'].value()))
        return self.scoped_draft(paths)

    def scoped_draft(self, paths):
        changes = {}
        for key in self.controls:
            if key in paths or any(path.startswith(key+'.') for path in paths):
                target = changes
                *parts, name = key.split('.')
                for part in parts:
                    target = target.setdefault(part, {})
                target[name] = self.draft_value(key)
        return replace_fields(self.original, changes)

    def load_appearance_preset(self, preset):
        config = apply_appearance(self.original, preset, self.store.path.parent/'appearance/images')
        paths = appearance_paths(config.oracle.body_appearance)
        self.fill_preset(config, paths)

    def load_profile_preset(self, preset):
        config = apply_profile(self.original, preset, self.store.path.parent/'appearance/images')
        paths = (*paths_for(FieldScope.PROFILE), *appearance_paths(config.oracle.body_appearance))
        self.fill_preset(config, paths)

    def set_appearance_source(self, source):
        self._appearance_source = source

    def fill_preset(self, config, paths):
        # 未展示字段同样进入草稿基准；仅填入本次范围，保留其他控件中的未保存修改
        self.original = config
        for key, control in self.controls.items():
            if key not in paths and not any(path.startswith(key+'.') for path in paths):
                continue
            value = get_value(config, key)
            self.fill_control(key, control, value)
        self.sync_dependencies()
        self.refresh_space()
        self.queue_face_preview()

    def fill_control(self, key, control, value):
        """预设载入和恢复默认值共用精确草稿值，避免显示位数造成参数损失"""
        shown = display_value(key, value)
        if isinstance(control, QCheckBox):
            control.setChecked(shown)
        elif isinstance(control, ScreenComboBox):
            control.refresh(selection=shown)
        elif isinstance(control, QComboBox):
            control.setCurrentIndex(control.findData(shown))
        else:
            if isinstance(control, (QSpinBox, QDoubleSpinBox)):
                if isinstance(control, QSpinBox):
                    shown = round(shown)
                control.setRange(min(control.minimum(), shown), max(control.maximum(), shown))
            control.setValue(shown)
        self._reset_values[key] = value
        self.initial_values[key] = self.value(control)

    def open_face_preview(self):
        if self.controls['oracle.body_appearance'].value() != 'custom':
            return
        if self.face_preview is None:
            self.face_preview = FacePreviewDialog(self)
            bind_parameter_resets(self, self.preset_workflow, self.face_preview)
        self.refresh_face_preview()
        self.face_preview.show()
        self.face_preview.raise_()
        self.face_preview.activateWindow()

    def close_face_preview(self, *args):
        if self.face_preview is not None:
            self.face_preview.close()

    def queue_face_preview(self, *args):
        if self.face_preview is not None and not self._face_preview_pending:
            self._face_preview_pending = True
            QTimer.singleShot(0, self, self.refresh_face_preview)

    def refresh_face_preview(self):
        self._face_preview_pending = False
        if self.face_preview is None:
            return
        if self.controls['oracle.body_appearance'].value() == 'prince':
            self.close_face_preview()
            return
        custom = self.controls['oracle.body_appearance'].value() == 'custom'
        # 与保存共用嵌套字段组装，斗篷等子组不能作为带点号的 dataclass 参数传入
        draft = self.scoped_draft(appearance_paths('custom' if custom else 'bell')).oracle
        self.face_preview.set_appearance(draft.active_colors, draft.custom_appearance if custom else None,
                                         draft.outfit, draft.outfit_settings)

    def set_status(self, message):
        self._status_message = message
        self.status.setText(tr(message))
        if self.face_preview is not None:
            self.face_preview.set_status(message)

    def draft_value(self, key):
        value = self.value(self.controls[key])
        if value == self.initial_values[key]:
            if key in self._reset_values:
                return self._reset_values[key]
            value = self.original
            for field in key.split('.'):
                value = getattr(value, field)
            return value
        return stored_value(key, value)

    def space_assessment(self, config=None):
        if config is not None:
            return screen_space(selected_screen(config.desktop.screen), config.desktop.scale,
                                config.oracle.arm_scale, config.oracle.edge_fraction, config.oracle.allowed_edges)
        edges = tuple(edge for edge, check in self.edge_checks.items() if check.isChecked())
        return screen_space(selected_screen(self.draft_value('desktop.screen')), self.draft_value('desktop.scale'),
                            self.draft_value('oracle.arm_scale'), self.draft_value('oracle.edge_fraction'), edges)

    def queue_space_refresh(self, *args):
        QTimer.singleShot(0, self, self.refresh_space)

    def refresh_space(self, *args):
        screen = selected_screen(self.draft_value('desktop.screen'))
        if screen is not self._space_screen:
            for signal in self._space_connections:
                try:
                    signal.disconnect(self.refresh_space)
                except (RuntimeError, TypeError):
                    pass
            self._space_connections.clear()
            self._space_screen = screen
            if screen is not None:
                for name in ('availableGeometryChanged', 'geometryChanged', 'logicalDotsPerInchChanged',
                             'physicalDotsPerInchChanged'):
                    signal = getattr(screen, name)
                    signal.connect(self.refresh_space)
                    self._space_connections.append(signal)
        info = self.space_assessment()
        shown = info is not None and bool(info.edges) and (not info.baseline_fits or not info.valid)
        self.space_panel.setVisible(shown)
        if shown:
            self.space_hint.setText(space_description(info, self.draft_value('desktop.scale')))
            choice = info.recommendation
            self.recommend_button.setEnabled(choice is not None and
                (abs(choice[0]-info.arm_scale) > 1e-7 or abs(choice[1]-info.fraction) > 1e-7))

    def fill_space_recommendation(self):
        info = self.space_assessment()
        if info is None or info.recommendation is None:
            return
        arm, band = info.recommendation
        for key, value in (('oracle.arm_scale', arm), ('oracle.edge_fraction', band)):
            self.controls[key].setValue(value*100)
        self.refresh_space()
        self.set_status('已填入推荐设置，点击保存后生效')

    def show_space_settings(self):
        control = self.controls['oracle.edge_fraction']
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if page.isAncestorOf(control):
                self.tabs.setCurrentIndex(index)
                page.ensureWidgetVisible(control)
                break
        self.refresh_space()

    def retranslate_texts(self):
        self._texts.retranslate()
        if hasattr(self, 'preset_workflow'):
            self.preset_workflow.sync_ui()

    def retranslate(self):
        self.retranslate_texts()
        self.appearance_presets.retranslate()
        self.profile_presets.retranslate()
        for editor in (*self.image_editors, *self.eye_editors.values()):
            editor.refresh()
        self.refresh_space()
        voice = self.controls['oracle.voice']
        voice.setItemText(voice.findData('none'), tr('不使用语音'))
        mode = self.controls['overseer.appearance_mode']
        for key, label in (('random', '随机出现'), ('resident', '常驻')):
            mode.setItemText(mode.findData(key), tr(label))
        for selector in self.controls['overseer.slots'].appearances.values():
            for key, label in (('standard', '普通'), ('friend', '朋友？')):
                selector.setItemText(selector.findData(key), tr(label))
        self.set_status(self._status_message)
        language = language_manager().language
        self.original = replace(self.original, ui=UiConfig(language))
        if hasattr(self, 'preset_workflow'):
            self.preset_workflow.applied = replace(self.preset_workflow.applied, ui=self.original.ui)
        if hasattr(self, 'pending'):
            self.pending = replace(self.pending, ui=self.original.ui)
        self.setFont(settings_font())
        self.status.setFont(self.font())
        for selector in self.controls['overseer.slots'].appearances.values():
            selector.view().setFont(self.font())
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
            self.resize(max(self.width(), min(780, rect.width() - 32)), self.height())
            # 加宽不能把原本靠屏幕右侧的关闭按钮推到工作区外
            self.move(max(rect.left(), min(self.x(), rect.right() - self.width() + 1)),
                      max(rect.top(), min(self.y(), rect.bottom() - self.height() + 1)))

    def tab(self, key, title, *, reset=True):
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
        self.pages[key] = area
        self.tabs.addTab(area, title)
        if not reset:
            return form
        reset = QPushButton('恢复本页程序默认值')
        reset.setAutoDefault(False)
        reset.clicked.connect(lambda checked=False, page=area: self.confirm_restore_defaults(self.tabs.indexOf(page)))
        self.reset_tab_buttons.append(reset)
        row = QHBoxLayout()
        if key == 'appearance':
            self.appearance_owner = QLabel()
            self.appearance_owner.setTextFormat(Qt.TextFormat.PlainText)
            self.appearance_owner.setStyleSheet(NOTE_STYLE)
            self.appearance_owner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            row.addWidget(self.appearance_owner, 1)
        else:
            row.addStretch(1)
        row.addWidget(reset)
        form.addRow(row)
        return form

    def confirm_restore_defaults(self, index=None):
        if self.worker is not None:
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr('确认恢复默认值'))
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(tr('将全部设置及游戏目录恢复为程序默认值？') if index is None else
                    tr('将「{page}」页的设置恢复为程序默认值？', page=self.tabs.tabText(index)))
        box.setInformativeText(tr('*若您开启了自动保存，此恢复操作将是不可撤销的'))
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText(tr('恢复默认值'))
        box.button(QMessageBox.StandardButton.Cancel).setText(tr('取消'))
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        apply_settings_style(box)
        if box.exec() == QMessageBox.StandardButton.Ok:
            self.restore_defaults(index)
        box.deleteLater()

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
            editors = self.color_editors.get(key, (control,))
            if key == 'oracle.body_appearance':
                continue  # 程序参数重置不改变当前角色的绘制类型
            if page is not None and not any(page.isAncestorOf(editor) for editor in editors):
                continue
            if (page is not None and page.isAncestorOf(self.projection_color_panel)
                    and key in self.projection_colors and key != self.projection_color_key()):
                continue
            value = defaults
            for field in key.split('.'):
                value = getattr(value, field)
            self.fill_control(key, control, value)
        if page is None or page.isAncestorOf(self.start_edge_group.checkedButton()):
            self.start_edge_buttons[defaults.oracle.base_side].setChecked(True)
            for edge, check in self.edge_checks.items():
                check.setChecked(edge in defaults.oracle.allowed_edges)
        if page is None:
            self.game_dir.setText(str(defaults.game_dir))
        self.sync_dependencies()
        self.refresh_space()
        self.queue_face_preview()
        self.set_status('已恢复[全部]默认设置，点击保存后生效' if page is None else
                        '已恢复[本页]默认设置，点击保存后生效')

    @staticmethod
    def two_columns(form):
        """添加等宽双列行；标签/复选框靠左，输入框靠列右侧"""
        panel, columns = _parameter_columns()
        form.addRow(panel)
        return columns

    @staticmethod
    def parameter_columns(form, count):
        panel, columns = _parameter_columns(count)
        form.addRow(panel)
        return columns

    def check(self, form, label, key, value):
        control = QCheckBox(label)
        control.setChecked(value)
        self.controls[key] = control
        form.addRow(control)

    def color(self, form, label, key, value):
        control = self.color_control(label, key, value)
        form.addRow(label, control)
        return control

    def color_palette(self, form, key, colors, names, *, bubble_color):
        for start in range(0, len(names), 3):
            row, columns = _parameter_columns(3)
            form.addRow(row)
            for column, name in zip(columns, names[start:start+3]):
                if name is None:
                    continue
                self.color(column, COLOR_LABELS[name], key+'.'+name, getattr(colors, name))
        # 共用的播放光晕颜色单列收尾，与配色区第一列对齐
        row, columns = _parameter_columns(3)
        form.addRow(row)
        self.color(columns[0], '珍珠播放特效色', 'oracle.pearl_bubble_color', bubble_color)

    def color_control(self, label, key, value):
        """同一配色可在相关分类中编辑，共用草稿值和保存边界"""
        control = ColorButton(value, label)
        control.setFixedWidth(100)
        editors = self.color_editors.setdefault(key, [])
        if editors:
            canonical = editors[0]
            control.valueChanged.connect(canonical.setValue)
            canonical.valueChanged.connect(control.setValue)
        else:
            self.controls[key] = control
        editors.append(control)
        return control

    @staticmethod
    def section_heading(form, title, *, default_collapsed=False):
        """default_collapsed=True 默认折叠；仅影响窗口初始显示，不写入用户配置"""
        return form.add_section(title, default_collapsed=default_collapsed)

    def reset_sections(self, *args):
        for section in self.findChildren(CollapsibleSection):
            section.restore_default()

    def neckline_settings(self, form, shape, colors):
        form.addRow(PixelRuleThin())
        self.section_heading(form, '衣袍领口与领边')
        prefix = 'oracle.custom_appearance.'
        selector = OutfitSelector(shape.neckline_shape, choices=(('arc', '弧形'), ('v', 'V 型')), horizontal=True)
        self.controls[prefix+'neckline_shape'] = selector
        form.addRow('衣袍领口形状', selector)
        left, right = self.two_columns(form)
        for column, label, name, low, high in (
                (left, '领口宽度', 'neckline_width', 2, 18),
                (right, '领口深度', 'neckline_depth', 0, 16)):
            self.spin(column, label, prefix+name, getattr(shape, name), low, high,
                      decimals=1, step=.5, suffix=' px')
        self.spin(form, '领口起始高度', prefix+'neckline_height', shape.neckline_height,
                  -6, 8, decimals=1, step=.5, suffix=' px')
        self.controls[prefix+'neckline_height'].setToolTip(
            '相对胸部中心，正值向头部、负值向下摆；深度从此高度向下测量，修改宽度不会改变此高度')
        left, right = self.two_columns(form)
        self.spin(left, '弧形圆润度', prefix+'neckline_roundness', shape.neckline_roundness,
                  0, 1, decimals=2, step=.05)
        self.controls[prefix+'neckline_roundness'].setToolTip('0 接近直线 V 形，数值越大越接近 U 形')
        self.spin(right, 'V 型尖端圆角', prefix+'neckline_tip_radius', shape.neckline_tip_radius,
                  0, 4, decimals=1, step=.5, suffix=' px')
        left, right = self.two_columns(form)
        self.check(left, '显示领边装饰', prefix+'neckline_trim_enabled', shape.neckline_trim_enabled)
        self.neckline_color = self.color(right, '领边颜色', 'oracle.custom_colors.collar_trim', colors.collar_trim)
        left, right = self.two_columns(form)
        self.spin(left, '领边宽度', prefix+'neckline_trim_width', shape.neckline_trim_width,
                  0, 6, decimals=1, step=.5, suffix=' px')
        self.spin(right, '领边与开口距离', prefix+'neckline_trim_gap', shape.neckline_trim_gap,
                  0, 6, decimals=1, step=.5, suffix=' px')
        self.controls[prefix+'neckline_trim_gap'].setToolTip('沿领口向衣料内侧留出的距离；0 为贴边包边，大于 0 为留有间隔的襟线')
        selector.group.buttonToggled.connect(self.sync_dependencies)
        self.controls[prefix+'neckline_trim_enabled'].toggled.connect(self.sync_dependencies)

    def projection_color_key(self):
        group = CHARACTERS[self.controls['oracle.body_appearance'].value()].palette
        return 'oracle.'+group+'.pearl_glyph'

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
        self.spin(form, '启动时在边上的位置', 'oracle.base_fraction', config.base_fraction * 100,
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
        sync_outfit_dependencies(self)
        sync_cape_settings(self)
        self.bell_parameters.setVisible(c['oracle.body_appearance'].value() == 'bell')
        self.custom_parameters.setVisible(c['oracle.body_appearance'].value() == 'custom')
        self.prince_parameters.setVisible(c['oracle.body_appearance'].value() == 'prince')
        self.outfit_section.setVisible(CHARACTERS[c['oracle.body_appearance'].value()].outfits)
        inner = c['oracle.custom_appearance.inner_robe_enabled'].isChecked()
        c['oracle.custom_appearance.inner_collar_enabled'].setEnabled(inner)
        collar = inner and c['oracle.custom_appearance.inner_collar_enabled'].isChecked()
        for field in ('height', 'top_width', 'bottom_width'):
            c['oracle.custom_appearance.inner_collar_'+field].setEnabled(collar)
        prefix = 'oracle.custom_appearance.'
        arc = c[prefix+'neckline_shape'].value() == 'arc'
        c[prefix+'neckline_roundness'].setEnabled(arc)
        c[prefix+'neckline_tip_radius'].setEnabled(not arc)
        trim = c[prefix+'neckline_trim_enabled'].isChecked()
        for name in ('neckline_trim_width', 'neckline_trim_gap'):
            c[prefix+name].setEnabled(trim)
        self.neckline_color.setEnabled(trim)
        for key, control in self.projection_colors.items():
            control.setVisible(key == self.projection_color_key())
        c['oracle.coarse_pixels_4x'].setEnabled(c['desktop.scale'].currentData() == 4.)
        for key in c:
            if key.startswith('overseer.') and key not in ('overseer.enabled', 'overseer.slots', 'overseer.appearance_mode'):
                c[key].setEnabled(c['overseer.enabled'].isChecked())
        random_mode = c['overseer.enabled'].isChecked() and c['overseer.appearance_mode'].currentData() == 'random'
        for field in ('check_interval', 'appearance_probability', 'duration_min', 'duration_max',
                      'cooldown_min', 'cooldown_max'):
            c['overseer.'+field].setEnabled(random_mode)
        for key in ('oracle.glow_color', 'oracle.glow_radius', 'oracle.glow_opacity'):
            c[key].setEnabled(c['oracle.glow_enabled'].isChecked())
        c['oracle.pearl_matrix_count'].setEnabled(c['oracle.pearl_matrix_enabled'].isChecked())
        c['oracle.pearl_matrix_avoid_radius'].setEnabled(
            c['oracle.pearl_matrix_enabled'].isChecked() and c['oracle.pearl_matrix_count'].value() > 0)
        c['oracle.pearl_playback_probability'].setEnabled(c['oracle.pearl_matrix_avoid_radius'].isEnabled())
        for editor in (c['oracle.pearl_bubble_max_size'], self.pearl_bubble_color):
            editor.setEnabled(c['oracle.pearl_playback_probability'].isEnabled()
                              and c['oracle.pearl_playback_probability'].value() > 0)
        for name in ('inner', 'outer'):
            c[f'oracle.pearl_{name}_count'].setEnabled(c['oracle.pearl_orbits_enabled'].isChecked())
        c['oracle.pearl_satellite_count'].setEnabled(c['oracle.pearl_fixed_count'].value() > 0)
        halo = c['oracle.halo_enabled'].isChecked()
        c['oracle.halo_scale'].setEnabled(halo)
        c['oracle.halo_arcs_enabled'].setEnabled(halo)
        c['oracle.halo_arc_max_count'].setEnabled(halo and c['oracle.halo_arcs_enabled'].isChecked())
        sync_behavior_dependencies(self)

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
            if value == self.initial_values[key]:
                if key not in self._reset_values:
                    continue  # 不把未编辑的精确数值按控件显示位数重新舍入
                value = self._reset_values[key]
            else:
                value = stored_value(key, value)
            target = groups
            *path, field = key.split('.')
            for part in path:
                target = target.setdefault(part, {})
            target[field] = value
        config = replace_fields(self.original, {'game_dir': directory, **groups})
        if config.oracle.body_appearance == 'custom':
            for editor in self.image_editors:
                editor.validate()
        info = self.space_assessment(config)
        if info is not None and not info.valid:
            self.show_space_settings()
            raise ValueError('场景空间不足，请扩大活动带、缩小机械臂或降低显示倍率')
        return config

    def busy(self, value):
        self.form.setEnabled(not value)
        self.buttons.setEnabled(not value)
        self.apply_button.setEnabled(not value)
        self.reset_all_button.setEnabled(not value)
        self.close_button.setEnabled(not value)
        if self.face_preview is not None:
            self.face_preview.sync_editing()

    def save(self, *, close=True):
        if self.worker is not None:
            return
        try:
            self.pending = self.candidate()
        except (OSError, ValueError, TypeError) as exc:
            self.set_status(exc)
            return
        self._close_after_save = close
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
            self.pending, personal_entry, personal_state = self.preset_workflow.prepare_commit(self.pending)
            with self.store.preset_state(personal_state):
                if self.commit is not None:
                    self.commit(self.pending, assets)
                else:
                    self.store.save(self.pending)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.busy(False)
            self.set_status(Message('保存失败：{error}', error=exc))
            return
        self.saved_config, self.prepared_assets = self.pending, assets
        # 继续编辑时以本次保存为基准，保留未编辑数值的精度并复用已准备的资源
        self.original, self.assets = self.pending, assets
        self.controls['overseer.slots'].setValue(self.pending.overseer.slots)
        self.initial_values = {key: self.value(control) for key, control in self.controls.items()}
        self._reset_values.clear()
        self.preset_workflow.committed(self.pending, personal_entry)
        self.busy(False)
        if self._close_after_save:
            self.accept()
        else:
            self.set_status('已保存并应用')

    def reject(self):
        if self.worker is None and self.preset_workflow.before_close():
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
            QTimer.singleShot(0, self, self.retranslate_texts)
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
        self.resize(min(self.width(), max(320, rect.width() - 32)), min(self.height(), max(320, rect.height() - 48)))
        self.move(rect.center().x() - self.width() // 2, rect.center().y() - self.height() // 2)
