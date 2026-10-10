"""资源默认位置；不导入应用配置或生物模块。"""
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GAME_DIR = Path(r"D:\steam\steamapps\common\Rain World")
