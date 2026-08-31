"""Single-block routing dispatch and result assembly helpers."""
from ..route import our_qucomm
from ..types import Plan, RoutingState

def _route_single_block(block, bid, agg_node, position_table, connectivity, channel_dict, atom_paths, interact_info, is_last, route_algo='our_qucomm', qucomm_forced_gate_meet_plan=None, candidate_eval_mode='active_chip_nodes', one_meet_tiebreak_mode='legacy_direct', enable_teleport_hybrid=False, disable_future_touch=False, print_debug=False):
    common = {'block_id': bid, 'block': block, 'position_table': position_table, 'connectivity': connectivity, 'aggregation_node': agg_node, 'channel_dict': channel_dict, 'atom_paths': atom_paths, 'interact_info': interact_info, 'is_last': is_last, 'physical_dep_check': False, 'PRINT_DEBUG': print_debug}
    return our_qucomm(**common, forced_gate_meet_plan=qucomm_forced_gate_meet_plan, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, enable_teleport_hybrid=enable_teleport_hybrid, disable_future_touch=disable_future_touch)

def _update_position_table(position_table, atom_paths):
    for (q, path) in atom_paths.items():
        if path:
            position_table[q] = path[-1]

def _build_plan(done_ids, done_aggs, position_table, channel_dict, atom_paths, total_relocates, total_recnots, total_releases, total_routing_cost, combined_schedule, per_block_info_list, per_block_metrics_list, interact_info, lookahead_debug_list):
    debug_rows = [] if lookahead_debug_list is None else lookahead_debug_list
    return Plan(done_ids=done_ids, aggs=done_aggs, state_after=RoutingState(position_table=position_table.copy(), channel_dict=channel_dict.copy(), atom_paths={k: list(v) for (k, v) in atom_paths.items()}), cost_reloc=total_relocates, cost_recnot=total_recnots, cost_cr=total_releases, routing_cost=total_routing_cost, combined_schedule=combined_schedule, per_block_info=per_block_info_list, per_block_metrics=per_block_metrics_list, use_swap_list=[], interact_info=interact_info, lookahead_debug=list(debug_rows))