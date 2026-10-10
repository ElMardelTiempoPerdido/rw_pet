"""可选 CPU 数值内核；同一求解顺序用于 Python 和 Numba 后端。"""
from array import array
from functools import lru_cache
from math import hypot
import os
import warnings


def solve_rope(x, y, weights, rest, pins, pin_x, pin_y, long_i, long_j,
               prefix, minimum, maximum, tolerance):
    n = len(x)
    for k in range(len(pins)):
        i = pins[k]
        x[i], y[i] = pin_x[k], pin_y[k]
    for i in range(len(rest)):
        prefix[i+1] = prefix[i]+rest[i]
    for iteration in range(maximum):
        for k in range(len(long_i)):
            i, j = long_i[k], long_j[k]
            length = prefix[j]-prefix[i]
            dx, dy = x[j]-x[i], y[j]-y[i]
            d2, w = dx*dx+dy*dy, weights[i]+weights[j]
            if d2 > length*length and w:
                d = d2**.5
                f = (d-length)/(d*w)
                x[i] += dx*f*weights[i]; y[i] += dy*f*weights[i]
                x[j] -= dx*f*weights[j]; y[j] -= dy*f*weights[j]
        start, stop, stride = (0, n-1, 1) if iteration % 2 == 0 else (n-2, -1, -1)
        for i in range(start, stop, stride):
            j = i+1
            dx, dy = x[j]-x[i], y[j]-y[i]
            d = hypot(dx, dy)
            w = weights[i]+weights[j]
            if d < 1e-9 or not w:
                continue
            f = (d-rest[i])/(d*w)
            x[i] += dx*f*weights[i]; y[i] += dy*f*weights[i]
            x[j] -= dx*f*weights[j]; y[j] -= dy*f*weights[j]
        for k in range(len(pins)):
            i = pins[k]
            x[i], y[i] = pin_x[k], pin_y[k]
        count = iteration+1
        if count >= minimum and count % 2 == 0:
            converged = True
            for i in range(len(rest)):
                if not abs(hypot(x[i+1]-x[i], y[i+1]-y[i])-rest[i]) <= tolerance:
                    converged = False
                    break
            if converged:
                return count
    return maximum


@lru_cache(maxsize=1)
def compiled_rope_solver():
    # 在创建场景时编译 / 读取缓存，不把首次编译放进移动帧。
    # 不启用 fastmath 或 parallel，保留相邻约束的读写顺序。
    from numba import njit
    solver = njit(cache=True, fastmath=False)(solve_rope)
    solver(array('d', (0., 1., 2.)), array('d', (0., 0., 0.)),
           array('d', (0., 1., 0.)), array('d', (1., 1.)),
           array('q', (0, 2)), array('d', (0., 2.)), array('d', (0., 0.)),
           array('q'), array('q'), array('d', (0., 0., 0.)), 2, 10, .3)
    return solver


@lru_cache(maxsize=3)
def rope_solver(backend='auto'):
    """auto 缺少依赖 / 编译失败时回退；显式 numba 则报告错误。"""
    backend = os.environ.get('RW_PET_NUMERIC_BACKEND', backend)
    if backend not in ('auto', 'python', 'numba'):
        raise ValueError('physics_backend 必须为 auto / python / numba')
    if backend == 'python':
        return solve_rope
    try:
        return compiled_rope_solver()
    except ImportError:
        if backend == 'numba':
            raise
    except Exception as exc:
        if backend == 'numba':
            raise
        warnings.warn(f'Oracle 数值加速不可用，使用 Python：{exc}', RuntimeWarning, stacklevel=2)
    return solve_rope
