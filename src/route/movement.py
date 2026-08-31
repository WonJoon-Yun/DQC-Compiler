from .channel import assert_edge_in_connectivity, consume_path
def apply_move(qubit, path, connectivity, ch, qubit_positions,
               atom_paths, active_qubits,
               position_timeline, gate_timeline,
               position_table=None, context=""):
    hops = len(path) - 1
    if hops <= 0: return 0
    for i in range(hops):
        assert_edge_in_connectivity(connectivity, path[i], path[i + 1], context=context)
    consume_path(connectivity, path, ch, context=context)
    for node in path[1:]:
        atom_paths[qubit].append(node)
    for node in path[1:-1]:
        qubit_positions[qubit] = node
        if position_table is not None: position_table[qubit] = node
        position_timeline.append({q: qubit_positions[q] for q in sorted(active_qubits)})
        gate_timeline.append([])
    qubit_positions[qubit] = path[-1]
    if position_table is not None: position_table[qubit] = path[-1]
    return hops
def record_position_snapshot(qubit_positions, active_qubits,
                             position_timeline, gate_timeline):
    """Record a timeline snapshot with an empty gate list."""
    position_timeline.append({q: qubit_positions[q] for q in sorted(active_qubits)})
    gate_timeline.append([])