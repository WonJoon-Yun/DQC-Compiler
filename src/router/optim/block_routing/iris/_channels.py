from typing import Any, Dict, List, Optional, Set, Tuple
from ._common import DEBUG_CHECKS, VERBOSE_SEARCH, Edge, Pos, _manhattan, _tiebreak_coords
from ._state import _neighbors

def _normalize_channels_struct_only(ch: Dict[Edge, int]) -> Dict[Edge, int]:
    out: Dict[Edge, int] = {}
    for ((a, b), v) in ch.items():
        out[a, b] = int(v)
    for (a, b) in list(out.keys()):
        if (b, a) not in out:
            out[b, a] = 0
    return out

def _validate_channels_nonneg(ch: Dict[Edge, int], where: str='') -> None:
    if not DEBUG_CHECKS:
        return
    for ((a, b), v) in ch.items():
        iv = int(v)
        if iv < 0:
            raise ValueError(f'[NEG-CHAN]{where} edge={(a, b)} value={iv} \n Whole Channel Dict: {ch}')

def _diff_channels(before: Dict[Edge, int], after: Dict[Edge, int]) -> List[str]:
    if not DEBUG_CHECKS:
        return []
    lines: List[str] = []
    keys = set(before.keys()) | set(after.keys())
    for k in sorted(keys, key=lambda e: (_tiebreak_coords(e[0]), _tiebreak_coords(e[1]))):
        bv = int(before.get(k, 0))
        av = int(after.get(k, 0))
        if av != bv:
            if av < 0 or bv < 0:
                lines.append(f'{k}: {bv} -> {av} (NEGATIVE EDGE VALUE)')
            else:
                lines.append(f'{k}: {bv} -> {av} (Δ {av - bv})')
    return lines

def _cap_value(channel_dict: Dict[Edge, int], u: Pos, v: Pos) -> int:
    return int(channel_dict.get((u, v), 0))

def relaxed_hop_with_capacity(*, curr: Pos, goal: Pos, connectivity: Any, channel_dict: Dict[Edge, int], min_comm_value: int, max_comm_value: int, forbid_nodes: Optional[Set[Pos]]=None, iteration_cap: int=256, print_debug: bool=False) -> Tuple[Optional[Pos], Dict[Edge, int]]:
    ch = dict(channel_dict)
    _validate_channels_nonneg(ch, where='relaxed-hop')
    if curr == goal:
        if print_debug and VERBOSE_SEARCH:
            print(f'[RELAX] already at goal {goal} - no hop')
        return (None, ch)
    forbid_nodes = forbid_nodes or set()
    if curr in forbid_nodes:
        forbid_nodes = set(forbid_nodes)
        forbid_nodes.discard(curr)
    prev: Optional[Pos] = None
    visited_edges: Set[Edge] = set()

    def _choose_next(u: Pos) -> Optional[Pos]:
        neighs: List[Pos] = [v for v in _neighbors(connectivity, u) if v not in forbid_nodes]
        candidates: List[Pos] = [v for v in neighs if _cap_value(ch, u, v) < max_comm_value]
        if not candidates:
            return None
        du = _manhattan(u, goal)
        improving = [v for v in candidates if _manhattan(v, goal) < du]
        if prev is not None:
            improving_no_back = [v for v in improving if v != prev]
            cand_no_back = [v for v in candidates if v != prev]
        else:
            improving_no_back = improving
            cand_no_back = candidates

        def key(v: Pos):
            return (_manhattan(v, goal), _cap_value(ch, u, v))
        pool = improving_no_back or improving or cand_no_back or candidates
        pool_not_visited = [v for v in pool if (u, v) not in visited_edges]
        choice_pool = pool_not_visited or pool
        choice = min(choice_pool, key=key)
        return choice
    steps = 0
    u = curr
    while steps < iteration_cap:
        steps += 1
        v = _choose_next(u)
        if print_debug and VERBOSE_SEARCH:
            print(f'[RELAX] step={steps} curr={u} next={v} goal={goal}')
        if v is None or v == u:
            return (None, ch)
        if prev is not None and v == prev:
            visited_edges.add((u, v))
            continue
        if (u, v) in visited_edges:
            continue
        ch[u, v] = _cap_value(ch, u, v) + 1
        visited_edges.add((u, v))
        (prev, u) = (u, v)
        return (u, ch)
    if print_debug and VERBOSE_SEARCH:
        print(f'[RELAX] iteration cap hit at {iteration_cap}, giving up from curr={curr}')
    return (None, ch)