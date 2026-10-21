"""Prince 触手外观草案：固定配置、平滑中心线和按弧长定位的囊肿，不推进物理"""
from bisect import bisect_right
from dataclasses import dataclass
from math import ceil, isfinite
from pathlib import Path
from functools import lru_cache
import re
import tomllib

from ..shared.geometry import Vec2


DEFAULT_CONFIG = Path(__file__).resolve().parents[1]/'skin/prince/tentacles.toml'


@lru_cache(maxsize=1)
def default_study():
    """运行时与调试脚本共用一份随包发布的轮廓，场景步进不读取文件"""
    return load_study(DEFAULT_CONFIG)


def number(value, name, low=-4096., high=4096.):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} 必须是数值')
    value = float(value)
    if not isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} 必须在 {low:g}～{high:g} 之间')
    return value


def color(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError(f'{name} 必须是 #RRGGBB 颜色')
    return value


def vector(value, name):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f'{name} 必须是 [x, y]')
    return Vec2(*(number(v, f'{name}[{i}]') for i, v in enumerate(value)))


def fields(data, allowed, name):
    if not isinstance(data, dict):
        raise ValueError(f'{name} 必须是配置表')
    unknown = set(data)-set(allowed.split())
    if unknown:
        raise ValueError(f'{name} 包含未知字段：{", ".join(sorted(unknown))}')


def enabled(data, name):
    value = data.get('enabled', True)
    if not isinstance(value, bool):
        raise ValueError(f'{name}.enabled 必须是 true 或 false')
    return value


def stops(value, name, parse_value):
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError(f'{name} 至少需要两项：[0, 值] 和 [1, 值]')
    result = []
    for i, item in enumerate(value):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f'{name}[{i}] 必须是 [位置, 值]')
        t = number(item[0], f'{name}[{i}].位置', 0., 1.)
        result.append((t, parse_value(item[1], f'{name}[{i}].值')))
    if result[0][0] != 0 or result[-1][0] != 1:
        raise ValueError(f'{name} 必须从 0 开始、到 1 结束')
    if any(a[0] >= b[0] for a, b in zip(result, result[1:])):
        raise ValueError(f'{name} 的位置必须严格递增')
    return tuple(result)


def stop_interval(stations, s):
    index = max(0, min(len(stations)-2, bisect_right([v[0] for v in stations], s)-1))
    a, b = stations[index:index+2]
    return a[1], b[1], max(0., min(1., (s-a[0])/(b[0]-a[0])))


@dataclass(frozen=True)
class Bump:
    s: float
    offset: float
    width: float
    height: float
    angle: float = 0.
    color: str | None = None
    enabled: bool = True

    @classmethod
    def parse(cls, data, name):
        fields(data, 's offset width height angle color enabled', name)
        width = number(data.get('width', 4.), f'{name}.width', .1, 128.)
        return cls(
            number(data.get('s', 1.), f'{name}.s', 0., 1.),
            number(data.get('offset', 0.), f'{name}.offset'),
            width, number(data.get('height', width), f'{name}.height', .1, 128.),
            number(data.get('angle', 0.), f'{name}.angle', -360., 360.),
            color(data['color'], f'{name}.color') if 'color' in data else None,
            enabled(data, name))


@dataclass(frozen=True)
class Tentacle:
    name: str
    points: tuple[Vec2, ...]
    widths: tuple
    colors: tuple
    bumps: tuple[Bump, ...]
    cores: tuple[Bump, ...]
    core_color: str
    smoothness: float
    enabled: bool

    def width_at(self, s):
        a, b, t = stop_interval(self.widths, s)
        return a+(b-a)*t

    @classmethod
    def parse(cls, data, index):
        name = f'tentacles[{index}]'
        fields(data, 'name points widths colors bumps cores core_color smoothness enabled', name)
        title = data.get('name', str(index+1))
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f'{name}.name 必须是非空文字')
        points = data.get('points', [])
        if not isinstance(points, list) or not 2 <= len(points) <= 128:
            raise ValueError(f'{name}.points 需要 2～128 个点')
        points = tuple(vector(p, f'{name}.points[{i}]') for i, p in enumerate(points))
        if any((b-a).length() < .001 for a, b in zip(points, points[1:])):
            raise ValueError(f'{name}.points 相邻点不能重合')
        layers = []
        for key in ('bumps', 'cores'):
            values = data.get(key, [])
            if not isinstance(values, list) or len(values) > 256:
                raise ValueError(f'{name}.{key} 必须是最多 256 项的列表')
            layers.append(tuple(Bump.parse(v, f'{name}.{key}[{i}]') for i, v in enumerate(values)))
        return cls(title, points,
                   stops(data.get('widths', [[0, 3], [1, 2]]), f'{name}.widths',
                         lambda v, n: number(v, n, .1, 64.)),
                   stops(data.get('colors', [[0, '#08050F'], [1, '#34256A']]),
                         f'{name}.colors', color),
                   *layers, color(data.get('core_color', '#7149FF'), f'{name}.core_color'),
                   number(data.get('smoothness', 1.), f'{name}.smoothness', 0., 1.),
                   enabled(data, name))


@dataclass(frozen=True)
class TentacleStudy:
    tentacles: tuple[Tentacle, ...]
    preview: dict


def load_study(path):
    with Path(path).open('rb') as stream:
        data = tomllib.load(stream)
    fields(data, 'version preview tentacles', '配置')
    if type(data.get('version')) is not int or data['version'] != 1:
        raise ValueError('version 必须为 1')
    values = data.get('tentacles', [])
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError('tentacles 需要 1～16 条触手')
    tentacles = tuple(Tentacle.parse(v, i) for i, v in enumerate(values))
    if len({v.name for v in tentacles}) != len(tentacles):
        raise ValueError('触手 name 不能重复')
    preview = data.get('preview', {})
    if not isinstance(preview, dict):
        raise ValueError('preview 必须是配置表')
    return TentacleStudy(tentacles, preview)


@dataclass(frozen=True)
class TubePath:
    points: tuple[Vec2, ...]
    distances: tuple[float, ...]

    @property
    def length(self):
        return self.distances[-1]

    def sample(self, s):
        """按实际弧长采样；增加控制点不会改变囊肿的归一化位置含义"""
        distance = max(0., min(1., s))*self.length
        i = max(0, min(len(self.points)-2, bisect_right(self.distances, distance)-1))
        a, b = self.points[i:i+2]
        length = self.distances[i+1]-self.distances[i]
        return a.lerp(b, (distance-self.distances[i])/length), (b-a)*(1./length)

    def attachment(self, bump):
        center, tangent = self.sample(bump.s)
        # 正偏移位于前进方向的右手侧（屏幕坐标 y 向下）
        normal = Vec2(-tangent.y, tangent.x)
        return center+normal*bump.offset, tangent


def make_path(tentacle):
    """三次 Hermite 插值经过用户指定的全部点；短线段细分用于弧长与渐变"""
    controls = tentacle.points
    samples = [controls[0]]
    distances = [0.]
    for i, (a, b) in enumerate(zip(controls, controls[1:])):
        before = controls[max(0, i-1)]
        after = controls[min(len(controls)-1, i+2)]
        m0 = (b-before)*(.5*tentacle.smoothness)
        m1 = (after-a)*(.5*tentacle.smoothness)
        count = max(8, ceil(((b-a).length()+m0.length()+m1.length())*2))
        for j in range(1, count+1):
            t = j/count
            p = (a*(2*t**3-3*t*t+1)+m0*(t**3-2*t*t+t)
                 +b*(-2*t**3+3*t*t)+m1*(t**3-t*t))
            span = (p-samples[-1]).length()
            if span > 1e-8:
                distances.append(distances[-1]+span)
                samples.append(p)
    return TubePath(tuple(samples), tuple(distances))
