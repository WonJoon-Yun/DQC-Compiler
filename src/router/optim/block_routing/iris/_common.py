IMBALANCE_LIMIT = 10000
try:
    import inspect as _dc_inspect
    from dataclasses import dataclass as _dc_dataclass
    _DC_HAS_SLOTS = 'slots' in _dc_inspect.signature(_dc_dataclass).parameters
    def dataclass(*args, **kwargs):
        if not _DC_HAS_SLOTS: kwargs.pop('slots', None)
        return _dc_dataclass(*args, **kwargs)
except Exception:
    from dataclasses import dataclass
import functools
from typing import Any, Dict, List, Set, Tuple
try:
    import networkx as nx  # noqa: F401
except Exception:
    nx = None  # type: ignore
Pos = Tuple[int, int]
Edge = Tuple[Pos, Pos]
GateRow = Dict[str, Any]   # detailed_rows item from QuCommRouting
Block = List[Any]          # items have .atom0/.atom1
QuCommFn = Any             # Signature of QuCommRouting
DEBUG_CHECKS: bool = False
VERBOSE_SEARCH: bool = False
@dataclass(slots=True)
class TimeModel:
    T_MOVE_US: float = 0.0
    T_CNOT_US: float = 0.0
    T_ReCNOT_US: float = 0.0
MICRO_UNLOCK_STEPS: int = 0
def _mix64(x: int) -> int:
    x &= 0xFFFFFFFFFFFFFFFF
    x = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    x ^= (x >> 30)
    x = (x * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    x ^= (x >> 27)
    x = (x * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    x ^= (x >> 31)
    return x
def _pos_key(p: Pos) -> int:
    return ((int(p[0]) & 0xFFFFFFFF) << 32) | (int(p[1]) & 0xFFFFFFFF)
def _edge_key(e: Edge) -> int:
    (x1, y1), (x2, y2) = e
    return ((int(x1) & 0xFFFF) << 48) | ((int(y1) & 0xFFFF) << 32) | ((int(x2) & 0xFFFF) << 16) | (int(y2) & 0xFFFF)
@functools.lru_cache(maxsize=1024)
def _tiebreak_coords(p: Pos) -> Tuple[int, int]:
    try:
        return (int(p[0]), int(p[1]))
    except Exception:
        return (0, 0)
@functools.lru_cache(maxsize=4096)
def _manhattan(a: Pos, b: Pos) -> int:
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))
def _block_qubits(block: Block) -> Set[int]:
    return {int(g.atom0) for g in block} | {int(g.atom1) for g in block}