"""逻辑坐标：左上原点，x 向右、y 向下；长度为逻辑单位。"""
from dataclasses import dataclass
from math import hypot


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        return Vec2(self.x * scalar, self.y * scalar)

    def length(self) -> float:
        return hypot(self.x, self.y)

    def lerp(self, other: "Vec2", alpha: float) -> "Vec2":
        return self + (other - self) * alpha


@dataclass(frozen=True, slots=True)
class Bounds:
    left: float
    top: float
    right: float
    bottom: float

    def clamp(self, point: Vec2) -> Vec2:
        return Vec2(max(self.left, min(self.right, point.x)),
                    max(self.top, min(self.bottom, point.y)))

    def contains(self, point: Vec2, tolerance=1e-6) -> bool:
        return (self.left - tolerance <= point.x <= self.right + tolerance
                and self.top - tolerance <= point.y <= self.bottom + tolerance)
