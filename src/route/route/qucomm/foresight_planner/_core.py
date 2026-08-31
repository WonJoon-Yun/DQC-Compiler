from ....aggregation import compute_dynamic_agg
from ....cache import GraphCache
from ....gate_utils import normalize_block_to_gates
from ..gate_rollout_planner import DEFAULT_FUTURE_BLOCK_DECAY_MODE, DEFAULT_GATE_BEAM_PRUNE_MODE, DEFAULT_GATE_BEAM_WIDTH, DEFAULT_GATE_CANDIDATE_LIMIT, DEFAULT_GATE_LOOKAHEAD_SORT_MODE, _apply_guidance_sort_fields, _beam_sort_key, _candidate_nodes_for_mode, _diversity_prune_beam, _enumerate_gate_actions, _future_block_decay_weight, _future_specs_within_block_horizon, _iris_candidate_seed_target, _iris_guidance_step, _mapping_key, _resolve_block_agg, simulate_qucomm_gate_transition
from ._challenger import _resolve_exact_top_tie_with_deeper_horizon
from ._utils import _build_block_end_gate_indices, _copy_predicted_state, _flatten_all_gate_specs, _forced_plans_by_block_from_actions, _snapshot_state, _wrap_simulate_result

def _choose_qucomm_global_foresight_plan_opt1(*, blocks, aggs, block_ids, start_block_index, position_table, channel_dict, atom_paths, interact_info, connectivity, lookahead_depth, candidate_eval_mode='active_chip_nodes', one_meet_tiebreak_mode='legacy_direct', enable_teleport_hybrid=False, beam_width=DEFAULT_GATE_BEAM_WIDTH, candidate_limit=DEFAULT_GATE_CANDIDATE_LIMIT, iris_guidance=None, future_block_decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE, beam_prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE, block_levels=None, sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE, collect_debug=True, tie_refinement_remaining=2, disable_future_touch=False):
    gate_specs = _flatten_all_gate_specs(blocks, block_ids, start_block_index=start_block_index)
    if not gate_specs:
        return ({}, (), {'mode': 'empty'})
    initial_state = _snapshot_state(position_table, channel_dict, atom_paths, interact_info)
    beam = [{'state': initial_state, '_mk': _mapping_key(initial_state['position_table']), '_ak': (), 'actions': (), 'cost_vector': [], 'sort_cost_vector': [], 'sort_total_cost': 0.0, 'total_cost': 0.0, 'teleports': 0, 'recnots': 0, 'releases': 0, 'block_aggs': {}, 'prefix_states': {}, 'guidance_total_adjustment': 0.0, 'guidance_trace': ()}]
    window_block_depth = max(0, int(lookahead_depth))
    block_end_gate_indices = _build_block_end_gate_indices(gate_specs)
    _prefix_keep_indices = frozenset(block_end_gate_indices.values())
    for (depth, gate_spec) in enumerate(gate_specs):
        future_specs = _future_specs_within_block_horizon(gate_specs, depth, window_block_depth)
        future_gates = [spec['gate'] for spec in future_specs]
        routing_cost_weight = _future_block_decay_weight(start_block_index, gate_spec['block_index'], horizon_depth=window_block_depth, decay_mode=future_block_decay_mode, block_levels=block_levels)
        (s, t) = gate_spec['gate']
        active_qubits = {s, t}
        for spec in future_specs:
            (gs, gt) = spec['gate']
            active_qubits.add(gs)
            active_qubits.add(gt)
        (iris_seed_target_node, iris_seed_target_chip) = _iris_candidate_seed_target(iris_guidance, gate_spec)
        use_iris_candidate_seed = iris_seed_target_node is not None or iris_seed_target_chip is not None
        next_beam = []
        gcache = GraphCache(connectivity)
        for node in beam:
            state = node['state']
            block_agg = _resolve_block_agg(node, gate_spec, blocks=blocks, aggs=aggs, connectivity=connectivity, start_block_index=start_block_index)
            pos_s = state['position_table'][s]
            pos_t = state['position_table'][t]
            candidate_nodes = _candidate_nodes_for_mode(active_qubits, state['position_table'], connectivity, gcache, candidate_eval_mode)
            dyn_agg = compute_dynamic_agg((s, t), future_gates, state['position_table'], block_agg, connectivity, gcache, state['channel_dict'], PRINT_DEBUG=False, candidate_nodes=candidate_nodes)
            actions = _enumerate_gate_actions(s=s, t=t, pos_s=pos_s, pos_t=pos_t, dyn_agg=dyn_agg, future_gates=future_gates, qubit_positions=state['position_table'], active_qubits=active_qubits, connectivity=connectivity, gcache=gcache, channel_dict=state['channel_dict'], candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, candidate_limit=candidate_limit, iris_target_node=iris_seed_target_node, iris_target_chip=iris_seed_target_chip, use_iris_candidate_seed=use_iris_candidate_seed, disable_searchspace=False, disable_costfn=False, double_count_future_ops=False, disable_future_touch=disable_future_touch)
            for action in actions:
                result = simulate_qucomm_gate_transition(gate_spec=gate_spec, future_gate_specs=future_specs, state=state, connectivity=connectivity, aggregation_node=block_agg, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, enable_teleport_hybrid=enable_teleport_hybrid, forced_action=None if action['mode'] == 'baseline' else action, disable_searchspace=False, disable_costfn=False, double_count_future_ops=False, disable_future_touch=disable_future_touch)
                step_state = _wrap_simulate_result(result)
                guidance_step = _iris_guidance_step(iris_guidance=iris_guidance, gate_spec=gate_spec, active_qubits=active_qubits, result=result, step_state=step_state, gcache=gcache)
                cost_vector = list(node['cost_vector']) + [result['routing_cost'] * routing_cost_weight]
                new_actions = node['actions'] + ((gate_spec, result['selected_action']),)
                _sel = result['selected_action']
                new_ak = node.get('_ak', ()) + ((gate_spec['block_index'], gate_spec['local_gate_index'], _sel['mode'], _sel.get('meeting_node'), _sel.get('move_qubit')),)
                total_cv = round(sum(cost_vector), 8)
                child = {'state': step_state, '_mk': _mapping_key(step_state['position_table']), '_ak': new_ak, 'actions': new_actions, 'cost_vector': cost_vector, 'total_cost': total_cv, 'teleports': node['teleports'] + result['cost_reloc'] + result['cost_release'], 'recnots': node['recnots'] + result['cost_recnot'], 'releases': node['releases'] + result['cost_release'], 'block_aggs': dict(node['block_aggs']), 'prefix_states': {**node['prefix_states'], depth: step_state} if depth in _prefix_keep_indices else node['prefix_states'], 'guidance_total_adjustment': round(node.get('guidance_total_adjustment', 0.0) + guidance_step['total_adjustment'], 8), 'guidance_trace': node.get('guidance_trace', ()) + (guidance_step,)}
                _apply_guidance_sort_fields(child, list(cost_vector), child['total_cost'])
                next_beam.append(child)
        (beam, _prune_meta) = _diversity_prune_beam(next_beam, beam_width, sort_mode, prune_mode=beam_prune_mode)
    current_block_end_gate_index = block_end_gate_indices[start_block_index]
    (best, _ordered_beam, _exact_top_tie_debug) = _resolve_exact_top_tie_with_deeper_horizon(beam=beam, blocks=blocks, aggs=aggs, block_ids=block_ids, start_block_index=start_block_index, position_table=position_table, channel_dict=channel_dict, atom_paths=atom_paths, interact_info=interact_info, connectivity=connectivity, gate_specs=gate_specs, current_block_end_gate_index=current_block_end_gate_index, lookahead_depth=lookahead_depth, candidate_eval_mode=candidate_eval_mode, one_meet_tiebreak_mode=one_meet_tiebreak_mode, enable_teleport_hybrid=enable_teleport_hybrid, beam_width=beam_width, candidate_limit=candidate_limit, iris_guidance=iris_guidance, future_block_decay_mode=future_block_decay_mode, beam_prune_mode=beam_prune_mode, block_levels=block_levels, sort_mode=sort_mode, tie_refinement_remaining=tie_refinement_remaining, disable_future_touch=disable_future_touch, choose_plan_fn=choose_qucomm_global_foresight_plan, beam_sort_key=_beam_sort_key)
    forced_plans_by_block = _forced_plans_by_block_from_actions(best['actions'])
    predicted_block_end_states = {block_index: _copy_predicted_state(best['prefix_states'][end_gate_index]) for (block_index, end_gate_index) in block_end_gate_indices.items() if end_gate_index in best.get('prefix_states', {})}
    meta = {'mode': 'global_foresight_solution_tree', 'total_cost': round(best.get('sort_total_cost', best['total_cost']), 8), 'iris_guidance_enabled': bool(iris_guidance), 'predicted_block_end_states': predicted_block_end_states}
    return (forced_plans_by_block, tuple(best['cost_vector']), meta)

def choose_qucomm_global_foresight_plan(*, blocks, aggs, block_ids, start_block_index, position_table, channel_dict, atom_paths, interact_info=None, connectivity, lookahead_depth, candidate_eval_mode='active_chip_nodes', one_meet_tiebreak_mode='legacy_direct', enable_teleport_hybrid=False, beam_width=DEFAULT_GATE_BEAM_WIDTH, candidate_limit=DEFAULT_GATE_CANDIDATE_LIMIT, planning_option='opt0', iris_guidance=None, future_block_decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE, beam_prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE, block_levels=None, sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE, collect_debug=True, tie_refinement_remaining=2, disable_future_touch=False):
    option = str(planning_option).lower()
    common = {'blocks': blocks, 'aggs': aggs, 'block_ids': block_ids, 'start_block_index': start_block_index, 'position_table': position_table, 'channel_dict': channel_dict, 'atom_paths': atom_paths, 'interact_info': interact_info, 'connectivity': connectivity, 'lookahead_depth': lookahead_depth, 'candidate_eval_mode': candidate_eval_mode, 'one_meet_tiebreak_mode': one_meet_tiebreak_mode, 'enable_teleport_hybrid': enable_teleport_hybrid, 'beam_width': beam_width, 'candidate_limit': candidate_limit, 'iris_guidance': iris_guidance, 'future_block_decay_mode': future_block_decay_mode, 'beam_prune_mode': beam_prune_mode, 'block_levels': block_levels, 'sort_mode': sort_mode, 'collect_debug': collect_debug, 'tie_refinement_remaining': tie_refinement_remaining, 'disable_future_touch': disable_future_touch}
    if option == 'opt1':
        return _choose_qucomm_global_foresight_plan_opt1(**common)
    raise ValueError(f'Unknown QuComm gate lookahead planning option: {planning_option}')
