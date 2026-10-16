"""柔性 PNG 的原始尺寸；物理层只读图片元数据，不依赖 Qt"""
from functools import lru_cache

from PIL import Image

from .soft_part_config import SoftPart


@lru_cache(maxsize=64)
def soft_png_size(path):
    if path:
        try:
            with Image.open(path) as image:
                width, height = image.size
                if image.format == 'PNG' and 0 < width <= SoftPart.IMAGE_MAX_SIZE and 0 < height <= SoftPart.IMAGE_MAX_SIZE:
                    return float(width), float(height)
        except (OSError, ValueError):
            pass
    # 未选择或丢失的图片不会绘制，只保留一条最小物理链，避免使用几何尺寸替代
    return 1., 1.


def soft_part_size(config):
    return soft_png_size(config.image_path) if config.kind == 'png' else (config.width, config.length)
