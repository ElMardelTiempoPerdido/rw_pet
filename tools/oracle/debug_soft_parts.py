"""双柔性部件调试：几何外形、PNG 和前后图层，不读取或写入本机角色调整"""
import argparse
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from rw_creature_pet.config import AppConfig
from rw_creature_pet.oracle.ui.debug_window import OracleDebugWindow
from rw_creature_pet.oracle.ui.soft_parts_debug import demo_shape


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config.toml')
    parser.add_argument('--geometry-only', action='store_true', help='不加载游戏图集和语音')
    parser.add_argument('--glow', action='store_true', help='临时开启配置中的外发光，检查附件柔光')
    args = parser.parse_args()
    config = AppConfig.load(args.config)
    if args.glow:
        config = replace(config, oracle=replace(config.oracle, glow_enabled=True))
    config = replace(config, audio=replace(config.audio, enabled=False),
        oracle=replace(config.oracle, body_appearance='custom', hide_cords=True,
            halo_enabled=False, pearl_matrix_count=0, pearl_inner_count=0, pearl_outer_count=0,
            pearl_fixed_count=0, pearl_satellite_count=0, custom_appearance=demo_shape(config.oracle.custom_appearance)))
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    window = OracleDebugWindow(config, args.config, load_atlas=not args.geometry_only)
    window.show()
    window.scale_input.setCurrentIndex(window.scale_input.findData(4.))
    window.canvas.center_on_pet()
    window.open_soft_parts_debug()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
