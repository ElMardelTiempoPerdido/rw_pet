"""面部与耳机共用的小型 PNG 导入；绘制阶段只读取有界内存缓存"""
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import logging

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSaveFile
from PySide6.QtGui import QImage, QImageReader

from ...shared.messages import Message
from ..face_config import FACE_IMAGE_MAX_SIZE

MAX_FILE_BYTES = 1024*1024
log = logging.getLogger(__name__)


def read_face_png(path):
    path = Path(path)
    if path.suffix.lower() != '.png':
        raise ValueError('请选择 PNG 格式的外观贴图')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('外观 PNG 文件不能超过 1 MB')
    reader = QImageReader(str(path))
    if bytes(reader.format()).lower() != b'png':
        raise ValueError('文件内容不是有效的 PNG 图片')
    size = reader.size()
    if not (0 < size.width() <= FACE_IMAGE_MAX_SIZE and 0 < size.height() <= FACE_IMAGE_MAX_SIZE):
        raise ValueError(Message('外观 PNG 的宽和高必须为 1～{limit} 像素', limit=FACE_IMAGE_MAX_SIZE))
    if reader.supportsAnimation() and reader.imageCount() != 1:
        raise ValueError('外观贴图仅支持静态 PNG')
    image = reader.read()
    if image.isNull():
        raise ValueError('无法读取外观 PNG 图片')
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


@lru_cache(maxsize=64)
def face_image(path):
    if not path:
        return QImage()
    try:
        return read_face_png(path)
    except (OSError, ValueError) as exc:
        log.warning('Face PNG unavailable: %s: %s', path, exc)
        return QImage()


def import_face_png(source, directory, decal):
    """验证成功后原子保存规范化副本；不改变用户配置或原文件"""
    source, directory = Path(source), Path(directory)
    image = read_face_png(source)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise OSError('无法准备外观贴图副本')
    buffer.close()
    payload = bytes(data)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/(sha256(payload).hexdigest()+'.png')
    if not target.is_file() or target.read_bytes() != payload:
        output = QSaveFile(str(target))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload) or not output.commit():
            output.cancelWriting()
            raise OSError(output.errorString())
    face_image.cache_clear()
    return replace(decal, enabled=True, image_path=str(target.resolve()), image_name=source.name)


def decal_key(decal):
    if not decal.enabled or not decal.image_path:
        return None
    return decal, face_image(decal.image_path).cacheKey()
