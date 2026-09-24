"""基础蜥蜴身体数据与平地物理。

参考 rw_src/Lizard.cs 构造函数、LizardBreeds.cs WhiteLizard 分支。
速度沿用原版约定：逻辑单位 / tick，不是每秒。
"""
from dataclasses import dataclass
from enum import Enum

from .geometry import Vec2


@dataclass(slots=True)
class BodyChunk:
    position: Vec2
    previous_position: Vec2
    radius: float
    mass: float
    velocity: Vec2 = Vec2()
    grounded: bool = False


class ConnectionKind(Enum):
    NORMAL = "Normal"
    PUSH = "Push"


@dataclass(frozen=True, slots=True)
class BodyConnection:
    first: int
    second: int
    distance: float
    kind: ConnectionKind
    elasticity: float
    weight_symmetry: float = 0.5


@dataclass(frozen=True, slots=True)
class LizardBreed:
    key: str
    body_mass: float
    body_size: float
    body_radius_factor: float
    body_length_factor: float
    body_stiffness: float


WHITE_LIZARD = LizardBreed("WhiteLizard", 2.1, 1.0, 1.0, 1.0, 0.15)


@dataclass(slots=True)
class LizardBody:
    breed: LizardBreed
    chunks: list[BodyChunk]
    connections: tuple[BodyConnection, ...]

    def step(self, world, **physics_options):
        # 引用局限在入口，物理模块不依赖具体品种。
        from .physics import step_body
        step_body(self, world, **physics_options)

    def connection_error(self, connection: BodyConnection) -> float:
        length = (self.chunks[connection.second].position - self.chunks[connection.first].position).length()
        if connection.kind == ConnectionKind.PUSH:
            return max(0.0, connection.distance - length)
        return abs(length - connection.distance)

    @classmethod
    def preview(cls, center: Vec2, breed: LizardBreed = WHITE_LIZARD) -> "LizardBody":
        """水平展开的调试初始姿态；不代表原版出生姿态或特定 ID。"""
        distance = 17.0 * breed.body_length_factor * (breed.body_size + 1.0) / 2.0
        radius = 8.0 * breed.body_size * breed.body_radius_factor
        chunks = []
        for offset in (distance, 0.0, -distance):
            position = center + Vec2(offset, 0.0)
            chunks.append(BodyChunk(position, position, radius, breed.body_mass / 3.0))
        return cls(breed, chunks, (
            BodyConnection(0, 1, distance, ConnectionKind.NORMAL, 0.95),
            BodyConnection(1, 2, distance, ConnectionKind.NORMAL, 0.95),
            BodyConnection(0, 2, distance * (1.0 + breed.body_stiffness),
                           ConnectionKind.PUSH, 0.1 + 0.4 * breed.body_stiffness),
        ))
