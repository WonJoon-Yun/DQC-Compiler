from .channel import channel_snapshot, print_channel_delta
from .lookahead import lookahead_cost
from .movement import apply_move, record_position_snapshot
from .pathfinding import find_path_with_capacity, path_cost, single_source_shortest_paths_with_capacity
from .simulation import sim_channel_valid, simulate_consume_path

def evaluate_teleport_options(s, t, pos_s, pos_t, qubit_positions, active_qubits, future_gates, ch, gcache):
    options = []
    path_t2s = find_path_with_capacity(pos_t, pos_s, ch, gcache=gcache)
    path_s2t = find_path_with_capacity(pos_s, pos_t, ch, gcache=gcache)
    _add_direct_option(options, path_t2s, t, pos_s, 'A', qubit_positions, future_gates, gcache)
    _add_direct_option(options, path_s2t, s, pos_t, 'B', qubit_positions, future_gates, gcache)
    if path_t2s is None:
        _add_displacement_options(options, s, t, pos_s, pos_t, 'D', qubit_positions, active_qubits, future_gates, ch, gcache)
    if path_s2t is None:
        _add_displacement_options(options, t, s, pos_t, pos_s, 'E', qubit_positions, active_qubits, future_gates, ch, gcache)
    options.sort(key=lambda x: (x[0], x[1], str(x[2])))
    return options

def _add_direct_option(options, path, move_qubit, dest, label, qubit_positions, future_gates, gcache):
    if path is None or path_cost(path) <= 0:
        return
    pos_sim = dict(qubit_positions)
    pos_sim[move_qubit] = dest
    c = path_cost(path) + lookahead_cost(pos_sim, future_gates, gcache)
    options.append((c, label, {'path': path}))

def _add_displacement_options(options, stay_q, move_q, stay_pos, move_pos, label, qubit_positions, active_qubits, future_gates, ch, gcache):
    qubits_at = [q for q in active_qubits if qubit_positions[q] == stay_pos and q != stay_q]
    if not qubits_at:
        return
    reachable = single_source_shortest_paths_with_capacity(stay_pos, ch, gcache=gcache)
    if stay_pos not in reachable:
        return
    for q_d in qubits_at:
        for dest in sorted(reachable.keys()):
            displace_path = reachable[dest]
            if dest == stay_pos:
                continue
            result = _simulate_displacement(displace_path, move_pos, stay_pos, ch)
            if result is None:
                continue
            main_path = result
            pos_sim = dict(qubit_positions)
            pos_sim[move_q] = stay_pos
            pos_sim[q_d] = dest
            c = path_cost(displace_path) + path_cost(main_path) + lookahead_cost(pos_sim, future_gates, gcache)
            options.append((c, label, {'q_d': q_d, 'displace_path': list(displace_path), 'main_path': list(main_path), 'dest': dest}))

def _simulate_displacement(displace_path, move_src, move_dst, ch):
    ch_sim = dict(ch)
    simulate_consume_path(displace_path, ch_sim)
    if not sim_channel_valid(ch_sim):
        return None
    main_path = find_path_with_capacity(move_src, move_dst, ch_sim)
    if main_path is None:
        return None
    ch_sim2 = dict(ch_sim)
    simulate_consume_path(main_path, ch_sim2)
    if not sim_channel_valid(ch_sim2):
        return None
    return main_path

def execute_teleport(label, info, s, t, pos_s, pos_t, gate_idx, connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, gcache, PRINT_DEBUG=False):
    """Execute chosen teleport option. Returns total hops consumed."""
    if label == 'A':
        return _execute_direct(info['path'], t, pos_t, pos_s, gate_idx, 'OPT-A', connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, PRINT_DEBUG)
    if label == 'B':
        return _execute_direct(info['path'], s, pos_s, pos_t, gate_idx, 'OPT-B', connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, PRINT_DEBUG)
    if label == 'D':
        return _execute_displacement(info, t, pos_t, pos_s, gate_idx, 'D', connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, PRINT_DEBUG)
    if label == 'E':
        return _execute_displacement(info, s, pos_s, pos_t, gate_idx, 'E', connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, PRINT_DEBUG)
    return 0

def _execute_direct(path, qubit, src, dst, gate_idx, op_type, connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, PRINT_DEBUG):
    hops = apply_move(qubit, path, connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, context=f'gate {gate_idx} {op_type}')
    gate_timeline.append([])
    op_log.append({'gate_idx': gate_idx, 'op_type': op_type, 'qubit': qubit, 'from': src, 'to': dst, 'path': list(path), 'hops': hops, 'cost_model': f'1×{hops} (move only)', 'cap_consumed': True})
    return hops

def _execute_displacement(info, main_qubit, main_src, main_dst, gate_idx, variant, connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, PRINT_DEBUG):
    q_d = info['q_d']
    displace_path = info['displace_path']
    dest = info['dest']
    total_hops = 0
    op_prefix = f'OPT-{variant}'
    hops_d = apply_move(q_d, displace_path, connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, context=f'gate {gate_idx} {op_prefix} displace q{q_d}')
    if len(displace_path) > 1:
        record_position_snapshot(qubit_positions, active_qubits, position_timeline, gate_timeline)
    total_hops += hops_d
    op_log.append({'gate_idx': gate_idx, 'op_type': f'{op_prefix}-displace', 'qubit': q_d, 'from': displace_path[0], 'to': dest, 'path': list(displace_path), 'hops': hops_d, 'cost_model': f'displace q{q_d}: {hops_d} hops', 'cap_consumed': True})
    main_path = find_path_with_capacity(main_src, main_dst, ch)
    hops_m = apply_move(main_qubit, main_path, connectivity, ch, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, context=f'gate {gate_idx} {op_prefix} main q{main_qubit}→{main_dst}')
    gate_timeline.append([])
    total_hops += hops_m
    op_log.append({'gate_idx': gate_idx, 'op_type': f'{op_prefix}-main', 'qubit': main_qubit, 'from': main_src, 'to': main_dst, 'path': list(main_path), 'hops': hops_m, 'cost_model': f'teleport after displace: {hops_m} hops', 'cap_consumed': True})
    return total_hops