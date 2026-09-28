"""故障注入：省略松键/失去捕获事件，检查无按键的移动能否结束抓取。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.desktop import OracleDesktopWindow
from rw_creature_pet.oracle.render import OracleRenderer


def main():
    app = QApplication([])
    config = AppConfig()
    config = replace(config, interaction=replace(config.interaction, drag_enabled=True),
                     oracle=replace(config.oracle,
                         drag_reactions=replace(config.oracle.drag_reactions, voice_probability=1.)))
    with patch('rw_creature_pet.oracle.desktop.QSystemTrayIcon.isSystemTrayAvailable', return_value=True):
        window = OracleDesktopWindow(config, renderer=OracleRenderer())
    window.timer.stop()
    try:
        window.sync_drag_input()
        inp, scene = window.drag_input, window.motion.scene
        point = window.motion.viewport.to_global(scene.head.position)
        local, global_ = QPointF(point.x-inp.x(), point.y-inp.y()), QPointF(point.x, point.y)
        inp.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, local, global_,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        assert scene.drag.active
        # 这是受控故障条件，不代表已观察到 Windows 在朋友设备上丢弃了这些事件。
        inp.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, local, global_,
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        report = dict(condition='press, omit release and UngrabMouse, then move reporting NoButton',
                      drag_after_buttonless_move=scene.drag.active,
                      captured_after_buttonless_move=inp._captured)
        for _ in range(480):
            scene.step()
        report['requests_in_following_12_seconds'] = scene.drag_reactions.voice.request_count
        inp.cancel()
        count = scene.drag_reactions.voice.request_count
        for _ in range(240):
            scene.step()
        report['requests_after_cancel'] = scene.drag_reactions.voice.request_count-count
        output = Path(__file__).resolve().parents[2]/'artifacts/audio-missing-release.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        window.cleanup()


if __name__ == '__main__':
    main()
