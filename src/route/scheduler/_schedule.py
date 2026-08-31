"""Main schedule_blocks entry point."""
from ..classify import classify_qubits
from ..constants import compute_routing_cost
from ..route.qucomm import choose_qucomm_gate_rollout_plan, choose_qucomm_global_foresight_plan
from ..types import PerBlockInfo, PerBlockMetrics
from ._routing import _build_plan, _route_single_block, _update_position_table
from ._validators import _validate_aggregate, _validate_block, _validate_route_result, _validate_scheduler_inputs

def schedule_blocks(blocks, aggs, block_ids, start_state, connectivity, K, block_levels=None, interact_info=None, route_algo='our_qucomm', qucomm_enable_gate_lookahead=False, qucomm_gate_lookahead_depth=0, qucomm_gate_lookahead_beam_width=16, qucomm_gate_lookahead_option='opt0', qucomm_gate_lookahead_sort_mode='current_then_total', qucomm_gate_lookahead_prune_mode='scheduled_prefix_cost', qucomm_future_block_decay_mode='linear', qucomm_enable_gate_foresight=False, save_qucomm_block_lookahead_debug=True, print_debug=False, candidate_eval_mode='active_chip_nodes', one_meet_tiebreak_mode='legacy_direct', enable_teleport_hybrid=False, disable_future_touch=False):
    """Process up to K blocks sequentially."""
    n_blocks = min(K, len(blocks))
    _validate_scheduler_inputs(n_blocks, blocks, aggs, block_ids, block_levels)
    position_table = start_state.position_table.copy()
    channel_dict = start_state.channel_dict.copy()
    atom_paths = {k: list(v) for (k, v) in start_state.atom_paths.items()}
    total_relocates = 0
    total_recnots = 0
    total_releases = 0
    total_routing_cost = 0.0
    combined_schedule = []
    per_block_info_list = []
    per_block_metrics_list = []
    done_ids = []
    done_aggs = []
    capture_lookahead_debug = False
    lookahead_debug_list = None
    foresight_global_plans = {}
    foresight_global_meta = None
    if route_algo == 'our_qucomm' and qucomm_enable_gate_lookahead and (qucomm_gate_lookahead_depth > 0) and qucomm_enable_gate_foresight:
        (foresight_global_plans, _, foresight_global_meta) = choose_qucomm_global_foresight_plan(blocks=blocks, aggs=aggs, block_ids=block_ids, start_block_index=0, position_table=position_table, channel_dict=channel_dict, atom_paths=atom_paths, interact_info=interact_info, connectivity=connectivity, lookahead_depth=qucomm_gate_lookahead_depth, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, enable_teleport_hybrid=enable_teleport_hybrid, beam_width=qucomm_gate_lookahead_beam_width, planning_option=qucomm_gate_lookahead_option, sort_mode=qucomm_gate_lookahead_sort_mode, beam_prune_mode=qucomm_gate_lookahead_prune_mode, future_block_decay_mode=qucomm_future_block_decay_mode, block_levels=block_levels, collect_debug=capture_lookahead_debug, disable_future_touch=disable_future_touch)
        if print_debug:
            print(f"[schedule_blocks] QuComm global foresight depth={qucomm_gate_lookahead_depth} beam={qucomm_gate_lookahead_beam_width} option={qucomm_gate_lookahead_option} sort={qucomm_gate_lookahead_sort_mode} decay={qucomm_future_block_decay_mode} total_cost={foresight_global_meta.get('total_cost')}")
    for i in range(n_blocks):
        block = blocks[i]
        agg_node = aggs[i]
        bid = block_ids[i]
        forced_gate_meet_plan = None
        if route_algo == 'our_qucomm' and qucomm_enable_gate_lookahead and (qucomm_gate_lookahead_depth > 0):
            if qucomm_enable_gate_foresight:
                forced_gate_meet_plan = dict(foresight_global_plans.get(i, {}))
            else:
                (forced_gate_meet_plan, _gate_score, _gate_meta) = choose_qucomm_gate_rollout_plan(blocks=blocks, aggs=aggs, block_ids=block_ids, block_index=i, position_table=position_table, channel_dict=channel_dict, atom_paths=atom_paths, interact_info=interact_info, connectivity=connectivity, lookahead_depth=qucomm_gate_lookahead_depth, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, disable_future_touch=disable_future_touch, enable_teleport_hybrid=enable_teleport_hybrid, beam_width=qucomm_gate_lookahead_beam_width, enable_foresight=False, planning_option=qucomm_gate_lookahead_option, sort_mode=qucomm_gate_lookahead_sort_mode, beam_prune_mode=qucomm_gate_lookahead_prune_mode, future_block_decay_mode=qucomm_future_block_decay_mode, block_levels=block_levels, collect_debug=capture_lookahead_debug)
        _validate_block(block, bid, i, agg_node, connectivity)
        if print_debug:
            print(f'\n[schedule_blocks] Processing block {bid} ({i + 1}/{n_blocks}), gates={len(block)}, agg={agg_node}')
        (num_internal, num_external) = classify_qubits(block, position_table, connectivity, agg_node)
        result = _route_single_block(block, bid, agg_node, position_table, connectivity, channel_dict, atom_paths, interact_info, is_last=i == n_blocks - 1, route_algo=route_algo, qucomm_forced_gate_meet_plan=forced_gate_meet_plan, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, enable_teleport_hybrid=enable_teleport_hybrid, disable_future_touch=disable_future_touch, print_debug=print_debug)
        (detailed_rows, atom_paths, channel_dict, num_relocates, num_recnots, num_epr_release, interact_info) = result
        _validate_route_result(detailed_rows, channel_dict, num_relocates, num_recnots, num_epr_release, bid)
        routing_cost = compute_routing_cost(num_relocates, num_recnots, num_epr_release)
        _update_position_table(position_table, atom_paths)
        if qucomm_enable_gate_foresight and foresight_global_meta is not None:
            predicted_states = foresight_global_meta.get('predicted_block_end_states', {})
            predicted = predicted_states.get(i)
            if predicted is not None:
                position_table.update(predicted['position_table'])
                channel_dict.clear()
                channel_dict.update(predicted['channel_dict'])
                for q in predicted['atom_paths']:
                    atom_paths[q] = list(predicted['atom_paths'][q])
        total_relocates += num_relocates
        total_recnots += num_recnots
        total_releases += num_epr_release
        total_routing_cost += routing_cost
        combined_schedule.append(detailed_rows)
        done_ids.append(bid)
        done_aggs.append(agg_node)
        per_block_info_list.append(PerBlockInfo(num_external_qubits=num_external, num_internal_qubits=num_internal, channel_dict=channel_dict.copy()))
        per_block_metrics_list.append(PerBlockMetrics(relocates=num_relocates, recnots=num_recnots, releases=num_epr_release))
        if print_debug:
            print(f'  Block {bid} done: relocates={num_relocates}, recnots={num_recnots}, epr_release={num_epr_release}, cost={routing_cost:.4f}')
    _validate_aggregate(done_ids, n_blocks, per_block_metrics_list, total_relocates, total_recnots, total_releases, channel_dict, combined_schedule)
    plan = _build_plan(done_ids, done_aggs, position_table, channel_dict, atom_paths, total_relocates, total_recnots, total_releases, total_routing_cost, combined_schedule, per_block_info_list, per_block_metrics_list, interact_info, lookahead_debug_list)
    if print_debug:
        print('\n[schedule_blocks SUMMARY]')
        print(f'  Blocks processed: {n_blocks}')
        print(f'  Total relocates:  {total_relocates}')
        print(f'  Total recnots:    {total_recnots}')
        print(f'  Total epr_release:{total_releases}')
        print(f'  Total cost:       {total_routing_cost:.4f}')
    return plan