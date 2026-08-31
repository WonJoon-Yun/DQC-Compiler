from typing import Any, Dict, List, Optional, Sequence, Tuple
from ._common import (Block, Edge, GateRow, Pos, _block_qubits, dataclass)
from ._cost import Metrics
from ._state import RoutingState
@dataclass(slots=True)
class BlockInfo:
    """Information about a block during execution."""
    num_internal_qubits: int
    num_external_qubits: int
    channel_dict: Dict[Edge, int]
@dataclass(slots=True)
class WindowPlan:
    aggs: List[Pos]
    combined_schedule: List[List[GateRow]]
    cost_recnot: int
    cost_reloc: int
    cost_cr: int
    state_after: RoutingState
    per_block_metrics: List[Metrics]
    done_ids: List[int]
    use_swap_list: List[bool]
    per_block_info: List[BlockInfo]
    @property
    def key(self):
        return (self.cost_recnot, self.cost_reloc, self.cost_cr)