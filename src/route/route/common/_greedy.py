from ...channel import assert_edge_in_connectivity, channel_snapshot, consume_capacity, link_capacity
from ...evict import build_protected_set, try_local_evict
from ._helpers import _node_sort_key, _safe_sp_len
from ._validation import _assert_channel_delta_for_move, _assert_unit_step

def _score_greedy_neighbors(q, pq, goal_pos, partner, connectivity, channel_dict, position_table, ii, gcache):
    scored = []
    d0 = gcache.sp_len(pq, goal_pos)
    for nb in gcache.neighbors(pq):
        d1 = gcache.sp_len(nb, goal_pos)
        if d1 is None or d0 is None:
            continue
        evict_benefit = _compute_evict_benefit(nb, pq, q, partner, channel_dict, position_table, ii, gcache)
        scored.append((d1, evict_benefit, nb))
    scored.sort(key=lambda x: (x[0], x[1], _node_sort_key(x[2])))
    return (scored, d0)

def _compute_evict_benefit(nb, pq, q, partner, ch, position_table, ii, gcache):
    if link_capacity(pq, nb, ch) > 0 or ii is None:
        return 0
    evict_benefit = 0
    for (qid, pos) in position_table.items():
        if pos != nb or qid in {q, partner}:
            continue
        if qid not in ii or len(ii[qid]) == 0:
            continue
        next_gate = ii[qid][0]
        if hasattr(next_gate, 'atom0'):
            pt = next_gate.atom1 if next_gate.atom0 == qid else next_gate.atom0
        else:
            pt = next_gate[1] if next_gate[0] == qid else next_gate[0]
        pt_pos = position_table.get(pt)
        if pt_pos is None:
            continue
        d_before = gcache.sp_len(nb, pt_pos)
        d_after = gcache.sp_len(pq, pt_pos)
        if d_before is not None and d_after is not None:
            evict_benefit = min(evict_benefit, d_after - d_before)
    return evict_benefit

def _try_greedy_with_evict(gate_idx, q, pq, goal_pos, partner, future_gates, connectivity, channel_dict, position_table, qubit_positions, atom_paths, active_qubits, evict_cooldown, move_round, ii, gcache, num_relocates, gate_relocates, num_epr_release, op_log, gate_timeline, PRINT_DEBUG):
    (scored, d0) = _score_greedy_neighbors(q, pq, goal_pos, partner, connectivity, channel_dict, position_table, ii, gcache)
    if not scored:
        return None
    hop = next((nb for (d1, _eb, nb) in scored if d1 < d0), None)
    if hop is None:
        hop = scored[0][2]
    if link_capacity(pq, hop, channel_dict) <= 0:
        protected = build_protected_set(q, partner, future_gates, depth=8)
        _assert_unit_step(hop, pq, context=f'gate {gate_idx} evict-candidate')
        ch_before_evict = channel_snapshot(channel_dict)
        victim = try_local_evict(pq, hop, protected, future_gates, position_table, qubit_positions, atom_paths, active_qubits, connectivity, channel_dict, evict_cooldown, move_round, gcache, ii=ii, PRINT_DEBUG=PRINT_DEBUG)
        if victim is not None:
            ch_after_evict = channel_snapshot(channel_dict)
            _assert_channel_delta_for_move(ch_before_evict, ch_after_evict, hops=1, cap_consumed=True, context=f'gate {gate_idx} EVICT q{victim}')
            op_log.append({'gate_idx': gate_idx, 'op_type': 'EVICT', 'qubit': victim, 'from': hop, 'to': pq, 'path': [hop, pq], 'hops': 1, 'cost_model': '1h local-evict', 'cap_consumed': True})
            num_epr_release += 1
            gate_relocates += 1
    if link_capacity(pq, hop, channel_dict) <= 0:
        return None
    ch_before = channel_snapshot(channel_dict)
    _assert_unit_step(pq, hop, context=f'gate {gate_idx} greedy q{q}')
    assert_edge_in_connectivity(connectivity, pq, hop, context=f'gate {gate_idx} greedy q{q}')
    consume_capacity(connectivity, pq, hop, channel_dict, context=f'gate {gate_idx} greedy q{q} {pq}->{hop}')
    ch_after = channel_snapshot(channel_dict)
    _assert_channel_delta_for_move(ch_before, ch_after, hops=1, cap_consumed=True, context=f'gate {gate_idx} GREEDY q{q}')
    qubit_positions[q] = hop
    position_table[q] = hop
    atom_paths[q].append(hop)
    num_relocates += 1
    gate_relocates += 1
    gate_timeline.append([])
    op_log.append({'gate_idx': gate_idx, 'op_type': 'GREEDY', 'qubit': q, 'from': pq, 'to': hop, 'path': [pq, hop], 'hops': 1, 'cost_model': '1h greedy', 'cap_consumed': True})
    return {'num_relocates': num_relocates, 'gate_relocates': gate_relocates, 'num_epr_release': num_epr_release}

def _try_fallback(gate_idx, s, t, qubit_positions, dyn_agg, connectivity, channel_dict, position_table, atom_paths, gcache, num_relocates, gate_relocates, op_log, gate_timeline, PRINT_DEBUG):
    raise RuntimeError('pruned: _try_fallback')

def _try_deadlock_recovery(gate_idx, s, t, qubit_positions, dyn_agg, future_gates, connectivity, channel_dict, position_table, atom_paths, active_qubits, gcache, num_epr_release, gate_relocates, op_log, gate_timeline, position_timeline, PRINT_DEBUG):
    raise RuntimeError('pruned: _try_deadlock_recovery')

def _resolve_no_path(gate_idx, s, t, future_gates, dyn_agg, connectivity, channel_dict, position_table, qubit_positions, atom_paths, active_qubits, evict_cooldown, move_round, ii, gcache, num_relocates, gate_relocates, num_epr_release, op_log, gate_timeline, position_timeline, PRINT_DEBUG):
    (pos_s, pos_t) = (qubit_positions[s], qubit_positions[t])
    candidates_fb = [(s, pos_s, pos_t, t), (t, pos_t, pos_s, s)]
    candidates_fb.sort(key=lambda x: (_safe_sp_len(gcache, x[1], x[2]), _node_sort_key(x[2]), _node_sort_key(x[1]), x[0]))
    for (q, pq, goal_pos, partner) in candidates_fb:
        result = _try_greedy_with_evict(gate_idx, q, pq, goal_pos, partner, future_gates, connectivity, channel_dict, position_table, qubit_positions, atom_paths, active_qubits, evict_cooldown, move_round, ii, gcache, num_relocates, gate_relocates, num_epr_release, op_log, gate_timeline, PRINT_DEBUG)
        if result is not None:
            return (True, result['num_relocates'], result['gate_relocates'], result['num_epr_release'])
    result = _try_fallback(gate_idx, s, t, qubit_positions, dyn_agg, connectivity, channel_dict, position_table, atom_paths, gcache, num_relocates, gate_relocates, op_log, gate_timeline, PRINT_DEBUG)
    if result is not None:
        return (True, result['num_relocates'], result['gate_relocates'], num_epr_release)
    result = _try_deadlock_recovery(gate_idx, s, t, qubit_positions, dyn_agg, future_gates, connectivity, channel_dict, position_table, atom_paths, active_qubits, gcache, num_epr_release, gate_relocates, op_log, gate_timeline, position_timeline, PRINT_DEBUG)
    if result is not None:
        return (True, num_relocates, result['gate_relocates'], result['num_epr_release'])
    return (False, num_relocates, gate_relocates, num_epr_release)