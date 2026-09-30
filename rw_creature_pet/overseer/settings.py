"""阶段 5 的调试设置入口：实时应用、读取原配置和导出完整 JSON 副本。"""
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

from ..config import AppConfig
from ..settings_store import SettingsStore, absolute_paths


class OverseerSettingsDialog(QDialog):
    def __init__(self, model, apply_config, app_config, parent=None, *, source=None):
        super().__init__(parent)
        self.model, self.apply_config, self.app_config = model, apply_config, app_config
        self.source = source
        self.setWindowTitle('监视者事件设置（调试场景）')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        note = QLabel('参数应用到当前调试场景。暂停时所有事件计时冻结。\n'
                      '持续时间包含避让隐藏；关闭自动出现会让正在进行的事件退场。')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.controls = {}
        enabled = QCheckBox('允许自动出现')
        self.controls['enabled'] = enabled
        form.addRow(enabled)
        for key, label, low, high, suffix in (
            ('check_interval', '检查间隔', .025, 86400, ' s'),
            ('appearance_probability', '每次检查的出现概率', 0, 100, ' %'),
            ('duration_min', '持续时间 · 最短', .025, 86400, ' s'),
            ('duration_max', '持续时间 · 最长', .025, 86400, ' s'),
            ('cooldown_min', '冷却时间 · 最短', 0, 86400, ' s'),
            ('cooldown_max', '冷却时间 · 最长', 0, 86400, ' s'),
            ('withdraw_distance', '鼠标靠近缩回距离', .025, 10000, ' px'),
            ('reemerge_distance', '鼠标重新探出安全距离', .025, 10000, ' px'),
            ('puppet_withdraw_distance', '人偶靠近缩回距离', .025, 10000, ' px'),
            ('puppet_reemerge_distance', '人偶重新探出安全距离', .025, 10000, ' px'),
            ('relocation_probability', '完全缩回后换位概率', 0, 100, ' %'),
            ('safe_delay', '连续安全等待', 0, 60, ' s'),
        ):
            control = QDoubleSpinBox()
            control.setDecimals(3)
            control.setRange(low, high)
            control.setSuffix(suffix)
            control.setKeyboardTracking(False)
            self.controls[key] = control
            form.addRow(label, control)
        layout.addLayout(form)
        self.controls['appearance_probability'].setToolTip('只在空闲且冷却结束后的每个检查间隔抽签一次；不是每帧概率。')
        self.controls['reemerge_distance'].setToolTip('必须大于靠近缩回距离；单位是世界逻辑像素。')
        self.controls['relocation_probability'].setToolTip('只对计时事件生效，每次完整避让缩回只抽一次；外观预览固定原位。')
        self.preset_button = QPushButton('填入快速循环参数')
        self.reload_button = QPushButton('重新读取事件参数')
        row = QHBoxLayout()
        row.addWidget(self.preset_button)
        row.addWidget(self.reload_button)
        layout.addLayout(row)
        self.status = QLabel('未保存的修改仅用于本次调试；保存副本后可通过 --config 加载。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.apply_button = QPushButton('应用')
        self.export_button = QPushButton('保存配置副本…')
        close = QPushButton('关闭')
        row = QHBoxLayout()
        for button in (self.apply_button, self.export_button, close):
            button.setAutoDefault(False)
            row.addWidget(button)
        layout.addLayout(row)
        self.apply_button.clicked.connect(self.apply)
        self.export_button.clicked.connect(self.export)
        self.reload_button.clicked.connect(self.reload)
        self.preset_button.clicked.connect(self.preset)
        close.clicked.connect(self.close)
        self.fill(model.config)

    def fill(self, config):
        self.loaded = config
        for key, control in self.controls.items():
            value = getattr(config, key)
            if key == 'enabled':
                control.setChecked(value)
            else:
                control.setValue(value*100 if key in ('appearance_probability', 'relocation_probability') else value)
        self.initial_values = self.values()

    def values(self):
        return {key: c.isChecked() if isinstance(c, QCheckBox) else c.value()
                for key, c in self.controls.items()}

    def candidate(self):
        # 保留未显示字段和未编辑的精度，不覆盖另一个面板刚预览的颜色。
        values = {key: (getattr(self.loaded, key) if value == self.initial_values[key] else
                        value/100 if key in ('appearance_probability', 'relocation_probability') else value)
                  for key, value in self.values().items()}
        return replace(self.model.config, **values)

    def apply(self):
        try:
            config = self.candidate()
        except (ValueError, TypeError) as exc:
            self.status.setText(f'未应用：{exc}')
            return False
        self.apply_config(config)
        self.fill(config)
        self.status.setText('已应用到当前调试。新的时长范围在下次事件/冷却抽取时使用。')
        return True

    def preset(self):
        self.controls['enabled'].setChecked(True)
        for key, value in dict(check_interval=1, appearance_probability=100,
                               duration_min=4, duration_max=6, cooldown_min=2, cooldown_max=3).items():
            self.controls[key].setValue(value)
        self.status.setText('已填入：每 1 秒必定出现，持续 4～6 秒，冷却 2～3 秒。点击“应用”生效。')

    def reload(self):
        try:
            config = AppConfig.load(self.source).overseer if self.source else self.app_config.overseer
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f'读取失败，保留当前参数：{exc}')
            return
        self.fill(config)
        self.status.setText('已读取事件和避让参数；点击“应用”生效。')

    def export(self):
        try:
            config = self.candidate()
        except (ValueError, TypeError) as exc:
            self.status.setText(f'未保存：{exc}')
            return
        filename, _ = QFileDialog.getSaveFileName(self, '保存配置副本', 'overseer-settings.json', 'JSON 配置 (*.json)')
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != '.json':
            self.status.setText('请保存为 .json 文件；不覆盖原 TOML 配置。')
            return
        try:
            SettingsStore(path).save(absolute_paths(replace(self.app_config, overseer=config), self.source))
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f'保存失败：{exc}')
            return
        self.apply_config(config)
        self.fill(config)
        self.status.setText(f'已应用并保存副本：{path}\n启动时使用 --config "{path}"。')
