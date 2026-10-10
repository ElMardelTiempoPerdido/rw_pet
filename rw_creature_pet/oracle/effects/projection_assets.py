"""直接读取本机原版扫描图；只在资源初始化时加载，不在绘制中访问磁盘。"""
from pathlib import Path

from PySide6.QtGui import QImage

from ...shared.messages import Message


def load_projection_images(game_dir):
    root = Path(game_dir)/'RainWorld_Data/StreamingAssets/illustrations'
    images = []
    for name in ('aiimg3a.png', 'aiimg3b.png'):
        image = QImage(str(root/name))
        if image.isNull() or image.width() != 250 or image.height() != 350:
            raise ValueError(Message('扫描投影素材缺失或尺寸不正确：{path}', path=root/name))
        # 同时保留白色边框及原图 alpha；只裁去四周 25px 透明留白。
        images.append(image.copy(25, 25, 200, 300).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
    return tuple(images)


def prepare_projection(game_dir, renderer):
    try:
        renderer.projection_images = load_projection_images(game_dir)
    except (OSError, ValueError) as exc:
        renderer.projection_images = ()
        return Message('扫描投影不可用：{error}', error=exc)
    return ''
