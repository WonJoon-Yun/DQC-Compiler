from ...gate_utils import normalize_block_to_gates
from ...lookahead import anchor_convergence_cost

def _node_chip_key(node, gcache):
    chip = gcache.chip_of(node)
    return node if chip is None else chip

def _precompute_block_future_uses(gates):
    uses = {}
    for (gi, (s, t)) in enumerate(gates):
        uses.setdefault(s, []).append(gi)
        uses.setdefault(t, []).append(gi)
    return uses

def _future_local_chip_run_length(q, gates, future_uses, position_table, gcache, chip_key):
    run = 0
    for future_gi in future_uses.get(q, []):
        (s_f, t_f) = gates[future_gi]
        partner = t_f if s_f == q else s_f
        pos_partner = position_table.get(partner)
        if pos_partner is None:
            break
        if _node_chip_key(pos_partner, gcache) != chip_key:
            break
        run += 1
    return run

def _block_future_ping_pong_penalty(gates, position_table, candidate, gcache):
    if not gates:
        return 0.0
    future_uses = _precompute_block_future_uses(gates)
    candidate_chip = _node_chip_key(candidate, gcache)
    penalty = 0.0
    for (q, use_list) in future_uses.items():
        if len(use_list) <= 1:
            continue
        pos_q = position_table.get(q)
        if pos_q is None:
            continue
        stay_chip = _node_chip_key(pos_q, gcache)
        if stay_chip == candidate_chip:
            continue
        stay_local_run = _future_local_chip_run_length(q, gates, future_uses, position_table, gcache, stay_chip)
        candidate_local_run = _future_local_chip_run_length(q, gates, future_uses, position_table, gcache, candidate_chip)
        penalty += max(0, stay_local_run - candidate_local_run)
        for future_gi in use_list:
            (s_f, t_f) = gates[future_gi]
            partner = t_f if s_f == q else s_f
            pos_partner = position_table.get(partner)
            if pos_partner is None:
                continue
            partner_chip = _node_chip_key(pos_partner, gcache)
            if partner_chip == stay_chip and partner_chip != candidate_chip:
                penalty += 1.0 / max(1, future_gi + 1)
    return penalty

def _block_proxy_cost(block, position_table, candidate, gcache, channel_dict=None, include_future_ping_pong_penalty=False):
    move_cost = 0
    gates = normalize_block_to_gates(block)
    for (s, t) in gates:
        pos_s = position_table.get(s)
        pos_t = position_table.get(t)
        if pos_s is None or pos_t is None:
            return float('inf')
        ds = gcache.sp_len(pos_s, candidate)
        dt = gcache.sp_len(pos_t, candidate)
        if ds is None or dt is None:
            return float('inf')
        move_cost += ds + dt
    total_cost = move_cost
    if channel_dict:
        (_anchor_move_cost, release_penalty, _anchor_total_cost) = anchor_convergence_cost(position_table, gates, gcache, candidate, channel_dict=channel_dict)
        if release_penalty == float('inf'):
            return float('inf')
        total_cost += release_penalty
    if include_future_ping_pong_penalty:
        total_cost += _block_future_ping_pong_penalty(gates, position_table, candidate, gcache)
    return total_cost

def _block_active_qubits(block):
    active_qubits = set()
    for (s, t) in normalize_block_to_gates(block):
        active_qubits.add(s)
        active_qubits.add(t)
    return active_qubits

def _current_level_ceiling(next_ids, block_level_lookup):
    if block_level_lookup is None:
        return None
    current_levels = [block_level_lookup.get(block_id) for block_id in next_ids if block_level_lookup.get(block_id) is not None]
    return max(current_levels) if current_levels else None

def _is_strictly_later_layer(block_id, block_level_lookup, current_level_ceiling):
    if block_level_lookup is None or current_level_ceiling is None:
        return True
    future_level = block_level_lookup.get(block_id)
    if future_level is None:
        return True
    return future_level > current_level_ceiling

def _future_partner_indices(
    future_blocks,
    future_ids,
    current_active_qubits,
    block_level_lookup=None,
    current_level_ceiling=None,
):
    indices = []
    for future_index, future_block in enumerate(future_blocks):
        if not _is_strictly_later_layer(
            future_ids[future_index],
            block_level_lookup,
            current_level_ceiling,
        ):
            continue
        overlap_count = len(
            _block_active_qubits(future_block) & current_active_qubits
        )
        if overlap_count > 0:
            indices.append(future_index)
    return indices

def _future_partner_records(future_blocks, future_ids, current_active_qubits, block_level_lookup=None, current_level_ceiling=None):
    partner_records = []
    future_hits_per_qubit = {}
    for (future_index, future_block) in enumerate(future_blocks):
        if not _is_strictly_later_layer(future_ids[future_index], block_level_lookup, current_level_ceiling):
            continue
        overlap_qubits = _block_active_qubits(future_block) & current_active_qubits
        overlap_count = len(overlap_qubits)
        if overlap_count <= 0:
            continue
        future_level = None if block_level_lookup is None else block_level_lookup.get(future_ids[future_index])
        if current_level_ceiling is None or future_level is None:
            level_distance = 0
        else:
            level_distance = max(0, int(future_level) - int(current_level_ceiling))
        partner_records.append({'future_index': future_index, 'overlap_qubits': overlap_qubits, 'overlap_count': overlap_count, 'level_distance': level_distance})
        for q in overlap_qubits:
            future_hits_per_qubit[q] = future_hits_per_qubit.get(q, 0) + 1
    for record in partner_records:
        record['recurrence_support'] = sum((max(0, int(future_hits_per_qubit.get(q, 0)) - 1) for q in record['overlap_qubits']))
    return partner_records

def _future_partner_ranked_priority(record):
    return (0 if record['overlap_count'] >= 2 else 1, -record['overlap_count'], -record['recurrence_support'], record['level_distance'], record['future_index'])

def _future_partner_support_signature(records):
    return (sum((1 for record in records if record['overlap_count'] >= 2)), sum((int(record['overlap_count']) for record in records)), sum((int(record['recurrence_support']) for record in records)))

def _future_partner_structural_signature(records):
    return (sum((1 for record in records if record['overlap_count'] >= 2)), sum((int(record['overlap_count']) for record in records)))

def _future_partner_temporal_signature(records):
    return (sum((int(record['level_distance']) for record in records)), max((int(record['level_distance']) for record in records), default=0), sum((int(record['future_index']) for record in records)))

def _future_partner_ranked_indices(future_blocks, future_ids, current_active_qubits, requested_lookahead_extra, block_level_lookup=None, current_level_ceiling=None):
    partner_records = _future_partner_records(future_blocks, future_ids, current_active_qubits, block_level_lookup=block_level_lookup, current_level_ceiling=current_level_ceiling)
    if requested_lookahead_extra <= 0 or not partner_records:
        return []
    if len(partner_records) <= requested_lookahead_extra:
        return [record['future_index'] for record in partner_records[:requested_lookahead_extra]]
    plain_records = partner_records[:requested_lookahead_extra]
    near_band_size = min(len(partner_records), max(2 * int(requested_lookahead_extra), 8))
    near_band_records = list(partner_records[:near_band_size])
    ranked_records = sorted(near_band_records, key=_future_partner_ranked_priority)[:requested_lookahead_extra]
    plain_support = _future_partner_support_signature(plain_records)
    ranked_support = _future_partner_support_signature(ranked_records)
    plain_structural = _future_partner_structural_signature(plain_records)
    ranked_structural = _future_partner_structural_signature(ranked_records)
    plain_temporal = _future_partner_temporal_signature(plain_records)
    ranked_temporal = _future_partner_temporal_signature(ranked_records)
    if ranked_structural <= plain_structural:
        return [record['future_index'] for record in plain_records]
    dense_plain_regime = plain_structural[0] >= max(2, int(requested_lookahead_extra) - 1) and plain_structural[1] >= 2 * int(requested_lookahead_extra) + 1
    strong_ranked_gain = ranked_support > plain_support
    if ranked_temporal <= plain_temporal or (dense_plain_regime and strong_ranked_gain):
        return [record['future_index'] for record in ranked_records]
    return [record['future_index'] for record in plain_records]

def _next_layer_future_indices(
    future_blocks,
    future_ids,
    current_active_qubits,
    requested_lookahead_extra,
    block_level_lookup=None,
    current_level_ceiling=None,
    active_first=False,
):
    eligible_future_indices = [
        future_index
        for future_index, future_block_id in enumerate(future_ids)
        if _is_strictly_later_layer(
            future_block_id,
            block_level_lookup,
            current_level_ceiling,
        )
    ]
    if active_first:
        def _next_layer_priority(future_index):
            future_block_id = future_ids[future_index]
            future_level = (
                None
                if block_level_lookup is None
                else block_level_lookup.get(future_block_id)
            )
            if current_level_ceiling is None or future_level is None:
                level_distance = 0
            else:
                level_distance = max(
                    0,
                    int(future_level) - int(current_level_ceiling),
                )
            overlap_count = len(
                _block_active_qubits(future_blocks[future_index])
                & current_active_qubits
            )
            return (
                level_distance,
                0 if overlap_count > 0 else 1,
                -overlap_count,
                future_index,
            )

        eligible_future_indices.sort(key=_next_layer_priority)
    return eligible_future_indices[:requested_lookahead_extra]


def _should_guard_future_partner_window(
    *,
    requested_lookahead_extra,
    future_blocks,
    current_active_qubits,
    partner_indices,
):
    if requested_lookahead_extra <= 0 or not future_blocks:
        return False
    if len(partner_indices) <= requested_lookahead_extra:
        return False

    current_qubit_count = len(current_active_qubits)
    partner_ratio = len(partner_indices) / float(len(future_blocks))

    return (
        current_qubit_count >= max(8, 2 * int(requested_lookahead_extra))
        and partner_ratio >= 0.5
    )

def build_qucomm_execution_window(blocks, execution_block_count, block_id_start, position_table, connectivity, base_agg_func, lookahead_depth, block_level_lookup=None, future_window_mode='next_layer_active_first', enable_future_partner_dense_guard=False):
    normalized_future_window_mode = str(future_window_mode or 'next_layer_active_first').lower()
    if normalized_future_window_mode not in {'serial', 'next_layer', 'next_layer_active_first', 'future_partner', 'future_partner_ranked', 'serial_plus_future_partner'}:
        normalized_future_window_mode = 'next_layer_active_first'
    next_blocks = list(blocks[:execution_block_count])
    future_blocks = list(blocks[execution_block_count:])
    next_ids = [block_id_start + i for i in range(len(next_blocks))]
    future_ids = [block_id_start + len(next_blocks) + i for i in range(len(future_blocks))]
    next_aggs = [base_agg_func(normalize_block_to_gates(block), position_table, connectivity) for block in next_blocks]
    requested_lookahead_extra = min(max(0, lookahead_depth), len(future_blocks))
    future_window_indices = list(range(requested_lookahead_extra))
    current_level_ceiling = _current_level_ceiling(next_ids, block_level_lookup)
    current_active_qubits = set()
    for block in next_blocks:
        current_active_qubits.update(_block_active_qubits(block))
    if (
        normalized_future_window_mode in {"next_layer", "next_layer_active_first"}
        and requested_lookahead_extra > 0
        and future_ids
    ):
        future_window_indices = _next_layer_future_indices(
            future_blocks,
            future_ids,
            current_active_qubits,
            requested_lookahead_extra,
            block_level_lookup=block_level_lookup,
            current_level_ceiling=current_level_ceiling,
            active_first=(
                normalized_future_window_mode == "next_layer_active_first"
            ),
        )
    elif (
        normalized_future_window_mode in {
            "future_partner",
            "future_partner_ranked",
        }
        and requested_lookahead_extra > 0
        and future_ids
    ):
        partner_indices = _future_partner_indices(
            future_blocks,
            future_ids,
            current_active_qubits,
            block_level_lookup=block_level_lookup,
            current_level_ceiling=current_level_ceiling,
        )
        ranked_partner_indices = None
        if normalized_future_window_mode == "future_partner_ranked":
            ranked_partner_indices = _future_partner_ranked_indices(
                future_blocks,
                future_ids,
                current_active_qubits,
                requested_lookahead_extra,
                block_level_lookup=block_level_lookup,
                current_level_ceiling=current_level_ceiling,
            )
        if (
            enable_future_partner_dense_guard
            and _should_guard_future_partner_window(
                requested_lookahead_extra=requested_lookahead_extra,
                future_blocks=future_blocks,
                current_active_qubits=current_active_qubits,
                partner_indices=partner_indices,
            )
        ):
            future_window_indices = _next_layer_future_indices(
                future_blocks,
                future_ids,
                current_active_qubits,
                requested_lookahead_extra,
                block_level_lookup=block_level_lookup,
                current_level_ceiling=current_level_ceiling,
                active_first=True,
            )
        else:
            if normalized_future_window_mode == "future_partner_ranked":
                future_window_indices = ranked_partner_indices or []
            else:
                future_window_indices = partner_indices[:requested_lookahead_extra]
    elif (
        normalized_future_window_mode == "serial_plus_future_partner"
        and requested_lookahead_extra > 0
        and future_ids
    ):
        serial_indices = list(range(requested_lookahead_extra))
        partner_indices = _future_partner_indices(
            future_blocks,
            future_ids,
            current_active_qubits,
            block_level_lookup=block_level_lookup,
            current_level_ceiling=current_level_ceiling,
        )
        if (
            enable_future_partner_dense_guard
            and _should_guard_future_partner_window(
                requested_lookahead_extra=requested_lookahead_extra,
                future_blocks=future_blocks,
                current_active_qubits=current_active_qubits,
                partner_indices=partner_indices,
            )
        ):
            partner_indices = _next_layer_future_indices(
                future_blocks,
                future_ids,
                current_active_qubits,
                requested_lookahead_extra,
                block_level_lookup=block_level_lookup,
                current_level_ceiling=current_level_ceiling,
                active_first=True,
            )
        else:
            partner_indices = partner_indices[:requested_lookahead_extra]
        future_window_indices = sorted(set(serial_indices) | set(partner_indices))
    future_window_blocks = [future_blocks[i] for i in future_window_indices]
    future_window_aggs = [base_agg_func(normalize_block_to_gates(block), position_table, connectivity) for block in future_window_blocks]
    window_blocks = next_blocks + future_window_blocks
    window_aggs = next_aggs + future_window_aggs
    future_window_ids = [future_ids[i] for i in future_window_indices]
    window_ids = next_ids + future_window_ids
    execution_k = min(execution_block_count, len(next_blocks))
    lookahead_extra = len(future_window_blocks)
    assert len(window_blocks) == len(window_aggs) == len(window_ids), f'[ASSERT build_qucomm_execution_window] window sizes mismatch: blocks={len(window_blocks)} aggs={len(window_aggs)} ids={len(window_ids)}'
    assert window_blocks[:len(next_blocks)] == next_blocks
    assert window_aggs[:len(next_aggs)] == next_aggs
    assert window_ids[:len(next_ids)] == next_ids
    assert execution_k == min(execution_block_count, len(next_blocks))
    if lookahead_depth > 0 and future_blocks:
        assert 0 <= lookahead_extra <= min(lookahead_depth, len(future_blocks))
    return {'next_blocks': next_blocks, 'future_blocks': future_blocks, 'next_aggs': next_aggs, 'next_ids': next_ids, 'future_ids': future_ids, 'future_window_ids': future_window_ids, 'window_blocks': window_blocks, 'window_aggs': window_aggs, 'window_ids': window_ids, 'lookahead_extra': lookahead_extra, 'future_window_mode': normalized_future_window_mode, 'execution_k': execution_k}