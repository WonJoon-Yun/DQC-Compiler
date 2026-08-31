from .channel import link_capacity
from .constants import INF
try:
    from .accelerator import _cy_capacity_neighbors, _cy_find_path, _cy_sssp
    _USE_CYTHON_BFS = True
except ImportError:
    _USE_CYTHON_BFS = False
def _capacity_neighbors_py(u, ch, _topo_nbs=None):
    """Pure-Python fallback."""
    if _topo_nbs is not None: return [nb for nb in _topo_nbs if ch.get((nb, u), 0) >= 2]
    nbs = []
    for (a, b), _val in ch.items():
        if a != u: continue
        if ch.get((b, a), 0) >= 2: nbs.append(b)
    nbs.sort()
    return nbs
def single_source_shortest_paths_with_capacity(src, ch, max_depth=None,
                                               gcache=None):
    if _USE_CYTHON_BFS: return _cy_sssp(src, ch, max_depth, gcache)
    paths = {src: [src]}; queue = [src]; head = 0
    while head < len(queue):
        u = queue[head]
        head += 1
        depth = len(paths[u]) - 1
        if max_depth is not None and depth >= max_depth: continue
        _topo = gcache.neighbors(u) if gcache is not None else None
        for v in _capacity_neighbors_py(u, ch, _topo_nbs=_topo):
            if v in paths: continue
            paths[v] = paths[u] + [v]
            queue.append(v)
    return paths
def find_path_with_capacity(src, dst, ch, gcache=None):
    if _USE_CYTHON_BFS: return _cy_find_path(src, dst, ch, gcache)
    if src == dst: return [src]
    paths = single_source_shortest_paths_with_capacity(src, ch, gcache=gcache)
    return paths.get(dst)
def path_cost(path):
    if path is None: return INF
    return max(len(path) - 1, 0)
def first_hop_with_capacity(curr, goal, gcache, ch):
    d0 = gcache.sp_len(curr, goal)
    if d0 is None or d0 == 0: return None
    best, best_d = None, INF
    for nb in gcache.neighbors(curr):
        if link_capacity(curr, nb, ch) <= 0: continue
        d1 = gcache.sp_len(nb, goal)
        if d1 is not None and d1 < d0 and d1 < best_d: best, best_d = nb, d1
    return best
def relaxed_hop_with_capacity(curr, goal, gcache, ch):
    d0 = gcache.sp_len(curr, goal)
    if d0 is None: return None
    best, best_d = None, INF
    for nb in gcache.neighbors(curr):
        if link_capacity(curr, nb, ch) <= 0: continue
        d1 = gcache.sp_len(nb, goal)
        if d1 is not None and d1 <= d0 and d1 < best_d: best, best_d = nb, d1
    return best
def nearest_neighbor_toward(curr, goal, gcache):
    """Find the closest neighbor to goal (ignoring capacity)."""
    best_nb, best_d = None, INF
    for nb in gcache.neighbors(curr):
        d = gcache.sp_len(nb, goal)
        if d is not None and d < best_d: best_nb, best_d = nb, d
    return best_nb