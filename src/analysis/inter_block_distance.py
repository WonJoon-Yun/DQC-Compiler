from collections import defaultdict
def _extract_distinct_qubits(gate):
    for a_name, b_name in (("atom0", "atom1"), ("q0", "q1"), ("src", "dst")):
        if hasattr(gate, a_name) or hasattr(gate, b_name):
            qubits = {
                int(qubit)
                for qubit in (getattr(gate, a_name, None), getattr(gate, b_name, None))
                if qubit is not None}
            return tuple(sorted(qubits)) if len(qubits) >= 2 else ()
    if isinstance(gate, (tuple, list)) and len(gate) >= 2:
        qubits = {int(gate[0]), int(gate[1])}
        return tuple(sorted(qubits)) if len(qubits) >= 2 else ()
    for attr in ("atoms", "qubits"):
        if hasattr(gate, attr):
            try:
                qubits = {int(qubit) for qubit in getattr(gate, attr)}
            except Exception:
                return ()
            return tuple(sorted(qubits)) if len(qubits) >= 2 else ()
    return ()
def compute_execution_layers_from_dag(dag):
    if dag is None or len(dag.nodes) == 0:
        return {}
    work = dag.copy(as_view=False); remaining = set(work.nodes()); layers = {}; level = 0
    while remaining:
        roots = sorted(node for node in remaining if work.in_degree(node) == 0)
        if not roots:
            raise ValueError("Block DAG must be acyclic to compute execution layers")
        for node in roots:
            layers[node] = level
        work.remove_nodes_from(roots)
        remaining.difference_update(roots)
        level += 1
    return layers
def compute_inter_block_distance_metric(blocks, execution_layers=None):
    if not blocks:
        return 0.0, 0, 0
    execution_layers = execution_layers or {}
    qubit_to_touches = defaultdict(list)
    for block_idx, block in enumerate(blocks):
        layer = int(execution_layers.get(block_idx, block_idx))
        block_qubits = set()
        for gate in block:
            block_qubits.update(_extract_distinct_qubits(gate))
        for qubit in block_qubits:
            qubit_to_touches[qubit].append((layer, block_idx))
    all_distances = []
    for touches in qubit_to_touches.values():
        touches.sort()
        for (prev_layer, _), (next_layer, _) in zip(touches, touches[1:]):
            all_distances.append(next_layer - prev_layer)
    if not all_distances:
        return 0.0, 0, 0
    return (sum(all_distances) / len(all_distances), max(all_distances), min(all_distances))