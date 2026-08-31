"""Performance caches and cached shortest-path functions."""
from typing import Dict, Optional, Tuple
import networkx as nx
from ._types import Pos
_NEIGHBOR_CACHE: Optional[Dict[Pos, Tuple[Pos, ...]]] = None
def clear_performance_caches():
    global _NEIGHBOR_CACHE
    _NEIGHBOR_CACHE = None
def _build_neighbor_cache(connectivity: nx.Graph) -> Dict[Pos, Tuple[Pos, ...]]:
    """Build cache of neighbors for all nodes in the graph."""
    return {n: tuple(connectivity.neighbors(n)) for n in connectivity.nodes()}
def _neighbors(connectivity: nx.Graph, pos: Pos):
    """Get neighbors of a position, using cache if available."""
    global _NEIGHBOR_CACHE
    if _NEIGHBOR_CACHE is None:
        _NEIGHBOR_CACHE = _build_neighbor_cache(connectivity)
    return _NEIGHBOR_CACHE.get(pos, ())
