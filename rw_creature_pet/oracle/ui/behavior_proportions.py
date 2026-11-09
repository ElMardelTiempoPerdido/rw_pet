"""比例展示与原角色字段间的映射，加载只读，用户修改时整组提交"""
from contextlib import ExitStack

from PySide6.QtCore import QEvent, QSignalBlocker, Qt
from PySide6.QtWidgets import QMenu

from ...i18n import tr
from ...presets.common import get_value
from ...shared.messages import Message
from .proportion_slider import ProportionEditor, shares


def as_shares(values, mode):
    if mode == 'binary':
        return shares((1-values[0], values[0]))
    if mode == 'hands':
        both, alternating = values
        return shares((1-both, both*(1-alternating), both*alternating))
    return shares(values)


def from_shares(values, mode, previous):
    if mode == 'binary':
        return (values[1]/1000,)
    if mode == 'hands':
        both = values[1]+values[2]
        return (both/1000, values[2]/both if both else previous[1])
    return tuple(value/10 for value in values)


class BehaviorProportions(ProportionEditor):
    def __init__(self, dialog, config, prefix, names, labels, *, mode, tooltip):
        super().__init__(labels)
        self.dialog, self.mode = dialog, mode
        self.paths = tuple(prefix+name for name in names)
        self.sources = []
        for name, key in zip(names, self.paths):
            value = getattr(config, name) * (1 if mode == 'weights' else 100)
            source = dialog.spin_control(key, value, 0, 100, decimals=1,
                                         suffix='' if mode == 'weights' else ' %')
            source.setParent(self)
            source.hide()
            source.installEventFilter(self)
            source.valueChanged.connect(self.refresh)
            self.sources.append(source)
        self.setToolTip(tooltip)
        # self.slider.setToolTip('拖动分界线调整相邻选项，合计始终为 100%')
        self.edited.connect(self.commit)
        for widget in (self.slider, *self.inputs, *(control.lineEdit() for control in self.inputs)):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda point, w=widget: self.context(w, point))

    def source_values(self):
        if hasattr(self.dialog, 'initial_values'):
            return [self.dialog.draft_value(path) for path in self.paths]
        return [get_value(self.dialog.original, path) for path in self.paths]

    def refresh(self, *_):
        self.set_values(as_shares(self.source_values(), self.mode))
        self.set_editable(self.sources[0].isEnabled())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange and self.sources:
            self.set_editable(self.sources[0].isEnabled())
        return super().eventFilter(watched, event)

    def commit(self, values):
        self.write(from_shares(values, self.mode, self.source_values()))

    def write(self, values):
        workflow = self.dialog.preset_workflow
        with workflow.suspended(), ExitStack() as stack:
            for source in self.sources:
                stack.enter_context(QSignalBlocker(source))
            for path, source, value in zip(self.paths, self.sources, values):
                self.dialog.fill_control(path, source, value)
        self.dialog.sync_dependencies()
        workflow.changed(self.paths[0])

    def reset(self):
        try:
            defaults = self.dialog.preset_workflow.default_config()
            self.write([get_value(defaults, path) for path in self.paths])
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self.dialog.set_status(Message('无法恢复此项默认值：{error}', error=exc))

    def context(self, widget, point):
        menu = widget.createStandardContextMenu() if hasattr(widget, 'createStandardContextMenu') else QMenu(widget)
        if menu.actions():
            menu.addSeparator()
        menu.addAction(tr('恢复这组默认值'), self.reset)
        menu.exec(widget.mapToGlobal(point))
        menu.deleteLater()


def proportion_group(dialog, form, config, prefix, names, labels, *, mode='weights', tooltip=''):
    editor = BehaviorProportions(dialog, config, prefix, names, labels, mode=mode, tooltip=tooltip)
    form.addRow(editor)
    if not hasattr(dialog, 'proportion_groups'):
        dialog.proportion_groups = {}
    dialog.proportion_groups[editor.paths[0]] = editor
    editor.refresh()
    return editor
