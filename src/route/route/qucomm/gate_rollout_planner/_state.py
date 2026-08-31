from collections import defaultdict
from ....cache import GraphCache
from ....gate_utils import normalize_block_to_gates
from ..lookahead import _block_proxy_cost
from ._constants import _node_sort_key
from ._constants import _effective_future_proxy_depth
from ._constants import _future_block_decay_weight
from ._constants import _rollout_window_upper
from ....constants import compute_routing_cost
import math

def _block_active_qubits(block):
    active_qubits = set()
    for (s, t) in normalize_block_to_gates(block):
        active_qubits.add(s)
        active_qubits.add(t)
    return active_qubits

def _select_locality_agg_node(block, position_table, connectivity, channel_dict=None, base_agg=None):
    gates = normalize_block_to_gates(block)
    if not gates:
        if base_agg in connectivity.nodes:
            return base_agg
        return sorted(connectivity.nodes)[0]
    active_qubits = _block_active_qubits(block)
    gcache = GraphCache(connectivity)
    best_node = None
    best_key = None
    for candidate in sorted(connectivity.nodes):
        proxy_cost = _block_proxy_cost(block, position_table, candidate, gcache, channel_dict=channel_dict, include_future_ping_pong_penalty=True)
        already_here = sum((1 for q in active_qubits if position_table.get(q) == candidate))
        score_key = (proxy_cost, -already_here, 0 if candidate == base_agg else 1, _node_sort_key(candidate))
        if best_key is None or score_key < best_key:
            best_key = score_key
            best_node = candidate
    if best_node is not None:
        return best_node
    if base_agg in connectivity.nodes:
        return base_agg
    return sorted(connectivity.nodes)[0]

def _future_specs_within_block_horizon(gate_specs, gate_offset, future_block_depth):
    if gate_offset >= len(gate_specs):
        return []
    future_specs = []
    start_block_index = gate_specs[gate_offset]['block_index']
    max_block_index = start_block_index + max(0, int(future_block_depth))
    for spec in gate_specs[gate_offset + 1:]:
        if spec['block_index'] > max_block_index:
            break
        future_specs.append(spec)
    return future_specs

def _resolve_block_agg(node, gate_spec, *, blocks, aggs, connectivity, start_block_index):
    block_index = gate_spec['block_index']
    block_aggs = node.setdefault('block_aggs', {})
    if block_index in block_aggs:
        return block_aggs[block_index]
    base_agg = aggs[block_index] if block_index < len(aggs) else None
    if block_index == start_block_index and base_agg is not None:
        block_agg = base_agg
    else:
        block_agg = _select_locality_agg_node(blocks[block_index], node['state']['position_table'], connectivity, channel_dict=node['state']['channel_dict'], base_agg=base_agg)
    block_aggs[block_index] = block_agg
    return block_agg

def _build_gate_interact_info(gates):
    info = defaultdict(list)
    for (s, t) in gates:
        info[s].append((s, t))
        info[t].append((s, t))
    return dict(info)

def _forced_action_to_key(action):
    if not action or action.get('mode') != 'one_meet':
        return None
    return (action['meeting_node'], action['move_qubit'])

def _candidate_key(candidate):
    return (candidate['meeting_node'], candidate['move_qubit'])

def _mapping_key(position_table):
    return tuple(sorted(position_table.items()))

def _flatten_gate_window(blocks, block_ids, block_index, future_block_depth):
    specs = []
    plan_index = 0
    upper = _rollout_window_upper(len(blocks), block_index, future_block_depth)
    for bi in range(block_index, upper):
        gates = normalize_block_to_gates(blocks[bi])
        for gi, gate in enumerate(gates):
            specs.append(
                {
                    "block_index": bi,
                    "block_id": block_ids[bi],
                    "local_gate_index": gi,
                    "global_gate_index": plan_index,
                    "gate": gate,
                }
            )
            plan_index += 1
    return specs


def _same_block_future_specs(gate_specs, gate_offset):
    if gate_offset >= len(gate_specs):
        return []

    future_specs = []
    current_block_index = gate_specs[gate_offset]["block_index"]
    for spec in gate_specs[gate_offset + 1 :]:
        if spec["block_index"] != current_block_index:
            break
        future_specs.append(spec)
    return future_specs


def _estimate_future_block_suffix(
    *,
    state,
    blocks,
    aggs,
    connectivity,
    current_block_index,
    lookahead_depth,
    block_levels=None,
    future_block_decay_mode="linear",
):
    effective_lookahead_depth = _effective_future_proxy_depth(lookahead_depth)
    upper = _rollout_window_upper(
        len(blocks),
        current_block_index,
        effective_lookahead_depth,
    )
    if upper <= current_block_index + 1:
        return [], [], _snapshot_state(state)

    gcache = GraphCache(connectivity)
    estimated_state = _snapshot_state(state)
    estimated_cost_vector = []
    estimated_window_aggs = []

    for future_block_index in range(current_block_index + 1, upper):
        block = blocks[future_block_index]
        base_agg = aggs[future_block_index] if future_block_index < len(aggs) else None
        block_agg = _select_locality_agg_node(
            block,
            estimated_state["position_table"],
            connectivity,
            channel_dict=estimated_state["channel_dict"],
            base_agg=base_agg,
        )
        proxy_cost = _block_proxy_cost(
            block,
            estimated_state["position_table"],
            block_agg,
            gcache,
            channel_dict=estimated_state["channel_dict"],
            include_future_ping_pong_penalty=True,
        )
        if math.isinf(proxy_cost):
            weighted_cost = float("inf")
        else:
            weighted_cost = compute_routing_cost(proxy_cost, 0, 0) * (
                _future_block_decay_weight(
                    current_block_index,
                    future_block_index,
                    horizon_depth=effective_lookahead_depth,
                    decay_mode=future_block_decay_mode,
                    block_levels=block_levels,
                )
            )
        estimated_cost_vector.append(weighted_cost)
        estimated_window_aggs.append(block_agg)

        for qubit in _block_active_qubits(block):
            estimated_state["position_table"][qubit] = block_agg
            history = list(estimated_state["atom_paths"].get(qubit, []))
            if not history or history[-1] != block_agg:
                history.append(block_agg)
            estimated_state["atom_paths"][qubit] = history

    return estimated_cost_vector, estimated_window_aggs, estimated_state


def _is_block_end_gate(gate_specs, gate_offset):
    if gate_offset >= len(gate_specs) - 1:
        return True
    return gate_specs[gate_offset + 1]["block_index"] != gate_specs[gate_offset]["block_index"]


def _build_exact_suffix_rollout_window(
    *,
    blocks,
    aggs,
    block_ids,
    block_index,
    local_gate_index,
    lookahead_depth,
):
    upper = _rollout_window_upper(len(blocks), block_index, lookahead_depth)
    suffix_blocks = []
    suffix_aggs = []
    suffix_block_ids = []

    current_gates = normalize_block_to_gates(blocks[block_index])
    remaining_current_gates = current_gates[local_gate_index + 1 :]
    if remaining_current_gates:
        suffix_blocks.append(list(remaining_current_gates))
        suffix_aggs.append(aggs[block_index] if block_index < len(aggs) else None)
        suffix_block_ids.append(block_ids[block_index])

    for future_block_index in range(block_index + 1, upper):
        suffix_blocks.append(blocks[future_block_index])
        suffix_aggs.append(
            aggs[future_block_index] if future_block_index < len(aggs) else None
        )
        suffix_block_ids.append(block_ids[future_block_index])

    return suffix_blocks, suffix_aggs, suffix_block_ids


def _wrap_simulate_result(result):
    """Wrap simulate_qucomm_gate_transition result as state without re-copying.

    simulate already copies position_table/channel_dict/atom_paths on entry,
    so a second copy via _snapshot_state is redundant.
    """
    state = {
        "position_table": result["position_table"],
        "channel_dict": result["channel_dict"],
        "atom_paths": result["atom_paths"],
    }
    if result.get("interact_info") is not None:
        state["interact_info"] = result["interact_info"]
    if result.get("block_orig_positions_by_block") is not None:
        state["block_orig_positions_by_block"] = result["block_orig_positions_by_block"]
    return state
