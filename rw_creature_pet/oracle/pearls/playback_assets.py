"""读取随包分发的珍珠动画强度曲线，不访问游戏音乐或用户缓存"""
from hashlib import sha256
import io
import json

import numpy as np

from ...shared.paths import PACKAGE_ROOT
from .playback import SpectrumCurve

CURVE_ROOT = PACKAGE_ROOT/'oracle/pearls/data/playback'
FORMAT_VERSION = 1


def load_pearl_playback():
    manifest = json.loads((CURVE_ROOT/'manifest.json').read_text(encoding='utf-8'))
    raw = (CURVE_ROOT/'strength.npy').read_bytes()
    if manifest['format_version'] != FORMAT_VERSION:
        raise ValueError('不支持的内置珍珠动画数据版本')
    if sha256(raw).hexdigest() != manifest['sha256']:
        raise ValueError('内置珍珠动画数据校验失败')
    values = np.load(io.BytesIO(raw), allow_pickle=False)
    if (values.ndim != 1 or values.dtype != np.dtype('<f4')
            or len(values) != manifest['samples']):
        raise ValueError('无效的内置珍珠动画强度数组')
    curve = SpectrumCurve(tuple(map(float, values)), manifest['duration'], manifest['curve_rate'])
    return curve, CURVE_ROOT


def prepare_pearl_playback(renderer):
    """包内数据损坏时保留普通阅读，错误通过现有资源状态显示"""
    try:
        renderer.playback_curve, _ = load_pearl_playback()
        return ''
    except Exception as exc:
        renderer.playback_curve = None
        return f'珍珠播放动画不可用：{exc}'
