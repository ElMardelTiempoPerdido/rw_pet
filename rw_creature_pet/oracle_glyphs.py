"""SingleGlyph 的离线等价遮罩：首次从本机纹理提取，运行时只画缓存图。"""
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtGui import QColor, QImage, QPainter

from .atlas import AtlasError


class PearlGlyphs:
    CELL_SIZE = 15
    COUNT = 14  # GlyphLabel.RandomString(..., cyrillic=False) 的候选。

    def __init__(self, path):
        image = QImage(str(path))
        if image.isNull() or image.width() != 750 or image.height() != self.CELL_SIZE:
            raise AtlasError(f'珍珠字形缓存无效：{path}')
        self.masks = tuple(image.copy(i*15, 0, 15, 15).convertToFormat(
            QImage.Format.Format_ARGB32_Premultiplied) for i in range(self.COUNT))
        self.cache = {}

    def sprite(self, glyph_id, color):
        if not 0 <= glyph_id < self.COUNT:
            raise ValueError('珍珠字符编号必须在 0～13 之间')
        key = (glyph_id, color)
        if key not in self.cache:
            image = self.masks[glyph_id].copy()
            painter = QPainter(image)
            try:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(image.rect(), QColor(color))
            finally:
                painter.end()
            if len(self.cache) >= 64:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = image
        return self.cache[key]


def load_pearl_glyphs(game_dir: Path, atlas_root: Path) -> PearlGlyphs:
    # 主图集目录已有游戏容器的路径/大小/修改时间指纹；游戏更新自动换缓存。
    path = atlas_root/'pearl-glyphs-mask-v1.png'
    if path.is_file():
        return PearlGlyphs(path)
    try:
        import UnityPy
        from PIL import Image
        source = game_dir/'RainWorld_Data/resources.assets'
        environment = UnityPy.load(str(source))
        for obj in environment.objects:
            if obj.type.name != 'Texture2D':
                continue
            data = obj.read()
            if data.m_Name != 'glyphs':
                continue
            texture = data.image.convert('RGB')
            if texture.size != (750, 15):
                raise AtlasError(f'不支持的 glyphs 纹理尺寸：{texture.size}')
            # SingleGlyph.shader: red < .5 显示颜色，其余像素透明。
            mask = Image.new('RGBA', texture.size, (255, 255, 255, 0))
            mask.putalpha(texture.getchannel('R').point(lambda red: 255 if red < 128 else 0))
            atlas_root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=atlas_root) as temp:
                cached = Path(temp)/path.name
                mask.save(cached)
                PearlGlyphs(cached)  # 验证完成后再原子公布，避免半写入缓存。
                cached.replace(path)
            return PearlGlyphs(path)
        raise AtlasError('resources.assets 中未找到 glyphs 纹理')
    except AtlasError:
        raise
    except Exception as exc:
        raise AtlasError(f'提取珍珠字形失败：{exc}') from exc
