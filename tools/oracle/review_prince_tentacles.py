"""Prince 三条触手的配置热重载预览；也可 --output 离屏导出 PNG"""
import argparse
from dataclasses import dataclass, replace
from functools import lru_cache
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from rw_creature_pet.oracle.prince_tentacles import (
    DEFAULT_CONFIG, color, fields, load_study, number, vector,
)
from rw_creature_pet.oracle.graphics.prince_tentacles import draw_tentacles
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.shared.raster import pixel_density


DEFAULT_OUTPUT = ROOT/'artifacts/prince/prince-tentacles.png'


@dataclass(frozen=True)
class Preview:
    size: Vec2
    origin: Vec2
    background: str
    scale: float
    coarse_pixels_4x: bool
    magnify: int
    show_prince: bool
    back_offset: Vec2
    gaze: Vec2

    @classmethod
    def parse(cls, data):
        fields(data, 'size origin background scale coarse_pixels_4x magnify show_prince back_offset gaze',
               'preview')
        size = vector(data.get('size', [140, 210]), 'preview.size')
        for value in (size.x, size.y):
            if not 16 <= value <= 1024 or value != int(value):
                raise ValueError('preview.size 的宽高必须为 16～1024 的整数')
        scale = number(data.get('scale', 4.), 'preview.scale', 1., 4.)
        if scale not in (1., 1.5, 2., 3., 4.):
            raise ValueError('preview.scale 必须为 1 / 1.5 / 2 / 3 / 4')
        magnify = number(data.get('magnify', 1), 'preview.magnify', 1, 8)
        if magnify != int(magnify):
            raise ValueError('preview.magnify 必须是整数')
        if size.x*size.y*(scale*magnify)**2 > 16_000_000:
            raise ValueError('预览图过大，请减小 size 或 magnify')
        for name in ('show_prince', 'coarse_pixels_4x'):
            if not isinstance(data.get(name, True), bool):
                raise ValueError(f'preview.{name} 必须是 true 或 false')
        background = data.get('background', '#FFFFFF')
        if background != 'transparent':
            color(background, 'preview.background')
        gaze = vector(data.get('gaze', [-.75, .05]), 'preview.gaze')
        if max(abs(gaze.x), abs(gaze.y)) > 1:
            raise ValueError('preview.gaze 的 x/y 必须在 -1～1 之间')
        return cls(size, vector(data.get('origin', [42, 126]), 'preview.origin'),
                   background, scale, data.get('coarse_pixels_4x', True), int(magnify),
                   data.get('show_prince', True),
                   vector(data.get('back_offset', [0, 4]), 'preview.back_offset'), gaze)


@lru_cache(maxsize=4)
def prince_pose(gaze):
    # 只创建默认 Prince，不访问用户设置、角色库、原游戏提取或声音
    from rw_creature_pet.oracle.config import OracleConfig
    from rw_creature_pet.oracle.graphics.appearance import rotate
    from rw_creature_pet.oracle.graphics.render import OracleRenderer
    from rw_creature_pet.oracle.scene import OracleScene

    config = replace(OracleConfig(), body_appearance='prince', hide_cords=True,
                     physics_backend='python', pearl_fixed_count=0,
                     pearl_matrix_enabled=False, pearl_orbits_enabled=False)
    scene = OracleScene(config)
    origin = scene.body.chunks[0].position
    direction = Vec2(0., -1.)
    for _ in range(400):
        for p, goal in zip(scene.body.chunks, (origin, origin-direction*9)):
            p.previous_position, p.position, p.velocity = p.position, goal, Vec2()
        scene.previous_look_direction = scene.look_direction = gaze
        scene.prince_posture.step(scene.head, origin, direction, gaze)
        scene.appearance.step(scene)
    frame = scene.prince_posture.frame(origin, rotate(direction, scene.appearance.sway))
    return scene, OracleRenderer(colors=config.active_colors), frame.chest


def render(study, preview):
    density = pixel_density('adaptive', preview.scale, preview.coarse_pixels_4x)
    layer = QImage(round(preview.size.x*density), round(preview.size.y*density),
                   QImage.Format.Format_ARGB32_Premultiplied)
    layer.fill(QColor(preview.background))
    # 先准备身体，避免初始化失败时留下一个未关闭的 QPainter
    pose = prince_pose(preview.gaze) if preview.show_prince else None
    painter = QPainter(layer)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.scale(density, density)
        painter.translate(preview.origin.x, preview.origin.y)
        draw_tentacles(painter, study.tentacles)
        if pose:
            scene, renderer, chest = pose
            painter.translate(-chest.x-preview.back_offset.x, -chest.y-preview.back_offset.y)
            renderer.draw_geometry(painter, scene, arm=False, cords=False, pearl=False,
                                   halo=False, cache_body=True, raster_scale=density)
    finally:
        painter.end()
    factor = preview.scale*preview.magnify
    return layer.scaled(round(preview.size.x*factor), round(preview.size.y*factor),
                        Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)


def save_png(image, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), 'PNG'):
        raise OSError(f'无法保存 PNG：{path}')


class PreviewWindow(QWidget):
    def __init__(self, config, output):
        super().__init__()
        from rw_creature_pet.oracle.ui.settings_style import settings_font
        self.setFont(settings_font())
        self.config_path, self.output_path = Path(config), Path(output)
        self._signature = None
        self.image = None
        self.valid = False
        self.setWindowTitle('Prince 触手 - 配置预览')
        layout = QVBoxLayout(self)
        path_label = QLabel(str(self.config_path))
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        buttons = QHBoxLayout()
        for label, action in (('打开配置', self.open_config), ('重新载入', self.reload)):
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        self.export_button = QPushButton('导出 PNG')
        self.export_button.clicked.connect(self.export)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.scroll = QScrollArea()
        self.canvas = QLabel('正在读取配置')
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.resize(760, 820)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.reload()
        self.timer.start()

    def signature(self):
        try:
            stat = self.config_path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def poll(self):
        if self.signature() != self._signature:
            self.reload()

    def reload(self):
        signature = self.signature()
        try:
            study = load_study(self.config_path)
            preview = Preview.parse(study.preview)
            image = render(study, preview)
        except (OSError, ValueError) as error:
            self.valid = False
            self.export_button.setEnabled(False)
            self.status.setStyleSheet('color: #A32424')
            retained = '保留上一次有效画面' if self.image is not None else '尚无有效预览'
            self.status.setText(f'配置未应用 - {retained}\n{error}')
        else:
            self.image, self.valid = image, True
            # 图像按物理像素显示，避免 Windows 150% 缩放再插值模糊像素边缘
            self.refresh_canvas()
            self.export_button.setEnabled(True)
            self.status.setStyleSheet('')
            density = pixel_density('adaptive', preview.scale, preview.coarse_pixels_4x)
            self.status.setText(f'已载入 - {preview.scale:g}x / 像素密度 {density:g}x'
                                f' - 观察放大 {preview.magnify}x\n保存配置后自动刷新')
        self._signature = signature

    def refresh_canvas(self):
        if self.image is None:
            return
        pixmap = QPixmap.fromImage(self.image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        self.canvas.setPixmap(pixmap)
        self.canvas.resize(pixmap.deviceIndependentSize().toSize())

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and getattr(self, 'image', None) is not None:
            self.refresh_canvas()
        return result

    def open_config(self):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_path))):
            self.status.setText(f'未能打开默认编辑器，请手动编辑：{self.config_path}')

    def export(self):
        if not self.valid:
            return
        try:
            save_png(self.image, self.output_path)
        except OSError as error:
            self.status.setStyleSheet('color: #A32424')
            self.status.setText(str(error))
        else:
            self.status.setStyleSheet('')
            self.status.setText(f'已导出：{self.output_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG, help='可编辑的 TOML')
    parser.add_argument('--output', type=Path, help='离屏导出一次 PNG，不打开窗口')
    parser.add_argument('--export-path', type=Path, default=DEFAULT_OUTPUT,
                        help='窗口中“导出 PNG”的目标路径')
    args = parser.parse_args()
    if args.output:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    app = QApplication.instance() or QApplication([])
    if args.output:
        try:
            study = load_study(args.config)
            save_png(render(study, Preview.parse(study.preview)), args.output)
        except (OSError, ValueError) as error:
            parser.exit(1, f'{error}\n')
        print(args.output.resolve())
        return 0
    window = PreviewWindow(args.config.resolve(), args.export_path.resolve())
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
