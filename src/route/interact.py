from .accelerator import init_interact_info  # noqa: F401  (moved to accelerator)
from .gate_utils import gate_matches
def consume_interact_info(ii, s, t, PRINT_DEBUG=False):
    released = set()
    for q in (s, t):
        if q not in ii or len(ii[q]) == 0:
            continue
        front = ii[q][0]
        if gate_matches(front, s, t):
            ii[q].pop(0)
        else:
            found_idx = _find_matching_gate_index(ii[q], s, t)
            if found_idx is not None:
                ii[q].pop(found_idx)
        if len(ii[q]) == 0:
            released.add(q)
    return released
def get_still_active_qubits(ii):
    return {q for q, gates_list in ii.items() if len(gates_list) > 0}
def _find_matching_gate_index(gate_list, s, t):
    for idx, g in enumerate(gate_list):
        if gate_matches(g, s, t):
            return idx
    return None