"""固定 NPC 与本地目录共用一个选择器，刷新目录不会改写当前选择"""
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QSizePolicy

from ...i18n import tr
from ..audio.custom import PREFIX, CustomVoice, custom_voice_name, scan_custom_voices
from ..audio.voice import VOICE_CLIPS
from .inputs import WheelSafeComboBox


class VoiceSelector(WheelSafeComboBox):
    catalogChanged = Signal()

    def __init__(self, selected):
        super().__init__()
        self.packs = {}
        # 目录名长度不应挤掉左侧标签；完整名称仍在展开列表中显示
        self.setSizeAdjustPolicy(self.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for key in VOICE_CLIPS:
            self.addItem(tr('不使用语音') if key == 'none' else key, key)
        self.refresh(selection=selected)

    def refresh(self, *, selection=None, scan=True):
        selected = self.currentData() if selection is None else selection
        packs = scan_custom_voices() if scan else dict(self.packs)
        if (name := custom_voice_name(selected)) is not None:
            packs.setdefault(selected, CustomVoice(name))
        changed = packs != self.packs
        self.packs = packs
        with QSignalBlocker(self):
            for i in range(self.count()-1, -1, -1):
                if str(self.itemData(i)).startswith(PREFIX):
                    self.removeItem(i)
            for key, pack in sorted(packs.items(), key=lambda item: item[1].name.casefold()):
                self.addItem('', key)
            self.refresh_labels()
            self.setCurrentIndex(self.findData(selected))
        if changed:
            self.catalogChanged.emit()

    def refresh_labels(self):
        with QSignalBlocker(self):
            self.setItemText(self.findData('none'), tr('不使用语音'))
            for key, pack in self.packs.items():
                index = self.findData(key)
                label = tr('[自定义] {name}', name=pack.name)
                if pack.error:
                    label = tr('{label}（不可用）', label=label)
                item = self.model().item(index)
                item.setText(label)
                item.setEnabled(not pack.error)
                item.setToolTip(tr(pack.error) if pack.error else '')

    def showPopup(self):
        self.refresh()
        super().showPopup()
