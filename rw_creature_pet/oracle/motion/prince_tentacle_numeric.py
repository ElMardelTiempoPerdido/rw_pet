"""Prince 触手的原位长度约束；Python 与可选 Numba 使用同一数值内核"""
from array import array
from functools import lru_cache
from math import hypot
import os
import warnings


def solve_chain(x, y, line_x, line_y, budget, pad, width, height, iterations, free_tip=False):
    """抓附时固定两端；悬空时只固定根部，末端参与分段限长而不向直线收拢"""
    last = len(x)-1
    if free_tip:
        rest = budget/last
        right, bottom = width-pad, height-pad
        for iteration in range(iterations):
            forward = iteration % 2 == 0
            start, stop, stride = (0, last, 1) if forward else (last-1, -1, -1)
            for i in range(start, stop, stride):
                j = i+1
                dx, dy = x[j]-x[i], y[j]-y[i]
                distance = hypot(dx, dy)
                if distance <= rest:
                    continue
                factor = (distance-rest)/max(distance, 1e-9)
                cx, cy = dx*factor, dy*factor
                if i == 0:
                    x[j] -= cx
                    y[j] -= cy
                else:
                    x[i] += cx*.5
                    y[i] += cy*.5
                    x[j] -= cx*.5
                    y[j] -= cy*.5
            for i in range(1, last+1):
                x[i] = max(pad, min(right, x[i]))
                y[i] = max(pad, min(bottom, y[i]))
        # 自由端可以向内让位，最终逐段收回误差即可严格限长，无需拉直整条链
        for i in range(last):
            j = i+1
            dx, dy = x[j]-x[i], y[j]-y[i]
            distance = hypot(dx, dy)
            if distance > rest:
                factor = rest/distance
                x[j], y[j] = x[i]+dx*factor, y[i]+dy*factor
        return 0.

    root_x, root_y, tip_x, tip_y = x[0], y[0], x[last], y[last]
    dx, dy = tip_x-root_x, tip_y-root_y
    if hypot(dx, dy) >= budget-1e-6:
        for i in range(1, last):
            t = i/last
            x[i], y[i] = root_x+dx*t, root_y+dy*t
        return 0.

    rest = budget/last
    right, bottom = width-pad, height-pad
    for iteration in range(iterations):
        forward = iteration % 2 == 0
        start, stop, stride = (0, last, 1) if forward else (last-1, -1, -1)
        for i in range(start, stop, stride):
            j = i+1
            dx, dy = x[j]-x[i], y[j]-y[i]
            distance = hypot(dx, dy)
            if distance <= rest:
                continue
            factor = (distance-rest)/max(distance, 1e-9)
            cx, cy = dx*factor, dy*factor
            if i == 0:
                x[j] -= cx
                y[j] -= cy
            elif j == last:
                x[i] += cx
                y[i] += cy
            elif forward:
                x[j] -= cx
                y[j] -= cy
            else:
                x[i] += cx
                y[i] += cy
        for i in range(1, last):
            x[i] = max(pad, min(right, x[i]))
            y[i] = max(pad, min(bottom, y[i]))

    length = 0.
    for i in range(last):
        length += hypot(x[i+1]-x[i], y[i+1]-y[i])
    if length > budget:
        dx, dy = tip_x-root_x, tip_y-root_y
        for i in range(len(x)):
            t = i/last
            line_x[i], line_y[i] = root_x+dx*t, root_y+dy*t
        line_x[0], line_y[0] = root_x, root_y
        line_x[last], line_y[last] = tip_x, tip_y
        lo, hi = 0., 1.
        for _ in range(16):
            weight = (lo+hi)*.5
            length = 0.
            previous_x, previous_y = root_x, root_y
            for i in range(1, len(x)):
                px = line_x[i]+(x[i]-line_x[i])*weight
                py = line_y[i]+(y[i]-line_y[i])*weight
                length += hypot(px-previous_x, py-previous_y)
                previous_x, previous_y = px, py
            if length <= budget:
                lo = weight
            else:
                hi = weight
        for i in range(1, last):
            x[i] = line_x[i]+(x[i]-line_x[i])*lo
            y[i] = line_y[i]+(y[i]-line_y[i])*lo

    error = 0.
    for i in range(last):
        error = max(error, hypot(x[i+1]-x[i], y[i+1]-y[i])-rest)
    return error


@lru_cache(maxsize=1)
def compiled_tentacle_solver():
    # 与普通线缆一致，在创建场景时预热，移动帧内不编译；不重排浮点运算
    from numba import njit
    solver = njit(cache=True, fastmath=False)(solve_chain)
    solver(array('d', (0., 1., 2.)), array('d', (0., 2., 0.)),
           array('d', (0., 0., 0.)), array('d', (0., 0., 0.)),
           3., 0., 100., 100., 12)
    solver(array('d', (0., 1., 2.)), array('d', (0., 2., 0.)),
           array('d', (0., 0., 0.)), array('d', (0., 0., 0.)),
           3., 0., 100., 100., 12, True)
    return solver


@lru_cache(maxsize=3)
def tentacle_solver(backend='auto'):
    """沿用 physics_backend 和环境变量；自动后端不可用时回退到 Python"""
    backend = os.environ.get('RW_PET_NUMERIC_BACKEND', backend)
    if backend not in ('auto', 'python', 'numba'):
        raise ValueError('physics_backend 必须为 auto / python / numba')
    if backend == 'python':
        return solve_chain
    try:
        return compiled_tentacle_solver()
    except ImportError:
        if backend == 'numba':
            raise
    except Exception as exc:
        if backend == 'numba':
            raise
        warnings.warn(f'Prince 触手数值加速不可用，使用 Python：{exc}', RuntimeWarning, stacklevel=2)
    return solve_chain
