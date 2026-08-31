from collections import defaultdict
from ...channel import assert_channel_invariant
from ._validation import _assert_op_log_consistency, _strict_validate_block_physics, _validate_atom_paths

def _finalize_timeline(qubit_positions, active_qubits, position_timeline, gate_timeline):
    if len(position_timeline) == len(gate_timeline):
        position_timeline.append({q: qubit_positions[q] for q in sorted(active_qubits)})
        gate_timeline.append([])

def _sync_active_positions(position_table, qubit_positions, active_qubits):
    for q in active_qubits:
        position_table[q] = qubit_positions[q]

def _build_detailed_rows(gates, position_timeline, gate_timeline, block_id):
    detailed_rows = []
    qubit_paths = defaultdict(list)
    qubit_gates = defaultdict(list)
    for t_idx in range(len(position_timeline) - 1):
        pos = position_timeline[t_idx]
        nextpos = position_timeline[t_idx + 1]
        exec_gate_indices = {item for item in gate_timeline[t_idx] if isinstance(item, int)}
        for (gi, (s_, t_)) in enumerate(gates):
            if t_ not in qubit_gates[s_]:
                qubit_gates[s_].append(t_)
            if s_ not in qubit_gates[t_]:
                qubit_gates[t_].append(s_)
            if not qubit_paths[s_] or qubit_paths[s_][-1] != pos[s_]:
                qubit_paths[s_].append(pos[s_])
            if not qubit_paths[t_] or qubit_paths[t_][-1] != pos[t_]:
                qubit_paths[t_].append(pos[t_])
            detailed_rows.append({'BlockID': block_id, 'Time': t_idx, 'SIdx': s_, 'SPos': pos[s_], 'SNextPos': nextpos[s_], 'TIdx': t_, 'TPos': pos[t_], 'TNextPos': nextpos[t_], 'CNOT': gi in exec_gate_indices})
    return (detailed_rows, qubit_paths, qubit_gates)

def _compute_stats(detailed_rows, qubit_paths, qubit_gates, recnot_flags):
    try:
        (num_relocate_cnot_ops, _) = count_moving_ops(qubit_paths, qubit_gates)
    except NameError:
        num_relocate_cnot_ops = sum((max(len(p) - 1, 0) for p in qubit_paths.values()))
    re_cnot_ops = {(r['SIdx'], r['TIdx']) for r in detailed_rows if r['CNOT'] and r['SPos'] != r['TPos']}
    num_recnot_ops = len({op[0] for op in re_cnot_ops})
    num_recnots = sum((1 for f in recnot_flags if f))
    return (num_relocate_cnot_ops, num_recnot_ops, num_recnots)

def _build_output(algo_name, gates, active_qubits, qubit_positions, position_timeline, gate_timeline, block_id, recnot_flags, relocates_per_gate, num_relocates, num_epr_release, num_return_relocates, atom_paths, channel_dict, op_log, ii, interact_info, all_released_qubits, connectivity, initial_position_table, final_position_table, initial_channel_dict, initial_atom_paths, final_atom_paths, PRINT_DEBUG):
    _finalize_timeline(qubit_positions, active_qubits, position_timeline, gate_timeline)
    (detailed_rows, qubit_paths, qubit_gates) = _build_detailed_rows(gates, position_timeline, gate_timeline, block_id)
    (num_relocate_cnot_ops, num_recnot_ops, num_recnots) = _compute_stats(detailed_rows, qubit_paths, qubit_gates, recnot_flags)
    assert_channel_invariant(channel_dict, context='FINAL')
    _assert_op_log_consistency(op_log)
    _strict_validate_block_physics(algo_name=algo_name, gates=gates, position_timeline=position_timeline, gate_timeline=gate_timeline, op_log=op_log, connectivity=connectivity, initial_position_table=initial_position_table, final_position_table=final_position_table, initial_channel_dict=initial_channel_dict, final_channel_dict=channel_dict, initial_atom_paths=initial_atom_paths, final_atom_paths=final_atom_paths)
    return (detailed_rows, atom_paths, channel_dict, num_relocates, num_recnots, num_epr_release, ii if ii is not None else interact_info)