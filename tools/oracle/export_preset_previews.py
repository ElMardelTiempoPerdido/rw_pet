"""将当前角色库导出为透明背景、1× 正面平视的横排 PNG。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.graphics.damage import visual_bounds
from rw_creature_pet.oracle.graphics.raster import local_canvas
from rw_creature_pet.oracle.graphics.render import OracleRenderer
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.presets.profile import apply_profile
from rw_creature_pet.presets.profile_library import ProfileLibrary
from rw_creature_pet.shared.atlas import Atlas, AtlasError, extract_atlas
from rw_creature_pet.shared.geometry import Vec2


MARGIN = 16
CHARACTER_GAP = 24
PEARL_GAP = 12  # 珠心间距；珍珠本体沿用桌宠的 6×6 像素。
PEARL_RADIUS = 3
PEARL_TOP_GAP = 12
PEARL_SLOTS = (2, 0, 1)  # 渲染器的槽位：辅色、主色、普通色。


class PreviewRenderer(OracleRenderer):
    """只排除场景支架，其他图层沿用桌宠的完整像素渲染流程。"""

    def draw_geometry(self, painter, scene, alpha=1., **kwargs):
        kwargs.update(arm=False, cords=False, pearl=False, halo=False)
        return super().draw_geometry(painter, scene, alpha, **kwargs)


@dataclass
class CharacterPreview:
    image: QImage
    renderer: PreviewRenderer
    baseline: int  # 从裁剪图顶部到衣袍底边的像素距离；Prince 使用完整图底边。


def preview_scene(config):
    # 仅调整内存中的场景。默认眼形、开闭状态、服装和附件来自角色外观。
    scene = OracleScene(replace(
        config, hide_cords=True, glow_enabled=False, halo_enabled=False,
        halo_arcs_enabled=False, pearl_matrix_enabled=False,
        pearl_orbits_enabled=False, pearl_fixed_count=0, pearl_satellite_count=0,
        sliding_base=False, physics_backend='python',
    ))
    # 新场景的身体竖直、视线为零。只让布料和附件自然垂落，
    # 不推进自主行为、观察、眨眼或身体导航，保证每次姿态一致。
    for _ in range(400):
        scene.appearance.step(scene)
        scene.soft_parts.step(scene)
        if scene.appearance.sleeping and scene.soft_parts.sleeping:
            break
    return scene


def opaque_bounds(image):
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(rgba.constBits(), dtype=np.uint8).reshape(
        rgba.height(), rgba.bytesPerLine() // 4, 4)
    ys, xs = np.nonzero(pixels[:, :rgba.width(), 3])
    if not len(xs):
        raise ValueError('角色渲染结果为空')
    left, top = int(xs.min()), int(ys.min())
    return QRect(left, top, int(xs.max())-left+1, int(ys.max())-top+1)


def render_character(scene, renderer):
    # 使用现有的保守包围盒，包含长腿、斗篷、耳饰和柔性附件。
    # 最后仅裁掉透明留白，绝不缩放像素。
    image, target = local_canvas(visual_bounds(scene), 1.)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.translate(-target.x(), -target.y())
        renderer.draw(painter, scene, raster_scale=1.)
    finally:
        painter.end()
    bounds = opaque_bounds(image)
    sprite = image.copy(bounds)
    baseline = sprite.height()
    if scene.config.body_appearance != 'prince':
        # 单独绘制衣袍，按实际 1× 像素的最低处定位，避免腿部和
        # 柔性附件影响基线；与角色图共用画布原点，保留相同像素取整。
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.translate(-target.x(), -target.y())
            renderer.draw_gown(painter, scene, 1.)
        finally:
            painter.end()
        baseline = opaque_bounds(image).bottom()+1-bounds.top()
    return CharacterPreview(sprite, renderer, baseline)


def compose_sheet(characters):
    """衣袍底部对齐，Prince 沿用完整图底部；珍珠避开所有下溢部件。"""
    if not characters:
        raise ValueError('角色库中没有可导出的角色')
    pearl_width = 2*PEARL_GAP+2*PEARL_RADIUS
    widths = [max(character.image.width(), pearl_width) for character in characters]
    baseline = max(character.baseline for character in characters)
    overflow = max(character.image.height()-character.baseline for character in characters)
    pearl_y = MARGIN+baseline+overflow+PEARL_TOP_GAP+PEARL_RADIUS
    sheet = QImage(2*MARGIN+sum(widths)+CHARACTER_GAP*(len(widths)-1),
                   pearl_y+PEARL_RADIUS+MARGIN,
                   QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(0)
    painter = QPainter(sheet)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        x = MARGIN
        for character, width in zip(characters, widths):
            sprite, renderer = character.image, character.renderer
            painter.drawImage(x+(width-sprite.width())//2,
                              MARGIN+baseline-character.baseline, sprite)
            center = x+width//2
            for offset, slot in zip((-PEARL_GAP, 0, PEARL_GAP), PEARL_SLOTS):
                renderer.draw_pearl_at(painter, Vec2(center+offset, pearl_y),
                                       0, None, slot)
            x += width+CHARACTER_GAP
    finally:
        painter.end()
    return sheet


def save_timestamped(image, directory):
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not image.save(buffer, 'PNG'):
            raise OSError('无法编码预览 PNG')
        payload = bytes(buffer.data())
    finally:
        buffer.close()
    stem = 'presets_front_1x_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    index = 0
    while True:
        suffix = '' if index == 0 else f'_{index}'
        path = directory/f'{stem}{suffix}.png'
        try:
            stream = path.open('xb')
        except FileExistsError:
            index += 1
            continue
        with stream:
            stream.write(payload)
        return path


def export_previews(profiles_dir, output_dir, game_dir):
    report = ProfileLibrary(profiles_dir).scan()
    # 配图用于发布，损坏角色必须明确报错，避免静默遗漏。
    if report.errors:
        details = '\n'.join(f'  {path}: {error}' for path, error in report.errors)
        raise ValueError('角色库存在无效配置，请修复后重试：\n'+details)
    if not report.presets:
        raise ValueError(f'角色库中没有可导出的角色：{profiles_dir}')
    for group in report.duplicates:
        print(f'重复角色 {group[0].name}：使用最新有效版本 {group[0].path}', file=sys.stderr)
    atlas = Atlas(extract_atlas(Path(game_dir).expanduser().resolve()))
    characters = []
    # apply_profile 负责验证并收齐贴图，但缓存只写入临时目录。
    with tempfile.TemporaryDirectory(prefix='rw-preset-preview-') as assets:
        for preset in report.presets:
            config = apply_profile(AppConfig(), preset, Path(assets)).oracle
            scene = preview_scene(config)
            renderer = PreviewRenderer(atlas, config.active_colors)
            character = render_character(scene, renderer)
            characters.append(character)
            sprite = character.image
            print(f'{len(characters):2}. {preset.name} ({sprite.width()}×{sprite.height()} px)')
        sheet = compose_sheet(characters)
        destination = save_timestamped(sheet, output_dir)
    print(f'已导出 {len(characters)} 个角色，{sheet.width()}×{sheet.height()} px，透明 PNG：')
    print(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles-dir', type=Path, default=ROOT/'presets/profiles',
                        help='角色库目录（默认：工程 presets/profiles）')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'artifacts/preset-previews',
                        help='输出目录（默认：工程 artifacts/preset-previews）')
    parser.add_argument('--game-dir', type=Path,
                        help='雨世界游戏目录（默认：工程 config.toml 的 game_dir）')
    args = parser.parse_args(argv)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    try:
        game_dir = args.game_dir or AppConfig.load(ROOT/'config.toml').game_dir
        export_previews(args.profiles_dir, args.output_dir, game_dir)
    except (OSError, ValueError, AtlasError) as exc:
        parser.exit(1, f'导出失败：{exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
