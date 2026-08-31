from ...constants import INF
from ._constants import ( CANDIDATE_EVAL_MODE_ACTIVE_CHIPS, CANDIDATE_EVAL_MODE_ALL, CANDIDATE_EVAL_MODES)
def _node_chip_key(node, gcache):
    chip = gcache.chip_of(node)
    return node if chip is None else chip
def _candidate_nodes_from_active_chips(active_qubits, qubit_positions,
                                       connectivity, gcache):
    """Restrict search to chips that currently host block qubits."""
    active_chip_keys = set()
    _chip_of = gcache.chip_of               # avoid repeated attr lookup
    for q in active_qubits:
        pos = qubit_positions.get(q)
        if pos is not None:
            c = _chip_of(pos)
            active_chip_keys.add(pos if c is None else c)
    if not active_chip_keys:
        return sorted(connectivity.nodes)
    nodes = [node for node in connectivity.nodes if (_chip_of(node) or node) in active_chip_keys]
    if not nodes:
        return sorted(connectivity.nodes)
    return sorted(nodes)
def _candidate_nodes_for_mode(active_qubits, qubit_positions, connectivity,
                              gcache, candidate_eval_mode):
    return _candidate_nodes_from_active_chips(
        active_qubits, qubit_positions, connectivity, gcache)
def _coord_l1_distance(a, b):
    if (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == 2 and len(b) == 2):
        try:
            return abs(a[0] - b[0]) + abs(a[1] - b[1])
        except Exception:
            return None
    return None
def _node_sort_key(node):
    return str(node)
def _safe_sp_len(gcache, u, v):
    d = gcache.sp_len(u, v)
    return d if d is not None else INF
def _gate_progress_state_key(active_qubits, qubit_positions, channel_dict):
    pos_key = tuple((q, qubit_positions[q]) for q in sorted(active_qubits) if q in qubit_positions)
    ch_key = tuple(sorted(channel_dict.items()))
    return pos_key, ch_key
def _channel_abs_delta(before, after):
    keys = set(before.keys()) | set(after.keys())
    return sum(abs(after.get(k, 0) - before.get(k, 0)) for k in keys)
def _simulate_channel_after_path(ch, path):
    ch_after = dict(ch)
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        ch_after[(u, v)] = ch_after.get((u, v), 0) + 1
        ch_after[(v, u)] = ch_after.get((v, u), 0) - 1
    return ch_after
def _predicted_one_meet_state_key(mp, active_qubits, qubit_positions, channel_dict):
    pos_sim = {q: qubit_positions[q] for q in active_qubits if q in qubit_positions }
    pos_sim[mp['move_qubit']] = mp['meeting_node']
    ch_sim = _simulate_channel_after_path(channel_dict, mp['path'])
    return _gate_progress_state_key(active_qubits, pos_sim, ch_sim)