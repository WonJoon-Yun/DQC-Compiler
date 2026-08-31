from ...channel import assert_channel_invariant, assert_edge_in_connectivity, channel_snapshot, consume_capacity, consume_path, release_recnot_channel, reserve_recnot_channel
from ...interact import consume_interact_info
from ...pathfinding import first_hop_with_capacity, nearest_neighbor_toward, relaxed_hop_with_capacity
from ...release import handle_released_qubits
from ._validation import _assert_channel_delta_for_move, _assert_path_unit_steps, _assert_unit_step

def _execute_one_meet(gate_idx, mp, mover, connectivity, channel_dict, qubit_positions, position_table, atom_paths, active_qubits, num_relocates, gate_relocates, op_log, gate_timeline, position_timeline, PRINT_DEBUG):
    meeting = mp['meeting_node']
    path = mp['path']
    dist = mp['dist']
    for i in range(len(path) - 1):
        assert_edge_in_connectivity(connectivity, path[i], path[i + 1], context=f'gate {gate_idx} one-meet@{meeting}')
    checked_hops = _assert_path_unit_steps(path, context=f'gate {gate_idx} one-meet')
    assert checked_hops == dist, f'[ASSERT ONE-MEET] gate {gate_idx}: dist={dist}, path_hops={checked_hops}'
    ch_before = channel_snapshot(channel_dict)
    if dist > 0:
        consume_path(connectivity, path, channel_dict, context=f'gate {gate_idx} q{mover}->{meeting}')
        ch_after = channel_snapshot(channel_dict)
        _assert_channel_delta_for_move(ch_before, ch_after, hops=dist, cap_consumed=True, context=f'gate {gate_idx} ONE-MEET q{mover}')
        for node in path[1:]:
            atom_paths[mover].append(node)
        for node in path[1:-1]:
            qubit_positions[mover] = node
            position_table[mover] = node
            position_timeline.append({q: qubit_positions[q] for q in sorted(active_qubits)})
            gate_timeline.append([])
        qubit_positions[mover] = meeting
        position_table[mover] = meeting
        num_relocates += dist
        gate_relocates += dist
        op_log.append({'gate_idx': gate_idx, 'op_type': 'ONE-MEET', 'qubit': mover, 'from': path[0], 'to': meeting, 'path': list(path), 'hops': dist, 'cost_model': f'meet({dist}h)', 'cap_consumed': True})
    gate_timeline.append([])
    return (num_relocates, gate_relocates)

def _record_gate_execution(s, t, gate_idx, gate_start_pos_s, gate_start_pos_t, qubit_positions, orig_positions, active_qubits, connectivity, channel_dict, position_timeline, gate_timeline, executed_gate_locations, executed_gate_types, relocates_per_gate, recnot_flags, gate_relocates, PRINT_DEBUG):
    assert qubit_positions[s] == qubit_positions[t]
    exec_pos = qubit_positions[s]
    assert exec_pos in connectivity.nodes
    position_timeline.append({q: qubit_positions[q] for q in sorted(active_qubits)})
    is_remote = qubit_positions[s] != qubit_positions[t]
    gate_type = 'Re-CNOT' if is_remote else 'Local CNOT'
    executed_gate_locations.append(((s, t), exec_pos))
    executed_gate_types.append(gate_type)
    gate_timeline.append([gate_idx])
    relocates_per_gate.append(gate_relocates)
    recnot_flags.append(is_remote)
    if is_remote and gate_start_pos_s != gate_start_pos_t and connectivity.has_edge(gate_start_pos_s, gate_start_pos_t):
        ch_before = channel_snapshot(channel_dict)
        reserve_recnot_channel(connectivity, gate_start_pos_s, gate_start_pos_t, channel_dict, context=f'gate {gate_idx} ({s},{t})')
        ch_held = channel_snapshot(channel_dict)
        _assert_channel_delta_for_move(ch_before, ch_held, hops=1, cap_consumed=True, context=f'gate {gate_idx} Re-CNOT reserve ({s},{t})')
        release_recnot_channel(gate_start_pos_s, gate_start_pos_t, channel_dict)
        ch_after = channel_snapshot(channel_dict)
        assert ch_after == ch_before, f'[ASSERT RECNOT] gate {gate_idx}: reserve+release must restore channel'
        assert_channel_invariant(channel_dict, context=f'after recnot gate {gate_idx}')

def _handle_post_gate_interact(ii, s, t, gate_idx, future_gates, qubit_positions, position_table, atom_paths, active_qubits, connectivity, channel_dict, gcache, num_relocates, gate_relocates, relocates_per_gate, all_released_qubits, op_log, gate_timeline, position_timeline, PRINT_DEBUG):
    released = consume_interact_info(ii, s, t, PRINT_DEBUG=False)
    all_released_qubits.update(released)
    if released and future_gates:
        (num_relocates, gate_relocates) = handle_released_qubits(released_qubits=released, gate_idx=gate_idx, future_gates=future_gates, qubit_positions=qubit_positions, position_table=position_table, atom_paths=atom_paths, active_qubits=active_qubits, ii=ii, connectivity=connectivity, ch=channel_dict, gcache=gcache, num_relocates=num_relocates, gate_relocates=gate_relocates, op_log=op_log, gate_timeline=gate_timeline, position_timeline=position_timeline, PRINT_DEBUG=PRINT_DEBUG)
        relocates_per_gate[-1] = gate_relocates
    assert_channel_invariant(channel_dict, context=f'after interact_info gate {gate_idx}')
    return (num_relocates, gate_relocates)