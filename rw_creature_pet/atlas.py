"""从本机 resources.assets 读取主图集，缓存到用户目录，不修改游戏。"""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform


class AtlasError(RuntimeError):
    pass


def extract_atlas(game_dir: Path) -> Path:
    source = game_dir / 'RainWorld_Data' / 'resources.assets'
    if not source.is_file():
        raise AtlasError(f'找不到游戏图集容器：{source}；请检查 config.toml 的 game_dir')
    stat = source.stat()
    identity = f'{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}'
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    root = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache')) / 'rw_creature_pet' / 'atlases' / key
    if (root / 'rainWorld.png').is_file() and (root / 'rainWorld.json').is_file():
        return root
    try:
        import UnityPy
        environment = UnityPy.load(str(source))
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root) as temp:
            temp = Path(temp)
            for obj in environment.objects:
                if obj.type.name not in ('Texture2D', 'TextAsset'):
                    continue
                data = obj.read()
                if data.m_Name != 'rainWorld':
                    continue
                if obj.type.name == 'Texture2D':
                    data.image.save(temp / 'rainWorld.png')
                else:
                    raw = data.m_Script
                    if isinstance(raw, str):
                        raw = raw.encode('utf-8', 'surrogateescape')
                    json.loads(raw)  # 写入完整且有效的映射后才公布缓存。
                    (temp / 'rainWorld.json').write_bytes(raw)
            if not all((temp / name).is_file() for name in ('rainWorld.png', 'rainWorld.json')):
                raise AtlasError('resources.assets 中未找到完整 rainWorld 主图集')
            for name in ('rainWorld.png', 'rainWorld.json'):
                (temp / name).replace(root / name)
    except AtlasError:
        raise
    except Exception as exc:
        raise AtlasError(f'提取游戏图集失败：{exc}') from exc
    return root


class Atlas:
    def __init__(self, root: Path):
        try:
            self.frames = json.loads((root / 'rainWorld.json').read_text(encoding='utf-8'))['frames']
            self.image = QImage(str(root / 'rainWorld.png'))
            if self.image.isNull():
                raise ValueError('PNG 无法解码')
        except (OSError, ValueError, KeyError) as exc:
            raise AtlasError(f'无法读取图集缓存 {root}：{exc}') from exc
        self.cache = {}
        self.root = root

    def sprite(self, name: str, tint: str = '#ffffff') -> QImage:
        key = (name, tint)
        if key in self.cache:
            return self.cache[key]
        try:
            frame = self.frames[name + '.png']
        except KeyError as exc:
            raise AtlasError(f'游戏主图集缺少贴图：{name}') from exc
        rect = frame['frame']
        image = self.image.copy(rect['x'], rect['y'], rect['w'], rect['h'])
        if frame.get('rotated'):
            image = image.transformed(QTransform().rotate(-90))
        if frame.get('trimmed'):
            size, offset = frame['sourceSize'], frame['spriteSourceSize']
            padded = QImage(size['w'], size['h'], QImage.Format.Format_ARGB32_Premultiplied)
            padded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(padded)
            painter.drawImage(offset['x'], offset['y'], image)
            painter.end()
            image = padded
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        if tint != '#ffffff':
            mask = image.copy()
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            painter.fillRect(image.rect(), QColor(tint))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.drawImage(0, 0, mask)
            painter.end()
        # 动态颜色不能无限积累着色贴图。
        if len(self.cache) >= 512:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = image
        return image


if __name__ == '__main__':
    from .config import DEFAULT_GAME_DIR
    print(extract_atlas(DEFAULT_GAME_DIR))
