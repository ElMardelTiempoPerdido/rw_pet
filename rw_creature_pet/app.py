"""应用入口。"""
import argparse
from pathlib import Path
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .config import AppConfig
from .debug_window import DebugWindow


def main():
    parser = argparse.ArgumentParser(description="Rain World 桌宠调试场景")
    parser.add_argument('--creature', choices=('lizard', 'oracle'), default='lizard', help='调试生物，默认 lizard')
    parser.add_argument("--config", type=Path, help="TOML 配置路径；默认读取当前目录 config.toml")
    parser.add_argument('--desktop', action='store_true', help='透明穿透桌面模式，右键托盘控制')
    parser.add_argument('--scale', type=float, default=1.0, help='桌宠大小倍率，默认 1')
    parser.add_argument('--activity', choices=('floor', 'wall'), default='floor', help='蜥蜴桌面活动模式')
    args = parser.parse_args()
    path = args.config
    if path is None and Path("config.toml").is_file():
        path = Path("config.toml")
    try:
        config = AppConfig.load(path)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f"配置读取失败：{exc}")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    if args.desktop:
        from .atlas import AtlasError
        from PySide6.QtWidgets import QMessageBox
        try:
            if args.creature == 'oracle':
                from .oracle_desktop import OracleDesktopWindow
                window = OracleDesktopWindow(config, args.scale, path)
            else:
                from .desktop import DesktopWindow
                window = DesktopWindow(config, args.scale, args.activity)
        except (OSError, ValueError, RuntimeError, AtlasError) as exc:
            QMessageBox.critical(None, '桌宠启动失败', str(exc))
            return 1
    elif args.creature == 'oracle':
        from .oracle_window import OracleDebugWindow
        window = OracleDebugWindow(config, path)
    else:
        window = DebugWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
