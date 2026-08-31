from collections import defaultdict
from ...channel import assert_channel_invariant, assert_edge_in_connectivity, channel_snapshot
from ._constants import STRICT_PHYSICS_VALIDATION
from ._helpers import _channel_abs_delta, _coord_l1_distance

def _validate_inputs(active_qubits, qubit_positions, aggregation_node, gates, connectivity, channel_dict, gcache):
    assert aggregation_node in connectivity.nodes
    for q in active_qubits:
        assert qubit_positions[q] in connectivity.nodes
    for (s, t) in gates:
        assert gcache.sp_len(qubit_positions[s], qubit_positions[t]) is not None
    for q in active_qubits:
        assert gcache.sp_len(qubit_positions[q], aggregation_node) is not None
    assert_channel_invariant(channel_dict, context='initial')
    for (u, v) in channel_dict:
        assert connectivity.has_node(u) and connectivity.has_node(v)

def _validate_atom_paths(active_qubits, atom_paths, connectivity):
    for q in active_qubits:
        path = atom_paths[q]
        for i in range(len(path) - 1):
            (u, v) = (path[i], path[i + 1])
            if u != v:
                assert connectivity.has_edge(u, v)

def _assert_unit_step(u, v, context=''):
    d = _coord_l1_distance(u, v)
    if d is not None:
        assert d == 1, f'[ASSERT MOVE DIST] {context}: non-unit move {u}->{v}, d={d}'

def _assert_path_unit_steps(path, context=''):
    assert isinstance(path, (list, tuple)) and len(path) >= 1, f'[ASSERT PATH] {context}: invalid path={path}'
    hops = len(path) - 1
    for i in range(hops):
        (u, v) = (path[i], path[i + 1])
        assert u != v, f'[ASSERT PATH] {context}: zero-length hop at index {i} ({u}->{v})'
        _assert_unit_step(u, v, context=f'{context} hop#{i}')
    return hops

def _assert_channel_delta_for_move(before, after, hops, cap_consumed, context=''):
    assert hops >= 0, f'[ASSERT HOPS] {context}: hops must be >=0, got {hops}'
    if hops == 0:
        assert before == after, f'[ASSERT CHANNEL] {context}: hops=0 but channel changed'
        return
    if cap_consumed:
        abs_delta = _channel_abs_delta(before, after)
        assert abs_delta == 2 * hops, f'[ASSERT CHANNEL] {context}: expected abs_delta={2 * hops}, got {abs_delta}, hops={hops}'
    else:
        assert before == after, f'[ASSERT CHANNEL] {context}: cap_consumed=False but channel changed'

def _assert_op_log_consistency(op_log):
    total_hops = 0
    cap_hops = 0
    no_cap_hops = 0
    for (i, op) in enumerate(op_log):
        path = op.get('path', [])
        assert isinstance(path, (list, tuple)) and len(path) >= 1, f'[ASSERT OPLOG] op#{i} invalid path: {path}'
        hops = int(op.get('hops', 0))
        assert hops == max(len(path) - 1, 0), f'[ASSERT OPLOG] op#{i} hops mismatch: hops={hops}, path_len={len(path)}'
        assert op.get('from') == path[0], f"[ASSERT OPLOG] op#{i} from mismatch: {op.get('from')} vs {path[0]}"
        assert op.get('to') == path[-1], f"[ASSERT OPLOG] op#{i} to mismatch: {op.get('to')} vs {path[-1]}"
        _assert_path_unit_steps(path, context=f"op#{i}:{op.get('op_type', 'UNKNOWN')}")
        total_hops += hops
        if op.get('cap_consumed', False):
            cap_hops += hops
        else:
            no_cap_hops += hops
    return (total_hops, cap_hops, no_cap_hops)

def _strict_validate_gate_timeline(algo_name, gates, position_timeline, gate_timeline):
    assert len(position_timeline) == len(gate_timeline), f'[ASSERT STRICT TIMELINE] {algo_name}: len(position_timeline)={len(position_timeline)} != len(gate_timeline)={len(gate_timeline)}'
    executed_counts = [0] * len(gates)
    for (t_idx, (pos_map, entries)) in enumerate(zip(position_timeline, gate_timeline)):
        assert isinstance(entries, list), f'[ASSERT STRICT TIMELINE] {algo_name}: t={t_idx} entries not list'
        for gi in entries:
            assert isinstance(gi, int), f'[ASSERT STRICT TIMELINE] {algo_name}: t={t_idx} non-int gate marker {gi}'
            assert 0 <= gi < len(gates), f'[ASSERT STRICT TIMELINE] {algo_name}: t={t_idx} gate_idx={gi} out of range'
            (s, t) = gates[gi]
            assert s in pos_map and t in pos_map, f'[ASSERT STRICT TIMELINE] {algo_name}: t={t_idx} missing qubit positions for gate {gi} ({s},{t})'
            assert pos_map[s] == pos_map[t], f'[ASSERT STRICT TIMELINE] {algo_name}: t={t_idx} gate {gi} executed while not co-located: q{s}@{pos_map[s]}, q{t}@{pos_map[t]}'
            executed_counts[gi] += 1
    bad = [gi for (gi, c) in enumerate(executed_counts) if c != 1]
    assert not bad, f'[ASSERT STRICT TIMELINE] {algo_name}: gate execution counts invalid, bad_gate_indices={bad[:20]}'

def _strict_replay_and_validate(algo_name, op_log, connectivity, initial_position_table, final_position_table, initial_channel_dict, final_channel_dict):
    sim_pos = dict(initial_position_table)
    sim_ch = dict(initial_channel_dict)
    moved_suffix = defaultdict(list)
    for (op_idx, op) in enumerate(op_log):
        q = op.get('qubit')
        assert q is not None, f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} missing qubit'
        assert q in sim_pos, f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} q{q} not in position table'
        path = op.get('path', [])
        assert isinstance(path, (list, tuple)) and len(path) >= 1, f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} invalid path {path}'
        hops = int(op.get('hops', 0))
        cap_consumed = bool(op.get('cap_consumed', False))
        assert hops == len(path) - 1, f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} hops={hops} != len(path)-1={len(path) - 1}'
        assert op.get('from') == path[0], f"[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} from mismatch {op.get('from')} vs {path[0]}"
        assert op.get('to') == path[-1], f"[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} to mismatch {op.get('to')} vs {path[-1]}"
        assert sim_pos[q] == path[0], f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} q{q} starts at {sim_pos[q]} but path starts at {path[0]}'
        ch_before = channel_snapshot(sim_ch)
        for hop_idx in range(hops):
            (u, v) = (path[hop_idx], path[hop_idx + 1])
            assert_edge_in_connectivity(connectivity, u, v, context=f'{algo_name} strict replay op#{op_idx} hop#{hop_idx}')
            _assert_unit_step(u, v, context=f'{algo_name} strict replay op#{op_idx} hop#{hop_idx}')
            if cap_consumed:
                rev = sim_ch.get((v, u), 0)
                assert rev >= 2, f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} hop#{hop_idx} cannot consume {u}->{v}, reverse cap={rev}'
                sim_ch[u, v] = sim_ch.get((u, v), 0) + 1
                sim_ch[v, u] = rev - 1
                assert sim_ch[v, u] > 0, f'[ASSERT STRICT REPLAY] {algo_name}: op#{op_idx} hop#{hop_idx} made reverse non-positive: {sim_ch[v, u]}'
        ch_after = channel_snapshot(sim_ch)
        _assert_channel_delta_for_move(ch_before, ch_after, hops=hops, cap_consumed=cap_consumed, context=f'{algo_name} strict replay op#{op_idx}')
        sim_pos[q] = path[-1]
        if hops > 0:
            moved_suffix[q].extend(path[1:])
        assert_channel_invariant(sim_ch, context=f'{algo_name} strict replay after op#{op_idx}')
    assert sim_ch == final_channel_dict, f'[ASSERT STRICT REPLAY] {algo_name}: final channel mismatch'
    assert sim_pos == final_position_table, f'[ASSERT STRICT REPLAY] {algo_name}: final position table mismatch'
    return moved_suffix

def _strict_validate_atom_path_suffix(algo_name, moved_suffix, initial_atom_paths, final_atom_paths):
    for (q, expected_suffix) in moved_suffix.items():
        before = list(initial_atom_paths.get(q, []))
        after = list(final_atom_paths.get(q, []))
        assert len(after) >= len(before), f'[ASSERT STRICT ATOMPATH] {algo_name}: q{q} path shrank {len(before)}->{len(after)}'
        assert after[:len(before)] == before, f'[ASSERT STRICT ATOMPATH] {algo_name}: q{q} prefix mismatch'
        got_suffix = after[len(before):]
        assert got_suffix == expected_suffix, f'[ASSERT STRICT ATOMPATH] {algo_name}: q{q} suffix mismatch, expected={expected_suffix}, got={got_suffix}'

def _strict_validate_block_physics(algo_name, gates, position_timeline, gate_timeline, op_log, connectivity, initial_position_table, final_position_table, initial_channel_dict, final_channel_dict, initial_atom_paths, final_atom_paths):
    if not STRICT_PHYSICS_VALIDATION:
        return
    _strict_validate_gate_timeline(algo_name, gates, position_timeline, gate_timeline)
    moved_suffix = _strict_replay_and_validate(algo_name, op_log, connectivity, initial_position_table, final_position_table, initial_channel_dict, final_channel_dict)
    _strict_validate_atom_path_suffix(algo_name, moved_suffix, initial_atom_paths, final_atom_paths)