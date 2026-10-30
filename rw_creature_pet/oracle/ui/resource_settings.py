"""设置面板的资源状态覆盖与只读刷新，不修改控件值或角色偏好"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel

from ...i18n import tr
from ...resources import Availability, load_catalog
from ...resources.status import ResourceReport
from ..assets import resource_key


class ResourceSettings(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.catalog = load_catalog()
        self.worker = None
        self._undo = []
        self._queued = False
        self._force = False
        self._closed = False
        self._runtime_request = None
        self.report = dialog.assets.resources if dialog.assets is not None else ResourceReport()
        self.checked_assets = dialog.assets
        self.checked_key = resource_key(dialog.original)
        self._voice = dialog.controls['oracle.voice'].currentData()
        dialog.controls['oracle.voice'].currentIndexChanged.connect(self.schedule)
        dialog.game_dir.editingFinished.connect(self.schedule)
        dialog.resource_refresh.clicked.connect(lambda: self.schedule(force=True))

    def restore(self):
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()

    def _label(self, control):
        if isinstance(control, QCheckBox):
            return control
        current = control
        labels = self.dialog.form.findChildren(QLabel)
        while current is not None and current is not self.dialog.form:
            for label in labels:
                if label.buddy() is current:
                    return label
            current = current.parentWidget()
        for layout in self.dialog.form.findChildren(QFormLayout):
            label = layout.labelForField(control)
            if isinstance(label, QLabel):
                return label
        return None

    def _reason(self, binding):
        messages = []
        for key in self.report.missing_for(binding, self.catalog):
            resource = self.catalog.resources[key]
            messages.extend(tr(text) for text in (resource.unavailable_message, resource.recovery_hint) if text)
        return '\n'.join(dict.fromkeys(messages)) or tr('所需资源不可用')

    def _disable(self, control, reason):
        enabled = not control.testAttribute(Qt.WidgetAttribute.WA_ForceDisabled)
        tooltip = control.toolTip()
        self._undo.append(lambda c=control, e=enabled, t=tooltip: (c.setEnabled(e), c.setToolTip(t)))
        control.setEnabled(False)
        control.setToolTip(reason)
        label = self._label(control)
        if label is not None and label not in self._marked_labels:
            self._marked_labels.add(label)
            text, tip = label.text(), label.toolTip()
            self._undo.append(lambda w=label, t=text, h=tip: (w.setText(t), w.setToolTip(h)))
            label.setText(tr('{label}（不可用）', label=text))
            label.setToolTip(reason)

    def apply(self):
        # 由 sync_dependencies 在常规依赖处理后调用，避免两层互相覆盖
        d = self.dialog
        self._marked_labels = set()
        if self.worker is not None:
            d.resource_refresh.setText(tr('正在检查资源...'))
        for key, binding in self.catalog.settings.items():
            state = self.catalog.setting_state(key, self.report.states)
            if key == 'voice_controls' and d.controls['oracle.voice'].currentData() == 'bell':
                state = self.catalog.feature_state('voice_bell', self.report.states)
            if state != Availability.UNAVAILABLE:
                continue
            reason = self._reason(binding)
            for path in binding.paths:
                control = d.controls.get(path)
                if control is None:
                    continue
                if binding.option is not None:
                    if not isinstance(control, QComboBox):
                        continue
                    index = control.findData(binding.option)
                    if index < 0:
                        continue
                    item = control.model().item(index)
                    text, tip, flags = item.text(), item.toolTip(), item.flags()
                    self._undo.append(lambda i=item, t=text, h=tip, f=flags:
                                      (i.setText(t), i.setToolTip(h), i.setFlags(f)))
                    with QSignalBlocker(control):
                        item.setText(tr('{label}（不可用）', label=text))
                        item.setToolTip(reason)
                        item.setEnabled(False)
                    if control.currentData() == binding.option:
                        tooltip = control.toolTip()
                        self._undo.append(lambda c=control, t=tooltip: c.setToolTip(t))
                        control.setToolTip(reason)
                    # 允许切换到 none；选中的缺失选项仍保留，不静默改值
                else:
                    for editor in d.color_editors.get(path, (control,)):
                        self._disable(editor, reason)

    def dependencies_changed(self):
        voice = self.dialog.controls['oracle.voice'].currentData()
        if voice != self._voice:
            self._voice = voice
            self.schedule()

    def ensure_runtime(self, config):
        """角色自动保存只使用已提交的安装目录，不借用尚未保存的目录草稿"""
        if self.dialog.assets is not None and not self.dialog.assets.reusable(config):
            self._runtime_request = config
            self.schedule()

    @property
    def has_pending_runtime(self):
        return self._runtime_request is not None

    def _finish_close_request(self):
        d = self.dialog
        if d._close_after_resource_check and not self.has_pending_runtime:
            d._close_after_resource_check = False
            QTimer.singleShot(0, d, d.reject)
            return True
        return False

    def schedule(self, *args, force=False):
        if self._closed:
            return
        self._force |= force
        if not self._queued:
            self._queued = True
            QTimer.singleShot(0, self, self.refresh)

    def refresh(self):
        self._queued = False
        if self._closed or self.worker is not None or self.dialog.worker is not None:
            return
        d = self.dialog
        config, self._runtime_request = self._runtime_request, None
        runtime = config is not None
        if not runtime:
            force, self._force = self._force, False
            directory = Path(d.game_dir.text().strip().strip('"')).expanduser().resolve()
            config = replace(d.original, game_dir=directory, oracle=replace(d.original.oracle,
                              voice=d.controls['oracle.voice'].currentData()))
            if not force:
                if d.assets is None or (self.checked_assets is not None and self.checked_key == resource_key(config)
                                       and self.checked_assets.reusable(config)):
                    return
            # 显式重新检查包含未选中的 Bell，但不改变用户选中的 none
            if force:
                config = replace(config, oracle=replace(config.oracle, voice='bell'))
        from .settings import AssetPreparation
        self.worker = AssetPreparation(config, d)
        self.worker.for_runtime = runtime
        self.worker.finished.connect(self.ready)
        d.resource_refresh.setEnabled(False)
        d.resource_refresh.setText(tr('正在检查资源...'))
        d.buttons.setEnabled(False)
        d.apply_button.setEnabled(False)
        d.close_button.setEnabled(False)
        self.worker.start()

    def ready(self):
        worker, self.worker = self.worker, None
        if worker is None:
            return
        worker.deleteLater()
        if self._closed:
            return
        d = self.dialog
        d.resource_refresh.setEnabled(True)
        d.resource_refresh.setText(tr('重新检查资源'))
        d.buttons.setEnabled(True)
        d.apply_button.setEnabled(True)
        d.close_button.setEnabled(True)
        current = replace(d.original, game_dir=Path(d.game_dir.text().strip().strip('"')).expanduser().resolve())
        applied = d.preset_workflow.applied
        matches_draft = resource_key(current) == resource_key(worker.config)
        matches_runtime = resource_key(applied) == resource_key(worker.config)
        if not matches_draft and not (worker.for_runtime and matches_runtime):
            self.schedule(force=self._force)
            return
        if worker.error:
            d.set_status(worker.error)
            d.resource_refresh.setToolTip(tr(worker.error))
            self._resume_autosave()
            if self._runtime_request is not None or self._force:
                self.schedule()
            else:
                self._finish_close_request()
            return
        d.resource_refresh.setToolTip('')
        if matches_draft:
            self.report = worker.result.resources
            self.checked_assets = worker.result
            self.checked_key = resource_key(worker.config)
        # 不把对尚未保存安装目录的检查写进当前运行实例
        if d.assets is not None and matches_runtime:
            d.assets = worker.result
            d.prepared_assets = worker.result
            if d.resource_commit is not None:
                d.resource_commit(worker.result)
        d.sync_dependencies()
        d.set_status('资源检查完成')
        self._resume_autosave()
        if self._finish_close_request():
            return
        # 刷新期间切换语音时，旧结果只能补充资源，不能丢掉最新检查请求
        if d.assets is not None:
            self.schedule(force=self._force)

    def _resume_autosave(self):
        workflow = getattr(self.dialog, 'preset_workflow', None)
        if (workflow is not None and self.dialog.assets is not None
                and workflow.dirty and workflow.state.autosave):
            workflow.timer.start()

    def install(self, assets):
        self.report = assets.resources
        self.checked_assets = assets
        self.checked_key = resource_key(self.dialog.original)
        self.dialog.sync_dependencies()

    def shutdown(self):
        self._closed = True
        if self.worker is not None:
            self.worker.finished.disconnect(self.ready)
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None
