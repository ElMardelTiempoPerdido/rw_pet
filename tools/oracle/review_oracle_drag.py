"""拖拽视觉回放；--native 在 Windows 测试窗口中验证真实输入穿透与捕获。"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if '--native' not in sys.argv:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from dataclasses import replace
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest

from rw_creature_pet.config import AppConfig
from rw_creature_pet.interaction.config import InteractionConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.scene import OracleScene
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.oracle.input import PuppetHitMap


def visual():
    config = AppConfig.load(ROOT/'config.toml')
    atlas = Atlas(extract_atlas(config.game_dir))
    renderer = OracleRenderer(atlas, config.oracle.colors)
    scene = OracleScene(config.oracle)
    scene.drag.set_enabled(True)
    sheet = QImage(1920, 1200, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor('#18212c'))
    cards = []
    for label, point, ticks in (
        ('Before / 1x', None, 120),
        ('Held outside activity band / 1x', Vec2(700, 350), 160),
        ('Arm reach limit / 1x', Vec2(700, 5000), 300),
        ('Released and returned / 1x', None, 600),
    ):
        if point is not None:
            if not scene.drag.active:
                scene.drag.press(scene.head.position, lambda _: True)
            scene.drag.move(point)
        elif scene.drag.active:
            scene.drag.release()
        for _ in range(ticks):
            scene.step()
        frame = QImage(960, 600, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(QColor('#18212c'))
        p = QPainter(frame)
        p.setPen(QColor('#334555'))
        inner = scene.world.inner
        p.drawRect(round(inner.left), round(inner.top), round(inner.right-inner.left), round(inner.bottom-inner.top))
        renderer.draw(p, scene)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(12, 22, label)
        p.end()
        cards.append(frame)
    p = QPainter(sheet)
    for i, card in enumerate(cards):
        p.drawImage((i%2)*960, (i//2)*600, card)
    p.end()
    (ROOT/'artifacts').mkdir(exist_ok=True)
    sheet.save(str(ROOT/'artifacts/oracle-drag-review.png'))
    print('Saved artifacts/oracle-drag-review.png', flush=True)


def native(app):
    import ctypes
    import json
    from unittest.mock import patch
    from rw_creature_pet.oracle.desktop import OracleDesktopWindow

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    prior_focus, prior_cursor = user32.GetForegroundWindow(), QCursor.pos()

    class Background(QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.presses = 0
            self.setStyleSheet('background-color: #26313d;')

        def mousePressEvent(self, event):
            self.presses += 1
            event.accept()

    back = Background()
    back.setGeometry(app.primaryScreen().availableGeometry())
    back.show()
    back.activateWindow()
    with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
        window = OracleDesktopWindow(AppConfig(interaction=InteractionConfig(True)), renderer=OracleRenderer())
    window.timer.stop()
    window.show()
    app.processEvents()
    window.sync_drag_input()
    # 等待原生窗口呈现并确定点击接收背景，避免把首个点击当成激活请求。
    user32.SetForegroundWindow(int(back.winId()))
    QTest.qWait(200)
    window.raise_()
    window.drag_input.raise_()
    QTest.qWait(100)
    scene = window.motion.scene
    viewport = window.motion.viewport

    def move(p):
        pos = viewport.to_global(p)
        QCursor.setPos(QPoint(round(pos.x), round(pos.y)))
        QTest.qWait(40)

    def button(down):
        user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)
        QTest.qWait(40)

    result = {}
    try:
        for name, p in (('blank', Vec2(300, 200)), ('arm_base', scene.base),
                        ('halo', scene.halo.center+Vec2(48, 0))):
            before = back.presses
            move(p); button(True); button(False)
            result[name+'_passes_through'] = back.presses == before+1 and not scene.drag.active
        move(Vec2(300, 200)); button(True)
        move(scene.head.position)
        result['held_button_does_not_acquire'] = not scene.drag.active
        button(False)
        focus = user32.GetForegroundWindow()
        move(scene.head.position); button(True)
        result['puppet_press_grabs'] = scene.drag.active
        result['does_not_take_focus'] = user32.GetForegroundWindow() == focus
        move(scene.head.position+Vec2(150, 170))
        result['captured_outside_shape'] = scene.drag.active
        old = scene.body.chunks[0].position
        for _ in range(60):
            scene.step()
            window.sync_drag_input()
            app.processEvents()
        result['physical_follow'] = (scene.body.chunks[0].position-old).length() > 40
        button(False)
        result['release_starts_recovery'] = not scene.drag.active and scene.drag.recovering
        window.drag_action.setChecked(False)
        QTest.qWait(40)
        before = back.presses
        move(scene.head.position); button(True); button(False)
        result['disabled_passes_through'] = back.presses == before+1
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        assert all(result.values()), result
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        window.close()
        back.close()
        app.processEvents()
        QCursor.setPos(prior_cursor)
        user32.SetForegroundWindow(prior_focus)


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    font = QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    if font >= 0:
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font)[0], 10))
    if '--native' in sys.argv:
        native(app)
    else:
        visual()
