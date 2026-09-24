"""Oracle 桌面验收。默认离屏回放；--native-click 用受控按钮验证 Windows 穿透。"""
import os
import sys
from pathlib import Path
import json
import hashlib
from time import perf_counter, process_time

NATIVE = '--native-click' in sys.argv
if not NATIVE:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
else:
    os.environ.pop('QT_QPA_PLATFORM', None)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
(ROOT/'artifacts').mkdir(exist_ok=True)

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from PIL import Image

from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.geometry import Vec2
from rw_creature_pet.oracle.desktop import OracleDesktopMotion, OracleDesktopViewport, OracleDesktopWindow, current_anchor
from rw_creature_pet.oracle.glyphs import load_pearl_glyphs
from rw_creature_pet.oracle.render import OracleRenderer


def replay(config, renderer):
    cases = [(1920, 1040, 1.), (1280, 680, 1.5), (800, 560, 2.), (1080, 1920, 1.)]
    result, poses = [], []
    for side in ('top', 'right', 'bottom', 'left'):
        from dataclasses import replace
        scene = None
        for width, height, dpr in cases:
            viewport = OracleDesktopViewport(-width, 40, width, height, dpr)
            motion = OracleDesktopMotion(replace(config.oracle, base_side=side), viewport, scene)
            scene = motion.scene
            for _ in range(40):
                motion.step()
            assert scene.navigator.region.contains(scene.body.chunks[0].position)
            assert scene.arm.constraint_error < .2
            assert all(scene.arm_region.segment_safe(a.position, b.position)
                       for a, b in zip(scene.arm.joints, scene.arm.joints[1:]))
            result.append(dict(side=side, logical_size=[width, height], dpr=dpr,
                world_size=[scene.world.width, scene.world.height],
                physical_scale=viewport.physical_scale, constraint_error=scene.arm.constraint_error))
        # 收敛后保留全景，展示竖屏上的四种支撑位置及透明底图。
        scene.set_autonomous(False)
        for _ in range(650):
            motion.step()
        image = QImage(1080, 1920, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.draw(painter, scene)
        painter.end()
        image.save(str(ROOT/f'artifacts/oracle-desktop-{side}-alpha.png'))
        # 3× 局部图只用于检视，不改变场景尺度。
        close = QImage(540, 420, QImage.Format.Format_RGBA8888)
        close.fill(QColor('#17232e'))
        p = QPainter(close)
        p.setFont(QFont('Microsoft YaHei UI', 10))
        p.setPen(QColor('#dbe6ec'))
        p.drawText(16, 26, f'{side} · 工作区改变后 · 3× 局部')
        p.translate(270, 160)
        p.scale(3, 3)
        center = scene.body.chunks[0].position
        p.translate(-center.x, -center.y)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.draw(p, scene)
        p.end()
        poses.append(Image.frombytes('RGBA', (540, 420), bytes(close.constBits())).convert('RGB'))
    sheet = Image.new('RGB', (1080, 840))
    for i, pose in enumerate(poses):
        sheet.paste(pose, ((i % 2)*540, (i//2)*420))
    sheet.save(ROOT/'artifacts/oracle-desktop-reflow.png')
    return result


def native_click(app, config):
    """只点击本脚本创建的测试按钮，结束时恢复鼠标与原前台窗口。"""
    import ctypes as C
    from ctypes import wintypes as W
    assert os.name == 'nt'
    u = C.WinDLL('user32', use_last_error=True)
    u.GetForegroundWindow.restype = W.HWND
    u.SetForegroundWindow.argtypes = [W.HWND]
    u.GetWindowLongPtrW.argtypes, u.GetWindowLongPtrW.restype = [W.HWND, C.c_int], C.c_ssize_t
    u.WindowFromPoint.argtypes, u.WindowFromPoint.restype = [W.POINT], W.HWND
    u.GetAncestor.argtypes, u.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
    u.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
    u.SetCursorPos.argtypes = [C.c_int, C.c_int]
    u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
    u.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
    previous_focus = u.GetForegroundWindow()
    old_cursor = W.POINT()
    u.GetCursorPos(C.byref(old_cursor))
    background = QWidget()
    background.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    background.resize(160, 96)
    button = QPushButton('穿透点击测试', background)
    button.setGeometry(0, 0, 160, 96)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    background.show()
    background.activateWindow()
    QTest.qWait(100)
    focus_before = u.GetForegroundWindow()
    window = None
    try:
        window = OracleDesktopWindow(config)
        window.timer.stop()
        window.set_paused(True)
        w = window.motion.viewport
        center = w.to_global(window.motion.scene.body.chunks[0].position+Vec2(0, 10))
        background.move(round(center.x-80), round(center.y-48))
        window.raise_()  # 只改变堆叠顺序；桌宠窗口仍具有 NOACTIVATE。
        QTest.qWait(150)
        overlay = int(window.winId())
        ex = u.GetWindowLongPtrW(overlay, -20)
        assert ex & 0x20 and ex & 0x80000 and ex & 0x8000000 and ex & 0x8
        focus_unchanged = u.GetForegroundWindow() == focus_before
        assert focus_unchanged, '桌宠显示后抢占了前台焦点'
        client = W.RECT()
        target = int(button.winId())
        u.GetClientRect(target, C.byref(client))
        point = W.POINT(client.right//2, client.bottom//2)
        u.ClientToScreen(target, C.byref(point))
        under = u.WindowFromPoint(point)
        assert u.GetAncestor(under, 2) == int(background.winId()), '人偶可见像素拦截了系统命中'
        capture = window.grab().toImage()
        px = round((center.x-window.x())*window.devicePixelRatioF())
        py = round((center.y-window.y())*window.devicePixelRatioF())
        assert capture.pixelColor(px, py).alpha() > 0, '测试点必须位于可见的人偶像素'
        capture.save(str(ROOT/'artifacts/oracle-desktop-native-alpha.png'))
        u.SetCursorPos(point.x, point.y)
        u.mouse_event(0x0002, 0, 0, 0, 0)
        u.mouse_event(0x0004, 0, 0, 0, 0)
        QTest.qWait(120)
        assert len(clicks) == 1, '下层按钮未收到点击'
        result = dict(platform=app.platformName(), available_rect=list(window.geometry().getRect()),
            screen_dpr=window.screen.devicePixelRatio(), actual_physical_scale=w.physical_scale,
            native_ex_style=hex(ex), no_focus_steal=focus_unchanged,
            visible_pixel_click_through=True, button_clicks=len(clicks))
        # 关闭测试按钮后用真实桌面窗口跑短时自主行为；不再移动用户鼠标。
        u.SetCursorPos(old_cursor.x, old_cursor.y)
        background.close()
        u.SetForegroundWindow(previous_focus)
        window.set_paused(False)
        window.last_time = perf_counter()
        window.timer.start(16)
        start, cpu = perf_counter(), process_time()
        QTimer.singleShot(6000, app.quit)
        app.exec()
        result['runtime'] = dict(elapsed_seconds=perf_counter()-start, cpu_seconds=process_time()-cpu,
            ticks=window.motion.scene.ticks, dropped_seconds=window.clock.dropped_seconds,
            tray_hidden_after_exit=not window.tray.isVisible(), timer_stopped_after_exit=not window.timer.isActive())
        assert not window.timer.isActive() and not window.tray.isVisible()
        return result
    finally:
        if window is not None:
            window.close()
        background.close()
        u.SetCursorPos(old_cursor.x, old_cursor.y)
        u.SetForegroundWindow(previous_focus)


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    config = AppConfig.load(ROOT/'config.toml')
    path = ROOT/'artifacts/oracle-desktop-metrics.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    before = hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    if NATIVE:
        data['native_windows'] = native_click(app, config)
    else:
        atlas = Atlas(extract_atlas(config.game_dir))
        renderer = OracleRenderer(atlas, config.oracle.colors,
                                   glyphs=load_pearl_glyphs(config.game_dir, atlas.root))
        data['reflow'] = replay(config, renderer)
    data['config_unchanged'] = before == hashlib.sha256((ROOT/'config.toml').read_bytes()).hexdigest()
    data['config_sha256'] = before
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
