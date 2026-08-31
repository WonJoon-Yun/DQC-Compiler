from typing import Any, Dict, List, Optional, Tuple
from ._common import (Edge, Pos, _edge_key, _mix64, _pos_key, dataclass)
@dataclass(slots=True)
class RoutingState:
    position_table: Dict[int, Pos]
    channel_dict: Dict[Edge, int]
    atom_paths: Dict[int, List[Pos]]
    state_hash: int = 0  # updated after transitions
_NEIGHBOR_CACHE: Optional[Dict[Pos, Tuple[Pos, ...]]] = None
_POSITION_TABLE_CACHE: Dict[int, Dict[int, Pos]] = {}
def clear_performance_caches():
    global _NEIGHBOR_CACHE
    _NEIGHBOR_CACHE = None
    _POSITION_TABLE_CACHE.clear()
def _build_neighbor_cache(connectivity: Any) -> Dict[Pos, Tuple[Pos, ...]]:
    cache: Dict[Pos, Tuple[Pos, ...]] = {}
    try:
        nodes = list(connectivity.nodes())
        for n in nodes:
            cache[n] = tuple(connectivity.neighbors(n))
    except Exception:
        cache = {}
    return cache
def _neighbors(connectivity: Any, node: Pos) -> List[Pos]:
    global _NEIGHBOR_CACHE
    if _NEIGHBOR_CACHE is None: _NEIGHBOR_CACHE = _build_neighbor_cache(connectivity)
    return list(_NEIGHBOR_CACHE.get(node, ()))
def _position_at_t_from_paths(atom_paths: Dict[int, List[Pos]], fallback_table: Dict[int, Pos], state_hash: Optional[int] = None) -> Dict[int, Pos]:
    if state_hash is not None and state_hash in _POSITION_TABLE_CACHE:
        return _POSITION_TABLE_CACHE[state_hash]
    pos: Dict[int, Pos] = {}
    for k, v in atom_paths.items():
        pos[k] = (v[-1] if v else fallback_table[k])
    if state_hash is not None: _POSITION_TABLE_CACHE[state_hash] = pos
    return pos
def _recompute_state_hash(st: RoutingState) -> None:
    h = 0
    for q, p in st.position_table.items():
        h ^= _mix64(int(q)) ^ _mix64(_pos_key(p))
    for e, cap in st.channel_dict.items():
        if cap: h ^= _mix64(_edge_key(e)) ^ _mix64(int(cap))
    st.state_hash = h & 0xFFFFFFFFFFFFFFFF