from ._constants import DEFAULT_GATE_BEAM_PRUNE_MODE, DEFAULT_GATE_LOOKAHEAD_SORT_MODE, _normalize_beam_prune_mode
from ._state import _mapping_key
from ._constants import DIRECT_TIE_EXACT_REFINEMENT_BEAM_WIDTH
from ._constants import DIRECT_TIE_EXACT_REFINEMENT_CANDIDATE_LIMIT
from ._constants import GENERAL_EXACT_SUFFIX_REFINEMENT_LOCAL_GATE_LIMIT
from ._constants import GENERAL_EXACT_SUFFIX_REFINEMENT_MAX_ACTIONS
from ._constants import GENERAL_EXACT_SUFFIX_REFINEMENT_PROXY_MARGIN
from ._constants import MAX_EXACT_TIE_SUFFIX_REFINEMENT_DEPTH
from ._guidance import _apply_guidance_sort_fields
from ._state import _build_exact_suffix_rollout_window

def _beam_action_tuple(node):
    return node.get('_ak') or tuple(((spec['block_index'], spec['local_gate_index'], action['mode'], action.get('meeting_node'), action.get('move_qubit')) for (spec, action) in node['actions']))

def _beam_sort_key(node, sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE):
    current_block_total_cost = node.get('current_block_total_cost', node.get('sort_total_cost', node['total_cost']))
    total_cost = node.get('sort_total_cost', node['total_cost'])
    sort_cost_vector = node.get('sort_cost_vector', node.get('objective_cost_vector', node['cost_vector']))
    leading_costs = (round(current_block_total_cost, 8), round(total_cost, 8))
    return (*leading_costs, node['recnots'], node['teleports'], node['releases'], tuple((round(v, 8) for v in sort_cost_vector)), _beam_action_tuple(node))

def _beam_prune_key(node, prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE, sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE):
    mode = _normalize_beam_prune_mode(prune_mode)
    if mode == 'scheduled_prefix_cost':
        return (round(float(node.get('prune_prefix_cost', 0.0)), 8), _beam_action_tuple(node))
    if mode == 'current_teleports_only':
        return (int(node.get('teleports', 0)), _beam_action_tuple(node))
    if mode == 'selection_plus_current_teleports':
        selection_total = round(float(node.get('sort_total_cost', node['total_cost'])), 8)
        current_teleports = int(node.get('teleports', 0))
        return (round(selection_total + current_teleports, 8), selection_total, current_teleports, _beam_action_tuple(node))
    return _beam_sort_key(node, sort_mode)

def _diversity_prune_beam(next_beam, beam_width, sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE, prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE):
    width = max(1, int(beam_width))
    normalized_prune_mode = _normalize_beam_prune_mode(prune_mode)
    if len(next_beam) <= width:
        return (sorted(next_beam, key=lambda node: _beam_sort_key(node, sort_mode)), {'raw_candidates': len(next_beam), 'unique_mappings': len({node.get('_mk') or _mapping_key(node['state']['position_table']) for node in next_beam}), 'prune_mode': normalized_prune_mode})
    buckets = {}
    for node in next_beam:
        buckets.setdefault(node.get('_mk') or _mapping_key(node['state']['position_table']), []).append(node)
    primary = []
    overflow = []
    for bucket in buckets.values():
        bucket.sort(key=lambda node: _beam_prune_key(node, normalized_prune_mode, sort_mode))
        primary.append(bucket[0])
        overflow.extend(bucket[1:])
    primary.sort(key=lambda node: _beam_prune_key(node, normalized_prune_mode, sort_mode))
    overflow.sort(key=lambda node: _beam_prune_key(node, normalized_prune_mode, sort_mode))
    pruned = list(primary[:width])
    if len(pruned) < width:
        for node in overflow:
            if len(pruned) >= width:
                break
            pruned.append(node)
    pruned.sort(key=lambda node: _beam_sort_key(node, sort_mode))
    return (pruned, {'raw_candidates': len(next_beam), 'unique_mappings': len(buckets), 'prune_mode': normalized_prune_mode})

def _apply_exact_suffix_refinement_to_children(
    *,
    children,
    gate_spec,
    blocks,
    aggs,
    block_ids,
    block_index,
    connectivity,
    lookahead_depth,
    candidate_eval_mode,
    one_meet_tiebreak_mode,
    disable_searchspace,
    disable_costfn,
    disable_future_touch,
    enable_teleport_hybrid,
    double_count_future_ops,
    beam_width,
    candidate_limit,
    direct_ab_tie_keys,
    sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE,
):
    exact_refine_depth = min(
        max(0, int(lookahead_depth)),
        MAX_EXACT_TIE_SUFFIX_REFINEMENT_DEPTH,
    )
    if exact_refine_depth <= 0:
        return

    refine_indices = _exact_suffix_refinement_indices(
        children,
        gate_spec,
        direct_ab_tie_keys,
        sort_mode,
    )
    if not refine_indices:
        return

    for idx in refine_indices:
        child = children[idx]
        selected_action_key = child.get("selected_action_key")
        refine_fn = _exact_action_suffix_total
        if selected_action_key is not None and selected_action_key in direct_ab_tie_keys:
            refine_fn = _exact_direct_ab_tie_suffix_total
        refined_suffix_total = refine_fn(
            blocks=blocks,
            aggs=aggs,
            block_ids=block_ids,
            block_index=block_index,
            gate_spec=gate_spec,
            state=child["state"],
            connectivity=connectivity,
            lookahead_depth=exact_refine_depth,
            candidate_eval_mode=candidate_eval_mode,
            one_meet_tiebreak_mode=one_meet_tiebreak_mode,
            disable_searchspace=disable_searchspace,
            disable_costfn=disable_costfn,
            disable_future_touch=disable_future_touch,
            enable_teleport_hybrid=enable_teleport_hybrid,
            double_count_future_ops=double_count_future_ops,
            beam_width=beam_width,
            candidate_limit=candidate_limit,
        )
        _apply_guidance_sort_fields(
            child,
            list(child["cost_vector"]) + [refined_suffix_total],
            sum(child["cost_vector"]) + refined_suffix_total,
        )
        child["exact_suffix_refined"] = True
        child["exact_suffix_total"] = refined_suffix_total


def _exact_action_suffix_total(
    *,
    blocks,
    aggs,
    block_ids,
    block_index,
    gate_spec,
    state,
    connectivity,
    lookahead_depth,
    candidate_eval_mode,
    one_meet_tiebreak_mode,
    disable_searchspace,
    disable_costfn,
    disable_future_touch,
    enable_teleport_hybrid,
    double_count_future_ops,
    beam_width,
    candidate_limit,
):
    suffix_blocks, suffix_aggs, suffix_block_ids = _build_exact_suffix_rollout_window(
        blocks=blocks,
        aggs=aggs,
        block_ids=block_ids,
        block_index=block_index,
        local_gate_index=gate_spec["local_gate_index"],
        lookahead_depth=lookahead_depth,
    )
    if not suffix_blocks:
        return 0.0

    suffix_lookahead_depth = max(0, len(suffix_blocks) - 1)
    refine_beam_width = min(
        max(1, int(beam_width)),
        DIRECT_TIE_EXACT_REFINEMENT_BEAM_WIDTH,
    )
    refine_candidate_limit = min(
        max(1, int(candidate_limit)),
        DIRECT_TIE_EXACT_REFINEMENT_CANDIDATE_LIMIT,
    )

    # Deferred import to break circular dependency with _planners module.
    from ._planners import choose_qucomm_gate_rollout_plan

    _forced_plan, score, _meta = choose_qucomm_gate_rollout_plan(
        blocks=suffix_blocks,
        aggs=suffix_aggs,
        block_ids=suffix_block_ids,
        block_index=0,
        position_table=state["position_table"],
        channel_dict=state["channel_dict"],
        atom_paths=state["atom_paths"],
        interact_info=state.get("interact_info"),
        connectivity=connectivity,
        lookahead_depth=suffix_lookahead_depth,
        candidate_eval_mode=candidate_eval_mode,
        one_meet_tiebreak_mode=one_meet_tiebreak_mode,
        disable_searchspace=disable_searchspace,
        disable_costfn=disable_costfn,
        disable_future_touch=disable_future_touch,
        enable_teleport_hybrid=enable_teleport_hybrid,
        double_count_future_ops=double_count_future_ops,
        beam_width=refine_beam_width,
        candidate_limit=refine_candidate_limit,
        enable_foresight=False,
        planning_option="opt1",
        collect_debug=False,
    )
    return sum(score)


def _exact_direct_ab_tie_suffix_total(**kwargs):
    return _exact_action_suffix_total(**kwargs)


def _exact_suffix_refinement_indices(
    children,
    gate_spec,
    direct_ab_tie_keys,
    sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE,
):
    if not children:
        return []

    refine_indices = set()
    if len(children) <= 1 and not direct_ab_tie_keys:
        return []
    early_gate = gate_spec["local_gate_index"] < GENERAL_EXACT_SUFFIX_REFINEMENT_LOCAL_GATE_LIMIT

    if early_gate:
        proxy_order = sorted(
            range(len(children)),
            key=lambda idx: _beam_sort_key(children[idx], sort_mode),
        )
        best_proxy_total = children[proxy_order[0]].get(
            "proxy_total_cost",
            children[proxy_order[0]].get("sort_total_cost", children[proxy_order[0]]["total_cost"]),
        )
        for rank, idx in enumerate(proxy_order):
            proxy_total = children[idx].get(
                "proxy_total_cost",
                children[idx].get("sort_total_cost", children[idx]["total_cost"]),
            )
            if rank < GENERAL_EXACT_SUFFIX_REFINEMENT_MAX_ACTIONS:
                refine_indices.add(idx)
                continue
            if proxy_total - best_proxy_total <= GENERAL_EXACT_SUFFIX_REFINEMENT_PROXY_MARGIN:
                refine_indices.add(idx)

    for idx, child in enumerate(children):
        selected_action_key = child.get("selected_action_key")
        if selected_action_key is not None and selected_action_key in direct_ab_tie_keys:
            refine_indices.add(idx)

    return sorted(refine_indices)
