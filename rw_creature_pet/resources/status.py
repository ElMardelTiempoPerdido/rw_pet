"""加载结果的只读快照，不把素材缺失写回用户偏好"""
from dataclasses import dataclass, field
from .catalog import Availability, load_catalog


@dataclass(frozen=True)
class ResourceStatus:
    state: Availability
    detail: str = ''


@dataclass
class ResourceReport:
    items: dict[str, ResourceStatus] = field(default_factory=dict)

    @property
    def states(self):
        return {key: value.state for key, value in self.items.items()}

    def record(self, key, *, error='', available=True):
        state = Availability.UNAVAILABLE if error or not available else Availability.AVAILABLE
        self.items[key] = ResourceStatus(state, str(error))

    def missing_for(self, binding, catalog=None):
        catalog = catalog or load_catalog()
        return tuple(dict.fromkeys(resource for feature in binding.features
            for resource in catalog.features[feature].resources
            if self.states.get(resource) == Availability.UNAVAILABLE))
