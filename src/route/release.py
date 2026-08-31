from .channel import channel_snapshot, consume_path, link_capacity, print_channel_delta
from .interact import get_still_active_qubits
from .lookahead import lookahead_cost
from .pathfinding import find_path_with_capacity

def _compute_active_centroid(still_active, qubit_positions, gcache):
    coords = []
    for q in still_active:
        if q in qubit_positions:
            coords.append(gcache.node_coords(qubit_positions[q]))
    if not coords:
        return (None, None)
    cx = sum((c[0] for c in coords)) / len(coords)
    cy = sum((c[1] for c in coords)) / len(coords)
    return (cx, cy)

def _occupied_by_active(still_active, qubit_positions):
    occupied = set()
    for q in still_active:
        if q in qubit_positions:
            occupied.add(qubit_positions[q])
    return occupied

def _score_release_candidate(candidate, baseline_la):
    return (candidate['la_delta'], -candidate['dist_from_active'], candidate['hops'], str(candidate['pos']), tuple(candidate['path']))

def _evaluate_release_position(pos, path, qubit, qubit_positions, future_pairs, baseline_la, cx, cy, gcache):
    hops = len(path) - 1
    pos_sim = dict(qubit_positions)
    pos_sim[qubit] = pos
    la_sim = lookahead_cost(pos_sim, future_pairs, gcache)
    la_delta = la_sim - baseline_la
    dist_from_active = 0.0
    if cx is not None and cy is not None:
        nc = gcache.node_coords(pos)
        dist_from_active = (nc[0] - cx) ** 2 + (nc[1] - cy) ** 2
    return {'pos': pos, 'path': path, 'la_delta': la_delta, 'dist_from_active': dist_from_active, 'hops': hops}

def find_best_release_position(qubit, curr_pos, future_gates, qubit_positions, still_active, ch, gcache, lookahead_depth=8):
    if not future_gates:
        return None
    (cx, cy) = _compute_active_centroid(still_active, qubit_positions, gcache)
    future_pairs = future_gates[:lookahead_depth]
    baseline_la = lookahead_cost(qubit_positions, future_pairs, gcache)
    occupied = _occupied_by_active(still_active, qubit_positions)
    candidates = [{'pos': curr_pos, 'path': [curr_pos], 'la_delta': 0, 'dist_from_active': 0, 'hops': 0}]
    for nb in gcache.neighbors(curr_pos):
        if link_capacity(curr_pos, nb, ch) <= 0 or nb in occupied:
            continue
        cand = _evaluate_release_position(nb, [curr_pos, nb], qubit, qubit_positions, future_pairs, baseline_la, cx, cy, gcache)
        candidates.append(cand)
    two_hop_targets = set()
    for nb in gcache.neighbors(curr_pos):
        for nb2 in gcache.neighbors(nb):
            if nb2 != curr_pos and nb2 not in occupied:
                two_hop_targets.add(nb2)
    for target in sorted(two_hop_targets):
        p = find_path_with_capacity(curr_pos, target, ch, gcache=gcache)
        if p is not None and len(p) <= 3:
            cand = _evaluate_release_position(target, p, qubit, qubit_positions, future_pairs, baseline_la, cx, cy, gcache)
            candidates.append(cand)
    candidates.sort(key=lambda c: _score_release_candidate(c, baseline_la))
    best = candidates[0]
    if best['hops'] == 0 or best['la_delta'] >= 0:
        return None
    return best

def handle_released_qubits(released_qubits, gate_idx, future_gates, qubit_positions, position_table, atom_paths, active_qubits, ii, connectivity, ch, gcache, num_relocates, gate_relocates, op_log, gate_timeline, position_timeline, PRINT_DEBUG=False):
    if not released_qubits or not future_gates:
        return (num_relocates, gate_relocates)
    still_active = get_still_active_qubits(ii)
    for q in sorted(released_qubits):
        curr_pos = qubit_positions.get(q, position_table.get(q))
        if curr_pos is None:
            continue
        result = find_best_release_position(qubit=q, curr_pos=curr_pos, future_gates=future_gates, qubit_positions=qubit_positions, still_active=still_active, ch=ch, gcache=gcache, lookahead_depth=8)
        if result is None:
            continue
        target_pos = result['pos']
        path = result['path']
        hops = result['hops']
        la_delta = result['la_delta']
        consume_path(connectivity, path, ch, context=f'gate {gate_idx} RELEASE q{q} {curr_pos}→{target_pos}')
        for node in path[1:]:
            atom_paths[q].append(node)
        for node in path[1:-1]:
            qubit_positions[q] = node
            position_table[q] = node
            position_timeline.append({qq: qubit_positions[qq] for qq in sorted(active_qubits)})
            gate_timeline.append([])
        qubit_positions[q] = target_pos
        position_table[q] = target_pos
        num_relocates += hops
        gate_relocates += hops
        op_log.append({'gate_idx': gate_idx, 'op_type': 'RELEASE', 'qubit': q, 'from': curr_pos, 'to': target_pos, 'path': list(path), 'hops': hops, 'cost_model': f'release({hops}h, la_delta={la_delta:.1f})', 'cap_consumed': True})
        gate_timeline.append([])
    return (num_relocates, gate_relocates)