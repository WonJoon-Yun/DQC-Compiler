from ._constants import IRIS_GUIDANCE_RESIDENCY_WEIGHT, IRIS_GUIDANCE_TARGET_DISTANCE_WEIGHT
from ....cache import GraphCache
from ._constants import _future_block_decay_weight
from ._state import _is_block_end_gate
from ....gate_utils import normalize_block_to_gates

def _apply_guidance_sort_fields(node, base_cost_vector, base_total_cost):
    guidance_total = round(node.get('guidance_total_adjustment', 0.0), 8)
    node['sort_total_cost'] = round(base_total_cost + guidance_total, 8)
    sort_cost_vector = list(base_cost_vector)
    if abs(guidance_total) > 1e-12:
        sort_cost_vector.append(guidance_total)
    node['sort_cost_vector'] = sort_cost_vector

def _iris_guidance_step(*, iris_guidance, gate_spec, active_qubits, result, step_state, gcache):
    empty = {'block_index': gate_spec['block_index'], 'local_gate_index': gate_spec['local_gate_index'], 'total_adjustment': 0.0, 'execution_penalty': 0.0, 'residency_penalty': 0.0, 'execution_node': result.get('execution_node'), 'execution_target_node': None, 'execution_distance': None, 'execution_residency_supported': None, 'execution_block_size_supported': None, 'residency_considered_qubits': 0, 'residency_matching_qubits': 0}
    if not iris_guidance:
        return empty
    block_guidance = iris_guidance.get('blocks', {}).get(gate_spec['block_index'])
    if not block_guidance:
        return empty
    disable_execution_penalty = bool(iris_guidance.get('disable_execution_penalty', False))
    disable_residency_penalty = bool(iris_guidance.get('disable_residency_penalty', False))
    require_residency_support_for_execution = bool(iris_guidance.get('require_residency_support_for_execution', False))
    min_block_gates_for_execution_penalty = max(0, int(iris_guidance.get('min_block_gates_for_execution_penalty', 0) or 0))
    target_node = block_guidance.get('gate_targets', {}).get(gate_spec['local_gate_index'])
    target_chip = block_guidance.get('gate_target_chips', {}).get(gate_spec['local_gate_index'])
    execution_node = result.get('execution_node')
    execution_distance = None
    execution_residency_supported = None
    execution_block_size_supported = None
    execution_penalty = 0.0
    residency_profile = block_guidance.get('residency_profile', {})
    planned_gate_count = int(block_guidance.get('planned_gate_count', 0) or 0)
    if min_block_gates_for_execution_penalty > 0:
        execution_block_size_supported = planned_gate_count >= min_block_gates_for_execution_penalty
    if require_residency_support_for_execution:
        required_chips = []
        for qubit in tuple(dict.fromkeys(gate_spec['gate'])):
            profile = residency_profile.get(qubit)
            if profile is None or not profile.has_majority_target:
                continue
            required_chips.append(profile.target_chip)
        if required_chips and len(set(required_chips)) == 1 and (target_chip is not None):
            execution_residency_supported = required_chips[0] == target_chip
        else:
            execution_residency_supported = False
    if not disable_execution_penalty and target_node is not None and (execution_node is not None) and (execution_block_size_supported is not False) and (not require_residency_support_for_execution or execution_residency_supported):
        execution_distance = gcache.sp_len(execution_node, target_node)
        if execution_distance is not None:
            execution_penalty = float(execution_distance) * IRIS_GUIDANCE_TARGET_DISTANCE_WEIGHT
    residency_penalty = 0.0
    residency_considered_qubits = 0
    residency_matching_qubits = 0
    if residency_profile and (not disable_residency_penalty):
        residency_qubits = tuple(dict.fromkeys(gate_spec['gate']))
        for qubit in sorted(residency_qubits):
            profile = residency_profile.get(qubit)
            position = step_state['position_table'].get(qubit)
            if profile is None or position is None or (not profile.has_majority_target):
                continue
            residency_considered_qubits += 1
            if profile.target_chip == gcache.chip_of(position):
                residency_matching_qubits += 1
                continue
            residency_penalty += profile.top_chip_mass * IRIS_GUIDANCE_RESIDENCY_WEIGHT
    total_adjustment = round(execution_penalty + residency_penalty, 8)
    return {'block_index': gate_spec['block_index'], 'local_gate_index': gate_spec['local_gate_index'], 'total_adjustment': total_adjustment, 'execution_penalty': round(execution_penalty, 8), 'residency_penalty': round(residency_penalty, 8), 'execution_node': execution_node, 'execution_target_node': target_node, 'execution_distance': execution_distance, 'execution_residency_supported': execution_residency_supported, 'execution_block_size_supported': execution_block_size_supported, 'residency_considered_qubits': residency_considered_qubits, 'residency_matching_qubits': residency_matching_qubits}

def _iris_candidate_seed_target(iris_guidance, gate_spec):
    if not iris_guidance or not iris_guidance.get('use_candidate_seed', False):
        return (None, None)
    block_guidance = iris_guidance.get('blocks', {}).get(gate_spec['block_index'])
    if not block_guidance:
        return (None, None)
    target_node = block_guidance.get('gate_targets', {}).get(gate_spec['local_gate_index'])
    target_chip = block_guidance.get('gate_target_chips', {}).get(gate_spec['local_gate_index'])
    return (target_node, target_chip)

def _critical_future_block_step(
    *,
    gate_specs,
    gate_offset,
    step_state,
    blocks,
    block_ids,
    connectivity,
    lookahead_depth,
    enabled,
    scan_depth,
    topk,
    pair_weight,
    multipair_weight,
    enable_same_chip_pressure=False,
    same_chip_pair_weight=0.25,
    same_chip_multipair_weight=0.125,
    enable_pair_distance_pressure=False,
    pair_distance_weight=0.125,
    block_levels=None,
    future_block_decay_mode="linear",
):
    gate_spec = gate_specs[gate_offset]
    empty = {
        "block_index": gate_spec["block_index"],
        "block_id": gate_spec["block_id"],
        "total_adjustment": 0.0,
        "component_adjustments": {
            "split_pair_adjustment": 0.0,
            "same_chip_adjustment": 0.0,
            "pair_distance_adjustment": 0.0,
        },
        "risky_blocks": [],
    }
    if not _is_block_end_gate(gate_specs, gate_offset):
        return empty
    any_enabled = (
        bool(enabled)
        or bool(enable_same_chip_pressure)
        or bool(enable_pair_distance_pressure)
    )
    if not any_enabled:
        return empty

    (
        risky_blocks,
        total_adjustment,
        component_adjustments,
    ) = _future_block_alignment_risk_summary(
        state=step_state,
        blocks=blocks,
        block_ids=block_ids,
        block_levels=block_levels,
        connectivity=connectivity,
        current_block_index=gate_spec["block_index"],
        lookahead_depth=lookahead_depth,
        scan_depth=scan_depth,
        topk=topk,
        pair_weight=pair_weight,
        multipair_weight=multipair_weight,
        enable_split_pairs=enabled,
        enable_same_chip_pressure=enable_same_chip_pressure,
        same_chip_pair_weight=same_chip_pair_weight,
        same_chip_multipair_weight=same_chip_multipair_weight,
        enable_pair_distance_pressure=enable_pair_distance_pressure,
        pair_distance_weight=pair_distance_weight,
        future_block_decay_mode=future_block_decay_mode,
    )
    return {
        "block_index": gate_spec["block_index"],
        "block_id": gate_spec["block_id"],
        "total_adjustment": total_adjustment,
        "component_adjustments": component_adjustments,
        "risky_blocks": risky_blocks,
    }


def _preserve_objective_tie_sort_fields(children, objective_tol=1e-9):
    """Do not let guidance-only adjustments break exact objective ties.

    When multiple candidates have the same raw objective total, keep their
    ordering on the objective cost vector and downstream deterministic tie-breaks
    rather than the IRIS guidance adjustment. This keeps guidance from flipping
    exact-cost ties while still allowing it to influence non-tied candidates.
    """
    if len(children) <= 1:
        return

    groups = {}
    for idx, child in enumerate(children):
        key = round(float(child["total_cost"]), 9)
        groups.setdefault(key, []).append(idx)

    for indices in groups.values():
        if len(indices) <= 1:
            continue
        totals = [children[idx]["total_cost"] for idx in indices]
        if max(totals) - min(totals) > objective_tol:
            continue
        for idx in indices:
            child = children[idx]
            critical_total = round(
                child.get("critical_future_total_adjustment", 0.0),
                8,
            )
            child["sort_total_cost"] = round(child["total_cost"] + critical_total, 8)
            sort_cost_vector = list(child.get("objective_cost_vector", child["cost_vector"]))
            if abs(critical_total) > 1e-12:
                sort_cost_vector.append(critical_total)
            child["sort_cost_vector"] = sort_cost_vector


def _future_block_alignment_risk_summary(
    *,
    state,
    blocks,
    block_ids,
    connectivity,
    current_block_index,
    lookahead_depth,
    scan_depth,
    topk,
    pair_weight,
    multipair_weight,
    enable_split_pairs=True,
    enable_same_chip_pressure=False,
    same_chip_pair_weight=0.25,
    same_chip_multipair_weight=0.125,
    enable_pair_distance_pressure=False,
    pair_distance_weight=0.125,
    block_levels=None,
    future_block_decay_mode="linear",
):
    effective_scan_depth = max(0, int(scan_depth))
    if effective_scan_depth <= 0:
        return [], 0.0, {
            "split_pair_adjustment": 0.0,
            "same_chip_adjustment": 0.0,
            "pair_distance_adjustment": 0.0,
        }

    start_index = current_block_index + max(0, int(lookahead_depth)) + 1
    if start_index >= len(blocks):
        return [], 0.0, {
            "split_pair_adjustment": 0.0,
            "same_chip_adjustment": 0.0,
            "pair_distance_adjustment": 0.0,
        }

    upper = min(len(blocks), start_index + effective_scan_depth)
    gcache = GraphCache(connectivity)
    position_table = state["position_table"]
    summaries = []

    for future_block_index in range(start_index, upper):
        seen_pairs = set()
        split_pairs = []
        split_qubits = set()
        same_chip_pairs = []
        same_chip_qubits = set()
        pair_distance_sum = 0.0
        for s, t in normalize_block_to_gates(blocks[future_block_index]):
            pair = (s, t) if s <= t else (t, s)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            pos_s = position_table.get(s)
            pos_t = position_table.get(t)
            if pos_s is None or pos_t is None:
                continue
            pair_distance = gcache.sp_len(pos_s, pos_t)
            if pair_distance is not None and pair_distance > 0:
                pair_distance_sum += float(pair_distance)
            if gcache.chip_of(pos_s) != gcache.chip_of(pos_t):
                split_pairs.append([pair[0], pair[1]])
                split_qubits.update(pair)
                continue
            if pos_s != pos_t:
                same_chip_pairs.append([pair[0], pair[1]])
                same_chip_qubits.update(pair)

        split_pair_count = len(split_pairs)
        same_chip_pair_count = len(same_chip_pairs)
        split_pair_tail = max(0, split_pair_count - 1)
        same_chip_pair_tail = max(0, same_chip_pair_count - 1)
        raw_split_adjustment = 0.0
        raw_same_chip_adjustment = 0.0
        raw_pair_distance_adjustment = 0.0
        if enable_split_pairs:
            raw_split_adjustment = (
                float(pair_weight) * split_pair_count
                + float(multipair_weight) * (split_pair_tail ** 2)
            )
        if enable_same_chip_pressure:
            raw_same_chip_adjustment = (
                float(same_chip_pair_weight) * same_chip_pair_count
                + float(same_chip_multipair_weight) * (same_chip_pair_tail ** 2)
            )
        if enable_pair_distance_pressure:
            raw_pair_distance_adjustment = (
                float(pair_distance_weight) * pair_distance_sum
            )
        raw_penalty = (
            raw_split_adjustment
            + raw_same_chip_adjustment
            + raw_pair_distance_adjustment
        )
        if raw_penalty <= 0:
            continue

        distance_weight = _future_block_decay_weight(
            current_block_index,
            future_block_index,
            decay_mode=future_block_decay_mode,
            block_levels=block_levels,
        )
        weighted_split_adjustment = round(
            distance_weight * raw_split_adjustment,
            8,
        )
        weighted_same_chip_adjustment = round(
            distance_weight * raw_same_chip_adjustment,
            8,
        )
        weighted_pair_distance_adjustment = round(
            distance_weight * raw_pair_distance_adjustment,
            8,
        )
        weighted_penalty = round(
            weighted_split_adjustment
            + weighted_same_chip_adjustment
            + weighted_pair_distance_adjustment,
            8,
        )
        summaries.append(
            {
                "block_index": future_block_index,
                "block_id": block_ids[future_block_index],
                "distance": future_block_index - current_block_index,
                "distance_weight": round(distance_weight, 8),
                "distance_mode": str(future_block_decay_mode),
                "split_pair_count": split_pair_count,
                "split_qubit_count": len(split_qubits),
                "split_pairs": split_pairs,
                "same_chip_pair_count": same_chip_pair_count,
                "same_chip_qubit_count": len(same_chip_qubits),
                "same_chip_pairs": same_chip_pairs,
                "pair_distance_sum": round(pair_distance_sum, 8),
                "weighted_split_adjustment": weighted_split_adjustment,
                "weighted_same_chip_adjustment": weighted_same_chip_adjustment,
                "weighted_pair_distance_adjustment": (
                    weighted_pair_distance_adjustment
                ),
                "weighted_penalty": weighted_penalty,
            }
        )

    summaries.sort(
        key=lambda item: (
            -item["weighted_penalty"],
            -item["weighted_same_chip_adjustment"],
            -item["weighted_pair_distance_adjustment"],
            -item["split_pair_count"],
            -item["same_chip_pair_count"],
            item["block_index"],
        )
    )
    top_summaries = summaries[: max(0, int(topk))]
    component_adjustments = {
        "split_pair_adjustment": round(
            sum(item["weighted_split_adjustment"] for item in top_summaries),
            8,
        ),
        "same_chip_adjustment": round(
            sum(item["weighted_same_chip_adjustment"] for item in top_summaries),
            8,
        ),
        "pair_distance_adjustment": round(
            sum(item["weighted_pair_distance_adjustment"] for item in top_summaries),
            8,
        ),
    }
    return top_summaries, round(
        sum(item["weighted_penalty"] for item in top_summaries),
        8,
    ), component_adjustments
