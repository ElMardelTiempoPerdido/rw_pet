"""应用入口。"""
import argparse
from dataclasses import replace
from pathlib import Path
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .config import AppConfig


def main(argv=None, *, default_desktop=False):
    parser = argparse.ArgumentParser(description="Rain World 桌宠调试场景")
    parser.add_argument('--creature', choices=('lizard', 'oracle'), default='lizard', help='调试生物，默认 lizard')
    parser.add_argument("--config", type=Path, help="本次启动使用的 TOML；Bell 桌面模式默认优先读取已保存设置")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--desktop', dest='desktop', action='store_true', help='透明穿透桌面模式，右键托盘控制')
    mode.add_argument('--debug', dest='desktop', action='store_false', help='打开独立调试窗口')
    parser.set_defaults(desktop=default_desktop)
    parser.add_argument('--scale', type=float, help='本次桌面大小倍率；Oracle 默认使用保存的设置，支持 1 / 1.5 / 2')
    parser.add_argument('--settings', action='store_true', help='启动 Bell 桌面模式前打开设置')
    parser.add_argument('--activity', choices=('floor', 'wall'), default='floor', help='蜥蜴桌面活动模式')
    args = parser.parse_args(argv)
    if args.creature == 'oracle':
        from .oracle.config import DISPLAY_SCALES
        if args.scale is not None and args.scale not in DISPLAY_SCALES:
            parser.error('Oracle 的 --scale 仅支持 1、1.5、2')
    bell_desktop = args.creature == 'oracle' and args.desktop
    bell_settings = bell_desktop or (args.creature == 'oracle' and default_desktop)
    if args.settings and not bell_desktop:
        parser.error('--settings 仅用于 Bell 桌面模式')
    path = args.config
    if not bell_settings and path is None and Path("config.toml").is_file():
        path = Path("config.toml")
    store, first_run, message = None, False, ''
    try:
        if bell_settings:
            from .settings_store import SettingsStore
            store = SettingsStore()
            config, first_run, message = store.startup(path)
            # 独立调试可沿用已保存设置，但颜色重载只接受显式 TOML。
            path = store.path if bell_desktop else args.config
            if args.scale is not None:
                config = replace(config, desktop=replace(config.desktop, scale=args.scale))
        else:
            config = AppConfig.load(path)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f"配置读取失败：{exc}")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    assets = None
    if bell_desktop:
        app.setQuitOnLastWindowClosed(False)
        from .settings_store import validate_game_directory
        from .oracle.settings import OracleSettingsDialog
        try:
            validate_game_directory(config.game_dir)
        except (OSError, ValueError) as exc:
            first_run, message = True, str(exc)
        if first_run or args.settings:
            dialog = OracleSettingsDialog(config, store, first_run=first_run, message=message)
            if app.primaryScreen() is not None:
                dialog.fit_workarea(app.primaryScreen().availableGeometry())
            if dialog.exec() != dialog.DialogCode.Accepted:
                return 0
            config, assets = dialog.saved_config, dialog.prepared_assets
    if args.desktop:
        from .shared.atlas import AtlasError
        from PySide6.QtWidgets import QMessageBox
        try:
            if args.creature == 'oracle':
                from .oracle.desktop import OracleDesktopWindow
                window = OracleDesktopWindow(config, config.desktop.scale, path, config_store=store, assets=assets)
            else:
                from .lizard.desktop import DesktopWindow
                window = DesktopWindow(config, 1. if args.scale is None else args.scale, args.activity)
        except (OSError, ValueError, RuntimeError, AtlasError) as exc:
            QMessageBox.critical(None, '桌宠启动失败', str(exc))
            return 1
    elif args.creature == 'oracle':
        from .oracle.debug_window import OracleDebugWindow
        window = OracleDebugWindow(config, path)
    else:
        from .lizard.debug_window import DebugWindow
        window = DebugWindow(config)
    window.show()
    sys.exit(app.exec())


def bell_main():
    return main(['--creature', 'oracle', *sys.argv[1:]], default_desktop=True)


if __name__ == "__main__":
    main()
