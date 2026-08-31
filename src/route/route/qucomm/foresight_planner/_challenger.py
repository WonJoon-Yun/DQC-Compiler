from ._utils import _beam_sort_key_without_action_tuple, _current_block_forced_signature_from_node, _current_block_forced_signature_from_plan

def _resolve_exact_top_tie_with_deeper_horizon(*, beam, blocks, aggs, block_ids, start_block_index, position_table, channel_dict, atom_paths, interact_info, connectivity, gate_specs, current_block_end_gate_index, lookahead_depth, candidate_eval_mode, one_meet_tiebreak_mode, enable_teleport_hybrid, beam_width, candidate_limit, iris_guidance, future_block_decay_mode, beam_prune_mode, block_levels, sort_mode, tie_refinement_remaining, choose_plan_fn, beam_sort_key, disable_future_touch=False):
    ordered_beam = sorted(beam, key=lambda node: beam_sort_key(node, sort_mode))
    best = ordered_beam[0]
    if tie_refinement_remaining <= 0:
        return (best, ordered_beam, None)
    top_numeric_key = _beam_sort_key_without_action_tuple(best, sort_mode)
    tied_nodes = [node for node in ordered_beam if _beam_sort_key_without_action_tuple(node, sort_mode) == top_numeric_key]
    if len(tied_nodes) <= 1:
        return (best, ordered_beam, None)
    signature_to_nodes = {}
    for node in tied_nodes:
        signature = _current_block_forced_signature_from_node(node, gate_specs, current_block_end_gate_index, start_block_index)
        signature_to_nodes.setdefault(signature, []).append(node)
    if len(signature_to_nodes) <= 1:
        return (best, ordered_beam, None)
    target_depth = max(0, int(lookahead_depth)) + 1
    (deeper_forced_plans, _deeper_score, _deeper_meta) = choose_plan_fn(blocks=blocks, aggs=aggs, block_ids=block_ids, start_block_index=start_block_index, position_table=position_table, channel_dict=channel_dict, atom_paths=atom_paths, interact_info=interact_info, connectivity=connectivity, lookahead_depth=target_depth, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, enable_teleport_hybrid=enable_teleport_hybrid, beam_width=beam_width, candidate_limit=candidate_limit, planning_option='opt1', iris_guidance=iris_guidance, future_block_decay_mode=future_block_decay_mode, beam_prune_mode=beam_prune_mode, block_levels=block_levels, sort_mode=sort_mode, collect_debug=False, tie_refinement_remaining=tie_refinement_remaining - 1, disable_future_touch=disable_future_touch)
    deeper_signature = _current_block_forced_signature_from_plan(deeper_forced_plans.get(start_block_index, {}))
    matched_nodes = signature_to_nodes.get(deeper_signature)
    if not matched_nodes:
        return (best, ordered_beam, None)
    refined_best = sorted(matched_nodes, key=lambda node: beam_sort_key(node, sort_mode))[0]
    return (refined_best, ordered_beam, None)
