"""七个行为维度的风格选择与高级参数展示；沿用角色编辑会话提交"""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...i18n import language_manager, tr
from ...oracle.style_config import StyleSelection
from ...presets.behavior_styles import (BehaviorStyleLibrary, DIMENSION_PATHS, PATH_DIMENSIONS,
                                       SELECTION_PREFIX, set_selection)
from .form_layout import ContentForm
from .inputs import WheelSafeComboBox
from .settings_style import NOTE_STYLE


DIMENSION_LABELS = {
    'daily_activity': '日常活动', 'drift': '反重力漫游', 'mouse_attention': '鼠标关注',
    'mouse_avoidance': '鼠标躲避', 'drag_reactions': '拖动反应',
    'reading_habits': '阅读频率', 'pearl_interaction': '阅读行动方式',
}


class StyleGroup(QWidget):
    def __init__(self, dimension, form):
        super().__init__(form.parentWidget())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(form.verticalSpacing())
        row = QHBoxLayout()
        row.addWidget(QLabel(DIMENSION_LABELS[dimension]))
        self.selector = WheelSafeComboBox()
        self.selector.setSizeAdjustPolicy(WheelSafeComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.selector.setMinimumContentsLength(8)
        self.selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(self.selector, 1)
        self.advanced = QCheckBox('显示详细参数')
        row.addWidget(self.advanced)
        layout.addLayout(row)
        self.description = QLabel()
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        self.description.setStyleSheet(NOTE_STYLE)
        self.description.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.description)
        self.content = QWidget(self)
        self.body = ContentForm(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setVerticalSpacing(form.verticalSpacing())
        self.body.setHorizontalSpacing(form.horizontalSpacing())
        self.body.setFieldGrowthPolicy(form.fieldGrowthPolicy())
        self.body.setLabelAlignment(form.labelAlignment())
        layout.addWidget(self.content)
        self.content.hide()
        # 展开只改变父容器可见性，不能重置数值或解除子控件的资源禁用状态
        self.advanced.toggled.connect(self.content.setVisible)
        form.addRow(self)


class BehaviorStyles:
    def __init__(self, dialog):
        self.dialog = dialog
        self.library = BehaviorStyleLibrary.load()
        self.groups = {}

    def add(self, dimension, form):
        group = StyleGroup(dimension, form)
        self.groups[dimension] = group
        group.selector.activated.connect(lambda _index, d=dimension: self.select(d))
        self.refresh(dimension)
        return group.body

    @property
    def dynamic_text_widgets(self):
        return tuple(widget for group in self.groups.values() for widget in (group.selector, group.description))

    def refresh(self, dimension=None):
        language = language_manager().language
        for key, group in self.groups.items():
            if dimension is not None and key != dimension:
                continue
            selected = getattr(self.dialog.original.oracle.behavior_styles, key)
            style = self.library.find(selected.id, key)
            with QSignalBlocker(group.selector):
                group.selector.clear()
                group.selector.addItem(tr('自定义'), '')
                for item in self.library.for_dimension(key):
                    group.selector.addItem(getattr(item, 'name_'+language), item.id)
                    group.selector.setItemData(group.selector.count()-1, getattr(item, 'description_'+language),
                                               Qt.ItemDataRole.ToolTipRole)
                group.selector.setCurrentIndex(group.selector.findData(style.id if style else ''))
            # if style is None:
            #     # text = tr('保留当前参数，可展开高级参数调整')
            #     text = tr('')
            # elif style.version != selected.version:
            #     text = tr('此风格定义已更新，当前参数保持原样；重新选择才会应用新版')
            # else:
            #     text = getattr(style, 'description_'+language)
            # group.description.setText(text)
            group.selector.setToolTip(tr('部分风格未能读取')+'\n'+'\n'.join(self.library.errors)
                                      if self.library.errors else '')

    def select(self, dimension):
        dialog = self.dialog
        identifier = self.groups[dimension].selector.currentData()
        style = self.library.find(identifier, dimension)
        try:
            # 整个维度原子填入，不能经过逐字段修改把自己标为自定义
            with dialog.preset_workflow.suspended():
                config = (style.apply(dialog.original) if style is not None else
                          set_selection(dialog.original, dimension, StyleSelection()))
                paths = (*DIMENSION_PATHS[dimension], SELECTION_PREFIX+dimension+'.id',
                         SELECTION_PREFIX+dimension+'.version') if style else ()
                if style:
                    dialog.fill_preset(config, paths)
                else:
                    dialog.original = config
                    self.refresh(dimension)
            dialog.preset_workflow.changed()
        except (ValueError, TypeError) as exc:
            dialog.set_status(exc)
            self.refresh(dimension)

    def edited(self, path):
        if dimension := PATH_DIMENSIONS.get(path):
            self.dialog.original = set_selection(self.dialog.original, dimension, StyleSelection())
            self.refresh(dimension)

    def reset(self, paths):
        for dimension in {PATH_DIMENSIONS[p] for p in paths if p in PATH_DIMENSIONS}:
            self.dialog.original = set_selection(self.dialog.original, dimension, StyleSelection())
        self.refresh()
