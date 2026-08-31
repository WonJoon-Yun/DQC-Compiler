from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
class Gate:
    def __init__(self, layer_idx, atom0, atom1, pos0, pos1,
                 dependency=None, is_done=False):
        self.layer_idx = layer_idx
        self.atom0 = atom0
        self.atom1 = atom1
        self.is_shuffled = False
        self._pos0 = pos0
        self._pos1 = pos1
        self._dependency = dependency if dependency is not None else []
        self._is_done = is_done
        self.unique_id = uuid4().hex
    @property
    def pos0(self):
        return self._pos0 if not self.is_shuffled else self._pos1
    @property
    def pos1(self):
        return self._pos1 if not self.is_shuffled else self._pos0
    @pos0.setter
    def pos0(self, value):
        self._pos0 = value
    @pos1.setter
    def pos1(self, value):
        self._pos1 = value
    @property
    def is_ccop(self):
        return self.pos0 != self.pos1
    @property
    def dependency(self):
        return list(set(self._dependency))
    @dependency.setter
    def dependency(self, value):
        self._dependency = value
    @property
    def is_done(self):
        return self._is_done
    @is_done.setter
    def is_done(self, value):
        self._is_done = value
    def done(self):
        if self.is_done: return
        can_be_done = all(dep.is_done for dep in self.dependency)
        if can_be_done: self.is_done = True
    def __str__(self):
        return (f"Gate(layer_idx={self.layer_idx}, "
                f"atom0={self.atom0}, atom1={self.atom1})")
    def __repr__(self):
        return self.__str__()
    def __eq__(self, other):
        return id(self) == id(other)
    def __hash__(self):
        return id(self)
class Executable(Gate):
    def __init__(self, unique_id, layer_idx, atom0, atom1,
                 pos0, pos1, operation,
                 dependency=None, duration=0, is_done=False,
                 start_time=0, end_time=0):
        super().__init__(layer_idx, atom0, atom1, pos0, pos1,
                         dependency, is_done)
        self.unique_id = unique_id
        self.operation = operation
        self.duration = duration
        self.start_time = start_time
        self.remaining_time = duration
        self.end_time = end_time
    def __eq__(self, other):
        if not isinstance(other, Executable): return False
        return self.unique_id == other.unique_id
    def __hash__(self):
        return hash(self.unique_id)
@dataclass
class RoutingState:
    position_table: Dict[Any, Any]
    channel_dict: Dict[Any, int]
    atom_paths: Dict[Any, List]
@dataclass
class PerBlockInfo:
    num_external_qubits: int
    num_internal_qubits: int
    channel_dict: Dict[Any, int]
@dataclass
class PerBlockMetrics:
    relocates: int
    recnots: int
    releases: int
@dataclass
class Plan:
    done_ids: List[int] = field(default_factory=list)
    aggs: List[Tuple] = field(default_factory=list)
    state_after: Optional[RoutingState] = None
    cost_reloc: int = 0
    cost_recnot: int = 0
    cost_cr: int = 0          # channel releases
    routing_cost: float = 0.0  # weighted cost (RELOC=1, Re-CNOT=1.77, release=1)
    combined_schedule: List[list] = field(default_factory=list)
    per_block_info: List[PerBlockInfo] = field(default_factory=list)
    per_block_metrics: List[PerBlockMetrics] = field(default_factory=list)
    use_swap_list: List = field(default_factory=list)
    interact_info: Optional[dict] = None
    lookahead_debug: List[Dict[str, Any]] = field(default_factory=list)