from ..common import CANDIDATE_EVAL_MODE_ACTIVE_CHIPS, CANDIDATE_EVAL_MODES, MAX_MOVE_ROUNDS, ONE_MEET_TIEBREAK_LEGACY_DIRECT, ONE_MEET_TIEBREAK_MODES, GraphCache, _build_output, _candidate_nodes_for_mode, _execute_one_meet, _gate_progress_state_key, _handle_post_gate_interact, _hybrid_one_meet_cost, _predicted_one_meet_state_key, _record_gate_execution, _resolve_no_path, _sync_active_positions, _teleport_action_matches_option, _teleport_option_sort_key, _validate_atom_paths, _validate_inputs, assert_channel_invariant, channel_snapshot, compute_dynamic_agg, dbg, enumerate_one_sided_meet_candidates, evaluate_teleport_options, execute_teleport, find_best_one_sided_meet, init_interact_info, normalize_block_to_gates

def our_qucomm(block_id, block, position_table, connectivity, aggregation_node, channel_dict, atom_paths, interact_info=None, is_last=False, physical_dep_check=False, PRINT_DEBUG=False, forced_gate_meet_plan=None, enable_reorder=False, reorder_lookahead_depth=8, candidate_eval_mode=CANDIDATE_EVAL_MODE_ACTIVE_CHIPS, one_meet_tiebreak_mode=ONE_MEET_TIEBREAK_LEGACY_DIRECT, enable_teleport_hybrid=False, disable_future_touch=False):
    ALGO = 'our_qucomm'
    gcache = GraphCache(connectivity)
    gates = normalize_block_to_gates(block)
    active_qubits = set()
    for (s, t) in gates:
        active_qubits.add(s)
        active_qubits.add(t)
    position_table = position_table.copy()
    qubit_positions = {q: position_table[q] for q in active_qubits}
    orig_positions = qubit_positions.copy()
    initial_position_table = position_table.copy()
    initial_channel_dict = channel_snapshot(channel_dict)
    initial_atom_paths = {k: list(v) for (k, v) in atom_paths.items()}
    _validate_inputs(active_qubits, qubit_positions, aggregation_node, gates, connectivity, channel_dict, gcache)
    ii = init_interact_info(interact_info, PRINT_DEBUG=False)
    evict_ii = ii
    if candidate_eval_mode not in CANDIDATE_EVAL_MODES:
        raise ValueError(f'Invalid candidate_eval_mode={candidate_eval_mode}. Expected one of {CANDIDATE_EVAL_MODES}')
    if one_meet_tiebreak_mode not in ONE_MEET_TIEBREAK_MODES:
        raise ValueError(f'Invalid one_meet_tiebreak_mode={one_meet_tiebreak_mode}. Expected one of {ONE_MEET_TIEBREAK_MODES}')
    if PRINT_DEBUG:
        dbg.block_start(ALGO, block_id, len(gates), active_qubits, aggregation_node, qubit_positions, channel_dict)
        print(f'  [CONFIG] candidate_eval_mode={candidate_eval_mode}')
        print(f'  [CONFIG] one_meet_tiebreak_mode={one_meet_tiebreak_mode}')
        print(f'  [CONFIG] enable_teleport_hybrid={enable_teleport_hybrid}')
        print(f'  [CONFIG] forced_gate_meet_plan={sorted((forced_gate_meet_plan or {}).keys())}')
        if forced_gate_meet_plan:
            print(f'  [CONFIG] forced_gate_meet_plan_detail={forced_gate_meet_plan}')
        if ii is not None:
            interact_info_mode = 'enabled'
        elif evict_ii is not None:
            interact_info_mode = 'evict-only'
        else:
            interact_info_mode = 'none'
        print(f'  [CONFIG] interact_info={interact_info_mode}')
    executed_gate_locations = []
    executed_gate_types = []
    position_timeline = []
    gate_timeline = []
    num_relocates = 0
    num_epr_release = 0
    relocates_per_gate = []
    recnot_flags = []
    op_log = []
    evict_cooldown = {}
    all_released_qubits = set()
    for (gate_idx, (s, t)) in enumerate(gates):
        future_gates = gates[gate_idx + 1:]
        gate_relocates = 0
        gate_start_pos_s = qubit_positions[s]
        gate_start_pos_t = qubit_positions[t]
        seen_gate_states = set()
        chip_candidate_nodes = _candidate_nodes_for_mode(active_qubits, qubit_positions, connectivity, gcache, candidate_eval_mode)
        dyn_agg = compute_dynamic_agg((s, t), future_gates, qubit_positions, aggregation_node, connectivity, gcache, channel_dict, PRINT_DEBUG=False, candidate_nodes=chip_candidate_nodes)
        move_round = 0
        while qubit_positions[s] != qubit_positions[t]:
            move_round += 1
            assert move_round <= MAX_MOVE_ROUNDS
            (pos_s, pos_t) = (qubit_positions[s], qubit_positions[t])
            assert pos_s in connectivity.nodes
            assert pos_t in connectivity.nodes
            assert gcache.sp_len(pos_s, pos_t) is not None
            position_timeline.append({q: qubit_positions[q] for q in sorted(active_qubits)})
            chip_candidate_nodes = _candidate_nodes_for_mode(active_qubits, qubit_positions, connectivity, gcache, candidate_eval_mode)
            dyn_agg = compute_dynamic_agg((s, t), future_gates, qubit_positions, aggregation_node, connectivity, gcache, channel_dict, PRINT_DEBUG=False, candidate_nodes=chip_candidate_nodes)
            current_state_key = _gate_progress_state_key(active_qubits, qubit_positions, channel_dict)
            repeated_state = current_state_key in seen_gate_states
            seen_gate_states.add(current_state_key)
            mp = None
            forced_mp = None
            forced_action = None
            forced_teleport_match = False
            if not repeated_state:
                if forced_gate_meet_plan and gate_idx in forced_gate_meet_plan:
                    forced_action = forced_gate_meet_plan[gate_idx]
                if forced_action is not None:
                    if forced_action.get('mode') == 'one_meet':
                        for cand in enumerate_one_sided_meet_candidates(pos_s, pos_t, s, t, future_gates, qubit_positions, dyn_agg=dyn_agg, ch=channel_dict, gcache=gcache, candidate_nodes=chip_candidate_nodes, tiebreak_mode=one_meet_tiebreak_mode, disable_future_touch=disable_future_touch, PRINT_DEBUG=False):
                            if cand['meeting_node'] == forced_action.get('meeting_node') and cand['move_qubit'] == forced_action.get('move_qubit'):
                                predicted_state_key = _predicted_one_meet_state_key(cand, active_qubits, qubit_positions, channel_dict)
                                if predicted_state_key not in seen_gate_states:
                                    forced_mp = cand
                                break
                mp = find_best_one_sided_meet(pos_s, pos_t, s, t, future_gates, qubit_positions, dyn_agg=dyn_agg, ch=channel_dict, gcache=gcache, candidate_nodes=chip_candidate_nodes, tiebreak_mode=one_meet_tiebreak_mode, disable_future_touch=disable_future_touch, PRINT_DEBUG=PRINT_DEBUG) if forced_mp is None else forced_mp
                if mp is not None:
                    predicted_state_key = _predicted_one_meet_state_key(mp, active_qubits, qubit_positions, channel_dict)
                    if predicted_state_key in seen_gate_states:
                        mp = None
            elif PRINT_DEBUG:
                print(f'  [STALL] gate={gate_idx} repeated gate state detected; switching to recovery')
            teleport_choice = None
            if not repeated_state:
                tp_opts = evaluate_teleport_options(s, t, pos_s, pos_t, qubit_positions, active_qubits, future_gates, channel_dict, gcache)
                if tp_opts:
                    tp_opts = sorted(tp_opts, key=_teleport_option_sort_key)
                    if forced_action and forced_action.get('mode') == 'teleport':
                        for opt in tp_opts:
                            if _teleport_action_matches_option(forced_action, opt):
                                teleport_choice = opt
                                forced_teleport_match = True
                                break
                    if teleport_choice is None:
                        teleport_choice = tp_opts[0]
                    if PRINT_DEBUG:
                        cands = [(l, f'{c:.1f}') for (c, l, _) in tp_opts]
                        dbg.strategy_candidates(gate_idx, cands)
            use_teleport = False
            if forced_action and forced_action.get('mode') == 'teleport' and forced_teleport_match:
                use_teleport = forced_teleport_match
            elif forced_mp is None and teleport_choice is not None and (mp is not None):
                tp_cost = teleport_choice[0]
                om_cost = _hybrid_one_meet_cost(mp, False)
                use_teleport = tp_cost < om_cost
            elif forced_mp is None and teleport_choice is not None:
                use_teleport = True
            if use_teleport:
                (best_cost, best_label, best_info) = teleport_choice
                hops = execute_teleport(best_label, best_info, s, t, pos_s, pos_t, gate_idx, connectivity, channel_dict, qubit_positions, atom_paths, active_qubits, position_timeline, gate_timeline, op_log, gcache, PRINT_DEBUG=PRINT_DEBUG)
                num_relocates += hops
                gate_relocates += hops
                _sync_active_positions(position_table, qubit_positions, active_qubits)
            elif mp is not None:
                (num_relocates, gate_relocates) = _execute_one_meet(gate_idx, mp, mp['move_qubit'], connectivity, channel_dict, qubit_positions, position_table, atom_paths, active_qubits, num_relocates, gate_relocates, op_log, gate_timeline, position_timeline, PRINT_DEBUG)
            else:
                (progressed, num_relocates, gate_relocates, num_epr_release) = _resolve_no_path(gate_idx, s, t, future_gates, dyn_agg, connectivity, channel_dict, position_table, qubit_positions, atom_paths, active_qubits, evict_cooldown, move_round, ii, gcache, num_relocates, gate_relocates, num_epr_release, op_log, gate_timeline, position_timeline, PRINT_DEBUG)
                assert progressed, f'[DEADLOCK] gate {gate_idx} ({s},{t})'
            assert_channel_invariant(channel_dict, context=f'round {move_round} gate {gate_idx}')
        _record_gate_execution(s, t, gate_idx, gate_start_pos_s, gate_start_pos_t, qubit_positions, orig_positions, active_qubits, connectivity, channel_dict, position_timeline, gate_timeline, executed_gate_locations, executed_gate_types, relocates_per_gate, recnot_flags, gate_relocates, PRINT_DEBUG)
        if ii is not None:
            (num_relocates, gate_relocates) = _handle_post_gate_interact(ii, s, t, gate_idx, future_gates, qubit_positions, position_table, atom_paths, active_qubits, connectivity, channel_dict, gcache, num_relocates, gate_relocates, relocates_per_gate, all_released_qubits, op_log, gate_timeline, position_timeline, PRINT_DEBUG)
    num_return_relocates = 0
    _validate_atom_paths(active_qubits, atom_paths, connectivity)
    returned_interact_info = interact_info
    return _build_output(ALGO, gates, active_qubits, qubit_positions, position_timeline, gate_timeline, block_id, recnot_flags, relocates_per_gate, num_relocates, num_epr_release, num_return_relocates, atom_paths, channel_dict, op_log, ii, returned_interact_info, all_released_qubits, connectivity, initial_position_table, position_table, initial_channel_dict, initial_atom_paths, atom_paths, PRINT_DEBUG)
route_v5 = our_qucomm