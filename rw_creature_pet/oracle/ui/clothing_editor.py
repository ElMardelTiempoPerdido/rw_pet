"""服装固有贴图：共用 PNG 管理、偏移和参数恢复，不提供尺寸或镜像开关"""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QSizePolicy

from ...i18n import tr
from ..clothing_config import ClothingDecal
from .face_editor import FaceDecalEditor
from .inputs import WheelSafeComboBox


CLOTHING_LABELS = (
    ('clothing_decal_1', '服装贴图 1'),
    ('clothing_decal_2', '服装贴图 2'),
    ('clothing_decal_3', '服装贴图 3'),
)
PART_LABELS = (('robe', '衣袍'), ('left_sleeve', '左袖子'), ('right_sleeve', '右袖子'))


class ClothingDecalEditor(FaceDecalEditor):
    def __init__(self, title, value, directory):
        super().__init__(title, value, directory)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = self.layout()
        layout.removeWidget(self.message)
        self.part = WheelSafeComboBox()
        self.part.setFixedWidth(100)
        for key, label in PART_LABELS:
            self.part.addItem(tr(label), key)
        self.parameter_row(3, ('所属部位', self.part))
        layout.addWidget(self.message, 4, 0, 1, 5)
        self.parameter_controls = {
            'enabled': self.enabled, 'part': self.part, 'offset_x': self.x_input,
            'offset_y': self.y_input, 'image_path': self.file_label,
        }
        self.part.currentIndexChanged.connect(lambda: self.change(part=self.part.currentData()))
        self.refresh()

    def setValue(self, value):
        if not isinstance(value, ClothingDecal):
            raise TypeError('Expected ClothingDecal')
        super().setValue(value)

    def refresh(self):
        super().refresh()
        if hasattr(self, 'part'):
            with QSignalBlocker(self.part):
                for i, (_, label) in enumerate(PART_LABELS):
                    self.part.setItemText(i, tr(label))
                self.part.setCurrentIndex(self.part.findData(self._value.part))

    def choose_file(self):
        source, _ = QFileDialog.getOpenFileName(self, tr('选择服装 PNG'), '', 'PNG (*.png)',
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.import_file(source)

    def validate(self):
        if self._value.enabled and not self._value.image_path:
            raise ValueError('请导入服装 PNG，或关闭尚未配置的贴图')
        super().validate()
