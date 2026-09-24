"""固定在世界坐标中的背景抓点；查询顺序和模拟时间不影响点的位置。"""
from math import floor

from ..shared.geometry import Vec2


CELL_SIZE = 8.0


def _mix(value):
    value &= 0xFFFFFFFF
    value = ((value ^ (value >> 16)) * 0x7FEB352D) & 0xFFFFFFFF
    value = ((value ^ (value >> 15)) * 0x846CA68B) & 0xFFFFFFFF
    return value ^ (value >> 16)


def spatial_candidates(hip: Vec2, reach: float):
    """每格一个略有偏移的固定点，只生成腿长范围附近的格子。

    桌面没有原版 Room 的砖块/横杆地形，以稀疏空间采样提供落脚差异；
    这不是生物 ID 随机数，也不向运动过程注入逐帧噪声。
    """
    if reach <= 0:
        return
    for y in range(floor((hip.y-reach)/CELL_SIZE), floor((hip.y+reach)/CELL_SIZE)+1):
        for x in range(floor((hip.x-reach)/CELL_SIZE), floor((hip.x+reach)/CELL_SIZE)+1):
            seed = _mix(x*0x9E3779B1 ^ y*0x85EBCA77)
            point = Vec2((x + .15 + .7*(seed & 0xFFFF)/65535)*CELL_SIZE,
                         (y + .15 + .7*(_mix(seed ^ 0xA341316C) & 0xFFFF)/65535)*CELL_SIZE)
            if (point-hip).length() <= reach:
                yield point
