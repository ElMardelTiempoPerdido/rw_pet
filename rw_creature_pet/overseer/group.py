"""多个槽位共享宿主时钟，各自维护事件、随机数和身体状态"""
from dataclasses import dataclass, replace
from random import Random

from ..shared.geometry import Bounds
from .events import OverseerEvents
from .model import Overseer


@dataclass
class OverseerEntry:
    slot_id: int
    model: Overseer
    events: OverseerEvents


class OverseerGroup:
    def __init__(self, config, bounds=Bounds(0, 0, 960, 600), *, seed=None):
        self.random = Random(seed)
        self.entries = {}
        self.bounds = bounds
        self.configure(config)

    @property
    def active(self):
        return any(e.model.active for e in self.entries.values())

    @property
    def available(self):
        return any(not e.model.active for e in self.entries.values())

    @property
    def revision(self):
        return tuple((key, e.model.revision) for key, e in self.entries.items())

    def configure(self, config):
        self.config = config
        wanted = {slot.id for slot in config.slots}
        for key in set(self.entries)-wanted:
            self.entries.pop(key).model.clear()
        for slot in config.slots:
            individual = replace(config, color=slot.color)
            entry = self.entries.get(slot.id)
            if entry is None:
                model = Overseer(self.bounds, individual, seed=self.random.getrandbits(64))
                model.set_appearance(slot.appearance)
                self.entries[slot.id] = OverseerEntry(slot.id, model,
                    OverseerEvents(model, seed=self.random.getrandbits(64)))
            elif entry.model.config != individual:
                if entry.model.config.size != individual.size:
                    entry.events.cancel()
                entry.events.configure(individual)
            if entry is not None:
                entry.model.set_appearance(slot.appearance)
        self.entries = dict(sorted(self.entries.items()))

    def bind(self, bounds, edges, *, reset=False):
        self.bounds = bounds
        for e in self.entries.values():
            if reset:
                e.events.clear()
            elif e.model.bounds != bounds or (e.model.active and e.model.anchor.edge not in edges):
                e.events.cancel()
            if e.model.bounds != bounds:
                e.model.place(bounds, e.model.anchor)

    def context(self, slot_id, context):
        occupied = tuple((e.model.root, e.model.reach+e.model.filament_length+12)
                         for key, e in self.entries.items() if key != slot_id and e.model.active)
        return replace(context, occupied=context.occupied+occupied)

    def start(self, context):
        for key, e in self.entries.items():
            if not e.model.active and e.events.start(self.context(key, context)):
                return True
        return False

    def step(self, target=None, *, threat=None, puppet=None, context_factory):
        context = None
        def for_slot(key):
            nonlocal context
            if context is None:
                context = context_factory()
            return self.context(key, context)
        for key, e in self.entries.items():
            if e.model.active or e.model.config.enabled:
                e.events.step(target, threat=threat, puppet=puppet,
                              context_factory=lambda key=key: for_slot(key))

    def cancel(self):
        for e in self.entries.values():
            e.events.cancel()

    def clear(self):
        for e in self.entries.values():
            e.events.clear()
