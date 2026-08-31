import functools
import logging
from logging.handlers import RotatingFileHandler
import networkx as nx
import numpy as np
logger = logging.getLogger(__name__)
logger.setLevel(logging.CRITICAL)
file_handler = RotatingFileHandler('router.log', maxBytes=5 * 1024 * 1024, backupCount=5, encoding='utf-8')
console_handler = logging.StreamHandler()
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(log_format)
console_handler.setFormatter(log_format)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def build_comm_topology_from_chiplets_with_channels(num_x, num_y, channels):
    """Build a comm_topology for a 2D chiplet mesh."""
    G = nx.Graph()
    for x in range(num_x):
        for y in range(num_y):
            try:
                node = (x, y)
                if x + 1 < num_x:
                    G.add_edge((x, y), (x + 1, y), cap=max(channels.get(((x, y), (x + 1, y)), 0) - 2, 0))
                    G.add_edge((x + 1, y), (x, y), cap=max(channels.get(((x + 1, y), (x, y)), 0) - 2, 0))
                if y + 1 < num_y:
                    G.add_edge((x, y), (x, y + 1), cap=max(channels.get(((x, y), (x, y + 1)), 0) - 2, 0))
                    G.add_edge((x, y + 1), (x, y), cap=max(channels.get(((x, y + 1), (x, y)), 0) - 2, 0))
            except Exception as e:
                raise f'Error building comm topology: {e}, node: {node}, channels: {channels}, used_key' from None
    return G

def build_comm_topology_from_chiplets(num_x, num_y, num_comm_qubits):
    """Build a comm_topology for a 2D chiplet mesh."""
    G = nx.Graph()
    cap = int(num_comm_qubits) - 1
    for x in range(num_x):
        for y in range(num_y):
            if x + 1 < num_x:
                G.add_edge((x, y), (x + 1, y), cap=cap)
            if y + 1 < num_y:
                G.add_edge((x, y), (x, y + 1), cap=cap)
    return G

@functools.lru_cache(maxsize=4096)
def get_manhattan_distance(src, tgt):
    if src is None or tgt is None:
        return 0
    return abs(src[0] - tgt[0]) + abs(src[1] - tgt[1])

def convert_ndarray_to_list(obj):
    if isinstance(obj, dict):
        converted = {}
        for (k, v) in obj.items():
            if isinstance(k, np.integer):
                key = int(k)
            elif isinstance(k, np.floating):
                key = float(k)
            elif isinstance(k, (str, int, float, bool)) or k is None:
                key = k
            else:
                key = str(k)
            converted[key] = convert_ndarray_to_list(v)
        return converted
    elif isinstance(obj, list):
        return [convert_ndarray_to_list(v) for v in obj]
    elif isinstance(obj, tuple):
        return [convert_ndarray_to_list(v) for v in obj]
    elif isinstance(obj, set):
        return [convert_ndarray_to_list(v) for v in sorted(obj, key=str)]
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj
import matplotlib.pyplot as plt
import json
import os
import tempfile
from pathlib import Path

def _json_default(o):
    try:
        import numpy as np
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    if isinstance(o, (set, tuple)):
        return list(o)
    if hasattr(o, '__dict__'):
        return o.__dict__
    return str(o)

def atomic_json_dump(obj, path, *, indent=2, sort_keys=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, prefix=f'.{path.name}.tmp-', suffix='.json', delete=False) as tmp:
            json.dump(obj, tmp, ensure_ascii=False, indent=indent, sort_keys=sort_keys, default=_json_default)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass