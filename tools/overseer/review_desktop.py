"""桌面监视者回放/性能计数；--native-click 在自建按钮上验证真实 Windows 穿透。"""
import os
import sys
from pathlib import Path
from dataclasses import replace
import json
from time import perf_counter, process_time
from unittest.mock import patch

NATIVE = '--native-click' in sys.argv
if not NATIVE:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
else:
    os.environ.pop('QT_QPA_PLATFORM', None)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from rw_creature_pet.config import AppConfig
from rw_creature_pet.shared.atlas import Atlas, extract_atlas
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer
from rw_creature_pet.overseer.model import Anchor, Edge

OUT = ROOT/'artifacts/overseer'


def settle(window):
    window.timer.stop()
    window.motion.scene.set_autonomous(False)
    for _ in range(850):
        window.motion.step()
    assert window.motion.scene.appearance.sleeping
    window.advance()
    QApplication.processEvents()


def show_watcher(window):
    layer = window.overseer_layer
    layer.events.preview(layer.model.bounds, Anchor(Edge.BOTTOM, .8))
    for _ in range(65):
        layer.model.step()
    layer.refresh(1.)
    QApplication.processEvents()


def profile(config, atlas):
    result = {}
    with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
        window = OracleDesktopWindow(config, renderer=OracleRenderer(atlas, config.oracle.colors))
    try:
        settle(window)
        layer, scene = window.overseer_layer, window.motion.scene
        counts = {}
        def trace(obj, attr, label):
            original = getattr(obj, attr)
            def counted(*args, **kwargs):
                counts[label] = counts.get(label, 0)+1
                return original(*args, **kwargs)
            setattr(obj, attr, counted)
        for obj, attr, label in ((window, 'update', 'puppet_update'), (window.renderer, 'draw', 'puppet_draw'),
                                 (scene.appearance, 'step_cloth', 'cloth_step'),
                                 (scene.appearance.cords, 'step', 'cord_step'),
                                 (layer, 'update', 'overseer_update'), (layer.renderer, 'draw', 'overseer_draw'),
                                 (layer, 'mouse_world', 'cursor_poll')):
            trace(obj, attr, label)
        for mode in ('disabled', 'waiting', 'watching'):
            layer.events.clear()
            layer.events.configure(replace(layer.model.config, enabled=mode != 'disabled', check_interval=30))
            if mode == 'watching':
                show_watcher(window)
            window.clock.accumulator = 0.
            window._next_render_time = 0.
            origin = perf_counter()
            window.last_time = origin
            counts.clear()
            revision = scene.appearance.revision
            cpu, start = process_time(), perf_counter()
            for tick in range(400):
                with patch('rw_creature_pet.oracle.desktop.perf_counter', return_value=origin+(tick+1)/40):
                    window.advance()
                QApplication.processEvents()
            cpu_seconds, elapsed = process_time()-cpu, perf_counter()-start
            assert scene.appearance.revision == revision and scene.appearance.sleeping
            assert counts.get('puppet_draw', 0) == counts.get('puppet_update', 0) == 0, counts
            assert counts.get('cloth_step', 0) == counts.get('cord_step', 0) == 0, counts
            result[mode] = dict(simulated_seconds=10, cpu_seconds=cpu_seconds,
                cpu_ms_per_simulated_second=cpu_seconds*100, wall_seconds=elapsed, calls=dict(counts),
                overseer_window_dip=list(layer.geometry().getRect()) if layer.isVisible() else None)
        layer.grab().save(str(OUT/'desktop-layer.png'))
        result['scope'] = 'Qt offscreen 40 Hz simulation / 30 Hz paint replay; excludes native compositor and is not Task Manager CPU percentage'
        return result
    finally:
        window.close()


def native_click(config, atlas):
    import ctypes as C
    from ctypes import wintypes as W
    u = C.windll.user32
    u.GetWindowLongPtrW.argtypes, u.GetWindowLongPtrW.restype = [W.HWND, C.c_int], C.c_ssize_t
    u.GetForegroundWindow.restype = W.HWND
    u.SetForegroundWindow.argtypes = [W.HWND]
    u.WindowFromPoint.argtypes, u.WindowFromPoint.restype = [W.POINT], W.HWND
    u.GetAncestor.argtypes, u.GetAncestor.restype = [W.HWND, W.UINT], W.HWND
    u.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    u.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
    u.mouse_event.argtypes = [W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
    old_focus, old_cursor = u.GetForegroundWindow(), W.POINT()
    u.GetCursorPos(C.byref(old_cursor))
    background = QWidget()
    background.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    button = QPushButton('监视者穿透测试', background)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    window = None
    try:
        window = OracleDesktopWindow(config, renderer=OracleRenderer(atlas, config.oracle.colors))
        settle(window)
        show_watcher(window)
        layer = window.overseer_layer
        background.setGeometry(layer.geometry())
        button.setGeometry(background.rect())
        background.show()
        background.activateWindow()
        QTest.qWait(100)
        focus = u.GetForegroundWindow()
        window.raise_()
        layer.raise_()
        QTest.qWait(120)
        assert u.GetForegroundWindow() == focus, '显示层抢占焦点'
        ex = u.GetWindowLongPtrW(int(layer.winId()), -20)
        assert ex & 0x20 and ex & 0x80000 and ex & 0x8000000 and ex & 0x8, hex(ex)
        capture = layer.grab().toImage()
        pixels = [(x, y) for y in range(capture.height()) for x in range(capture.width())
                  if capture.pixelColor(x, y).alpha() > 180]
        assert pixels, '必须检查监视者可见像素'
        x, y = pixels[len(pixels)//2]
        client = W.RECT()
        u.GetClientRect(int(layer.winId()), C.byref(client))
        point = W.POINT(round(x*client.right/capture.width()), round(y*client.bottom/capture.height()))
        u.ClientToScreen(int(layer.winId()), C.byref(point))
        for enabled in (False, True):
            window.set_drag_enabled(enabled)
            window.repaint()
            layer.raise_()
            QTest.qWait(80)
            assert u.GetAncestor(u.WindowFromPoint(point), 2) == int(background.winId()), '监视者拦截系统命中'
            u.SetCursorPos(point.x, point.y)
            u.mouse_event(0x0002, 0, 0, 0, 0)
            u.mouse_event(0x0004, 0, 0, 0, 0)
            QTest.qWait(100)
        assert len(clicks) == 2, clicks
        capture.save(str(OUT/'desktop-native-alpha.png'))
        return dict(platform=QApplication.platformName(), button_clicks=len(clicks),
                    drag_disabled_and_enabled_click_through=True, no_focus_steal=True,
                    native_ex_style=hex(ex), layer_rect=list(layer.geometry().getRect()))
    finally:
        if window is not None:
            window.close()
        background.close()
        u.SetCursorPos(old_cursor.x, old_cursor.y)
        u.SetForegroundWindow(old_focus)


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    config = AppConfig.load(ROOT/'config.toml')
    config = replace(config, oracle=replace(config.oracle, halo_enabled=False, pearl_matrix_enabled=False,
                     pearl_orbits_enabled=False, pearl_fixed_count=1, pearl_satellite_count=0),
                     desktop=replace(config.desktop, autonomous=False), overseer=replace(config.overseer, enabled=False),
                     audio=replace(config.audio, enabled=False))
    atlas = Atlas(extract_atlas(config.game_dir))
    OUT.mkdir(parents=True, exist_ok=True)
    result = native_click(config, atlas) if NATIVE else profile(config, atlas)
    path = OUT/('desktop-native.json' if NATIVE else 'desktop-performance.json')
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
