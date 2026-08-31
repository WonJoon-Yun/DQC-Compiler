import weakref
import networkx as nx
_cache_registry = {}
def _remove_from_registry(key, _ref):
    _cache_registry.pop(key, None)
def clear_graph_cache():
    _cache_registry.clear()
class GraphCache:
    """Cached accessors for graph topology queries."""
    def __new__(cls, connectivity):
        key = id(connectivity)
        if key in _cache_registry:
            cached = _cache_registry[key]
            if cached is not None:
                return cached
            del _cache_registry[key]
        instance = super().__new__(cls)
        _cache_registry[key] = instance
        try:
            weakref.finalize(connectivity, _remove_from_registry, key, None)
        except TypeError:
            pass
        return instance
    def __init__(self, connectivity):
        if hasattr(self, '_initialized'):
            return
        self.connectivity = connectivity
        self._sp_len = {}
        self._neighbors = {}
        self._chip = {}
        self._coords = {}
        self._paths = {}
        self._initialized = True
    def sp_len(self, a, b):
        if a == b:
            return 0
        key = (a, b)
        if key not in self._sp_len:
            try:
                self._sp_len[key] = nx.shortest_path_length(self.connectivity, a, b)
            except nx.NetworkXNoPath:
                self._sp_len[key] = None
        return self._sp_len[key]
    def neighbors(self, pos):
        if pos not in self._neighbors:
            self._neighbors[pos] = sorted(self.connectivity.neighbors(pos))
        return self._neighbors[pos]
    def chip_of(self, pos):
        if pos not in self._chip:
            try:
                self._chip[pos] = self.connectivity.nodes[pos].get('chip', None)
            except Exception:
                self._chip[pos] = None
        return self._chip[pos]
    def node_coords(self, pos):
        if pos not in self._coords:
            self._coords[pos] = self._extract_coords(pos)
        return self._coords[pos]
    def _extract_coords(self, pos):
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            return (float(pos[0]), float(pos[1]))
        data = self.connectivity.nodes[pos]
        if 'pos' in data:
            p = data['pos']
            return (float(p[0]), float(p[1]))
        if 'x' in data and 'y' in data:
            return (float(data['x']), float(data['y']))
        return (float(pos), 0.0)