from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
Pos = Tuple[int, int]
Edge = Tuple[Pos, Pos]
GateRow = Dict[str, Any]
Block = List[Any]
QuCommFn = Any

@dataclass
class TimeModel:
    T_MOVE_US: float = 0.0
    T_CNOT_US: float = 0.0
    T_ReCNOT_US: float = 0.0
MICRO_UNLOCK_STEPS: int = 0

@dataclass
class RoutingState:
    position_table: Dict[int, Pos]
    channel_dict: Dict[Edge, int]
    atom_paths: Dict[int, List[Pos]]

def _manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def _cap_value(channel_dict: Dict[Edge, int], u: Pos, v: Pos) -> int:
    return int(channel_dict.get((u, v), 0))

def relaxed_hop_with_capacity(*, curr: Pos, goal: Pos, connectivity: Any, channel_dict: Dict[Edge, int], min_comm_value: int, max_comm_value: int, forbid_nodes: Optional[Set[Pos]]=None, iteration_cap: int=256, print_debug: bool=False) -> Tuple[Optional[Pos], Dict[Edge, int]]:
    raise RuntimeError('pruned dead function: relaxed_hop_with_capacity')

def _neighbors(connectivity: Any, node: Pos) -> List[Pos]:
    try:
        return list(connectivity.neighbors(node))
    except Exception:
        return []

def _normalize_channels_struct_only(ch: Dict[Edge, int]) -> Dict[Edge, int]:
    out: Dict[Edge, int] = {}
    for ((a, b), v) in ch.items():
        out[a, b] = int(v)
    for (a, b) in list(out.keys()):
        if (b, a) not in out:
            out[b, a] = 0
    return out

def _validate_channels_nonneg(ch: Dict[Edge, int], where: str='') -> None:
    """Values must be >= 0. No clamping."""
    for ((a, b), v) in ch.items():
        iv = int(v)
        if iv < 0:
            raise ValueError(f'[NEG-CHAN]{where} edge={(a, b)} value={iv}')

def _diff_channels(before: Dict[Edge, int], after: Dict[Edge, int]) -> List[str]:
    raise RuntimeError('pruned dead function: _diff_channels')

@dataclass
class Metrics:
    relocates: int
    recnots: int

@dataclass
class RecoveryConfig:
    lookahead_restore_path: Any
    get_agg_node_func: Any
    num_comm_qubits: int
    min_comm_value: int = 1
    max_comm_value: int = 8
    K_restore: int = 1
    verbose: bool = False
    restore_iter_cap: int = 1000
    use_all_qubits: bool = False

def _position_at_t_from_paths(atom_paths: Dict[int, List[Pos]], fallback_table: Dict[int, Pos]) -> Dict[int, Pos]:
    pos = {}
    for (k, v) in atom_paths.items():
        pos[k] = v[-1] if v else fallback_table[k]
    return pos