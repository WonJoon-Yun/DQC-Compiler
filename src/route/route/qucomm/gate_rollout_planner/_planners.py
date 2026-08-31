from ....aggregation import compute_dynamic_agg
from ....cache import GraphCache
from ....constants import compute_routing_cost
from ....interact import init_interact_info
from ...common import _candidate_nodes_for_mode, _execute_one_meet, _gate_progress_state_key, _handle_post_gate_interact, _hybrid_one_meet_cost, _predicted_one_meet_state_key, _record_gate_execution, _resolve_no_path, _sync_active_positions, _teleport_action_from_option, _teleport_action_matches_option, _teleport_option_sort_key, assert_channel_invariant, enumerate_one_sided_meet_candidates, evaluate_teleport_options, execute_teleport, find_best_one_sided_meet
from ..lookahead import _node_chip_key
from ._state import _build_gate_interact_info, _candidate_key, _forced_action_to_key
from ._constants import DEFAULT_FUTURE_BLOCK_DECAY_MODE
from ._constants import DEFAULT_GATE_BEAM_PRUNE_MODE
from ._constants import DEFAULT_GATE_BEAM_WIDTH
from ._constants import DEFAULT_GATE_CANDIDATE_LIMIT
from ._constants import DEFAULT_GATE_LOOKAHEAD_SORT_MODE
from ._constants import FUTURE_BLOCK_DECAY_TARGET_DISTANCE
from ._constants import FUTURE_BLOCK_DECAY_TARGET_WEIGHT
from ._constants import FUTURE_BLOCK_EXTRA_DECAY_PER_BLOCK
from ._constants import FUTURE_BLOCK_EXTRA_DECAY_START_DISTANCE
from ._constants import GENERAL_EXACT_SUFFIX_REFINEMENT_LOCAL_GATE_LIMIT
from ._constants import GENERAL_EXACT_SUFFIX_REFINEMENT_MAX_ACTIONS
from ._constants import GENERAL_EXACT_SUFFIX_REFINEMENT_PROXY_MARGIN
from ._constants import IRIS_GUIDANCE_RESIDENCY_WEIGHT
from ._constants import IRIS_GUIDANCE_TARGET_DISTANCE_WEIGHT
from ._beam import _apply_exact_suffix_refinement_to_children
from ._guidance import _apply_guidance_sort_fields
from ._beam import _beam_prune_key
from ._beam import _beam_sort_key
import copy as _copy
from ._guidance import _critical_future_block_step
from ._beam import _diversity_prune_beam
from ._constants import _effective_future_proxy_depth
from ._state import _estimate_future_block_suffix
from ._state import _flatten_gate_window
from ._guidance import _future_block_alignment_risk_summary
from ._constants import _future_block_decay_weight
from ._guidance import _iris_candidate_seed_target
from ._guidance import _iris_guidance_step
from ._state import _mapping_key
from ._guidance import _preserve_objective_tie_sort_fields
from ._state import _resolve_block_agg
from ._constants import _rollout_window_upper
from ._state import _same_block_future_specs
from ._state import _wrap_simulate_result
from ...common import equivalent_direct_ab_tie_action_keys

def _enumerate_gate_actions(
    *,
    s,
    t,
    pos_s,
    pos_t,
    dyn_agg,
    future_gates,
    qubit_positions,
    active_qubits,
    connectivity,
    gcache,
    channel_dict,
    candidate_eval_mode,
    one_meet_tiebreak_mode,
    disable_searchspace,
    disable_costfn,
    disable_future_touch,
    double_count_future_ops,
    candidate_limit,
    iris_target_node=None,
    iris_target_chip=None,
    use_iris_candidate_seed=False,
):
    actions, _direct_ab_tie_keys, _plain_selected_action_key = _enumerate_gate_actions_with_metadata(
        s=s,
        t=t,
        pos_s=pos_s,
        pos_t=pos_t,
        dyn_agg=dyn_agg,
        future_gates=future_gates,
        qubit_positions=qubit_positions,
        active_qubits=active_qubits,
        connectivity=connectivity,
        gcache=gcache,
        channel_dict=channel_dict,
        candidate_eval_mode=candidate_eval_mode,
        one_meet_tiebreak_mode=one_meet_tiebreak_mode,
        disable_searchspace=disable_searchspace,
        disable_costfn=disable_costfn,
        disable_future_touch=disable_future_touch,
        double_count_future_ops=double_count_future_ops,
        candidate_limit=candidate_limit,
        iris_target_node=iris_target_node,
        iris_target_chip=iris_target_chip,
        use_iris_candidate_seed=use_iris_candidate_seed,
    )
    return actions

def simulate_qucomm_gate_transition(
    *,
    gate_spec,
    future_gate_specs,
    state,
    connectivity,
    aggregation_node,
    candidate_eval_mode="active_chip_nodes",
    one_meet_tiebreak_mode="legacy_direct",
    disable_searchspace=False,
    disable_costfn=False,
    disable_future_touch=False,
    enable_teleport_hybrid=False,
    double_count_future_ops=False,
    forced_action=None,
):
    gcache = GraphCache(connectivity)
    current_gate = gate_spec["gate"]
    block_index = gate_spec["block_index"]
    s, t = current_gate
    future_gates = [spec["gate"] for spec in future_gate_specs]
    active_qubits = {s, t}
    for gs, gt in future_gates:
        active_qubits.add(gs)
        active_qubits.add(gt)

    position_table = state["position_table"].copy()
    channel_dict = state["channel_dict"].copy()
    atom_paths = {k: list(v) for k, v in state["atom_paths"].items()}
    block_orig_positions_by_block = {
        k: v.copy() for k, v in state.get("block_orig_positions_by_block", {}).items()
    }
    qubit_positions = {q: position_table[q] for q in active_qubits}
    if block_index not in block_orig_positions_by_block:
        block_orig_positions_by_block[block_index] = {
            q: position_table[q]
            for q in sorted(active_qubits)
        }
    orig_positions = block_orig_positions_by_block[block_index].copy()
    # Lazy shallow copy: only duplicate the two gate-lists that
    # consume_interact_info will mutate (s, t).  The remaining ~70 qubit
    # lists are read-only within a single gate simulation, so sharing
    # references with the source dict is safe and avoids 245 K × 72
    # redundant list() copies that dominated init_interact_info cost.
    _src_ii = state.get("interact_info")
    if _src_ii is not None:
        ii = dict(_src_ii)                       # shallow dict copy
        for _q in (s, t):                        # deep-copy only mutated lists
            if _q in ii:
                ii[_q] = list(ii[_q])
    else:
        ii = init_interact_info(
            _build_gate_interact_info([current_gate] + future_gates),
            PRINT_DEBUG=False,
        )

    position_timeline = []
    gate_timeline = []
    op_log = []
    relocates_per_gate = []
    recnot_flags = []
    all_released_qubits = set()
    evict_cooldown = {}
    num_relocates = 0
    num_epr_release = 0
    gate_relocates = 0
    gate_idx = gate_spec["global_gate_index"]
    gate_start_pos_s = qubit_positions[s]
    gate_start_pos_t = qubit_positions[t]
    seen_gate_states = set()
    forced_iris_seed = bool(forced_action and forced_action.get("iris_seed"))
    selected_action = {"mode": "baseline"}
    gate_entry_action = None

    while qubit_positions[s] != qubit_positions[t]:
        pos_s, pos_t = qubit_positions[s], qubit_positions[t]
        if disable_searchspace:
            candidate_nodes = sorted({pos_s, pos_t})
        else:
            candidate_nodes = _candidate_nodes_for_mode(
                active_qubits,
                qubit_positions,
                connectivity,
                gcache,
                candidate_eval_mode,
            )
        dyn_agg = compute_dynamic_agg(
            (s, t),
            future_gates,
            qubit_positions,
            aggregation_node,
            connectivity,
            gcache,
            channel_dict,
            PRINT_DEBUG=False,
            candidate_nodes=candidate_nodes,
        )

        current_state_key = _gate_progress_state_key(
            active_qubits,
            qubit_positions,
            channel_dict,
        )
        repeated_state = current_state_key in seen_gate_states
        seen_gate_states.add(current_state_key)

        forced_mp = None
        forced_teleport_choice = None
        if forced_action and not repeated_state:
            forced_key = _forced_action_to_key(forced_action)
            if forced_key is not None:
                cands = enumerate_one_sided_meet_candidates(
                    pos_s,
                    pos_t,
                    s,
                    t,
                    future_gates,
                    qubit_positions,
                    dyn_agg,
                    channel_dict,
                    gcache,
                    candidate_nodes=candidate_nodes,
                    tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    double_count_future_ops=double_count_future_ops,
                    PRINT_DEBUG=False,
                )
                for cand in cands:
                    if _candidate_key(cand) == forced_key:
                        predicted_state_key = _predicted_one_meet_state_key(
                            cand,
                            active_qubits,
                            qubit_positions,
                            channel_dict,
                        )
                        if predicted_state_key not in seen_gate_states:
                            forced_mp = cand
                        break
            elif forced_action.get("mode") == "teleport" and enable_teleport_hybrid:
                tp_opts = evaluate_teleport_options(
                    s,
                    t,
                    pos_s,
                    pos_t,
                    qubit_positions,
                    active_qubits,
                    future_gates,
                    channel_dict,
                    gcache,
                )
                if tp_opts:
                    tp_opts = sorted(tp_opts, key=_teleport_option_sort_key)
                    for opt in tp_opts:
                        if _teleport_action_matches_option(forced_action, opt):
                            forced_teleport_choice = opt
                            break

        mp = forced_mp
        teleport_choice = None
        if mp is None and not repeated_state:
            mp = find_best_one_sided_meet(
                pos_s,
                pos_t,
                s,
                t,
                future_gates,
                qubit_positions,
                dyn_agg,
                channel_dict,
                gcache,
                candidate_nodes=candidate_nodes,
                tiebreak_mode=one_meet_tiebreak_mode,
                disable_searchspace=disable_searchspace,
                disable_costfn=disable_costfn,
                disable_future_touch=disable_future_touch,
                double_count_future_ops=double_count_future_ops,
                PRINT_DEBUG=False,
            )

            if enable_teleport_hybrid:
                tp_opts = evaluate_teleport_options(
                    s,
                    t,
                    pos_s,
                    pos_t,
                    qubit_positions,
                    active_qubits,
                    future_gates,
                    channel_dict,
                    gcache,
                )
                if tp_opts:
                    tp_opts = sorted(tp_opts, key=_teleport_option_sort_key)
                    teleport_choice = tp_opts[0]

        use_teleport = False
        if forced_teleport_choice is not None:
            teleport_choice = forced_teleport_choice
            use_teleport = True
        elif forced_mp is None and teleport_choice is not None and mp is not None:
            use_teleport = teleport_choice[0] < _hybrid_one_meet_cost(
                mp,
                disable_costfn=disable_costfn,
            )
        elif forced_mp is None and teleport_choice is not None:
            use_teleport = True

        if use_teleport:
            _best_cost, best_label, best_info = teleport_choice
            selected_action = _teleport_action_from_option(teleport_choice)
            if gate_entry_action is None:
                gate_entry_action = {**selected_action}
            hops = execute_teleport(
                best_label,
                best_info,
                s,
                t,
                pos_s,
                pos_t,
                gate_idx,
                connectivity,
                channel_dict,
                qubit_positions,
                atom_paths,
                active_qubits,
                position_timeline,
                gate_timeline,
                op_log,
                gcache,
                PRINT_DEBUG=False,
            )
            num_relocates += hops
            gate_relocates += hops
            _sync_active_positions(position_table, qubit_positions, active_qubits)
        elif mp is not None:
            selected_action = {
                "mode": "one_meet",
                "meeting_node": mp["meeting_node"],
                "move_qubit": mp["move_qubit"],
            }
            if forced_iris_seed:
                selected_action["iris_seed"] = True
            if gate_entry_action is None:
                gate_entry_action = {**selected_action}
            num_relocates, gate_relocates = _execute_one_meet(
                gate_idx,
                mp,
                mp["move_qubit"],
                connectivity,
                channel_dict,
                qubit_positions,
                position_table,
                atom_paths,
                active_qubits,
                num_relocates,
                gate_relocates,
                op_log,
                gate_timeline,
                position_timeline,
                False,
            )
        else:
            selected_action = {"mode": "recovery"}
            if gate_entry_action is None:
                gate_entry_action = {**selected_action}
            progressed, num_relocates, gate_relocates, num_epr_release = _resolve_no_path(
                gate_idx,
                s,
                t,
                future_gates,
                dyn_agg,
                connectivity,
                channel_dict,
                position_table,
                qubit_positions,
                atom_paths,
                active_qubits,
                evict_cooldown,
                1,
                ii,
                gcache,
                num_relocates,
                gate_relocates,
                num_epr_release,
                op_log,
                gate_timeline,
                position_timeline,
                False,
            )
            assert progressed, f"[DEADLOCK] gate {gate_idx} ({s},{t})"

        assert_channel_invariant(channel_dict, context=f"gate_rollout gate {gate_idx}")

    execution_node = qubit_positions[s]

    _record_gate_execution(
        s,
        t,
        gate_idx,
        gate_start_pos_s,
        gate_start_pos_t,
        qubit_positions,
        orig_positions,
        active_qubits,
        connectivity,
        channel_dict,
        position_timeline,
        gate_timeline,
        [],
        [],
        relocates_per_gate,
        recnot_flags,
        gate_relocates,
        False,
    )

    num_relocates, gate_relocates = _handle_post_gate_interact(
        ii,
        s,
        t,
        gate_idx,
        future_gates,
        qubit_positions,
        position_table,
        atom_paths,
        active_qubits,
        connectivity,
        channel_dict,
        gcache,
        num_relocates,
        gate_relocates,
        relocates_per_gate,
        all_released_qubits,
        op_log,
        gate_timeline,
        position_timeline,
        False,
    )

    return {
        "position_table": position_table,
        "channel_dict": channel_dict,
        "atom_paths": atom_paths,
        "block_orig_positions_by_block": block_orig_positions_by_block,
        "interact_info": ii,
        "selected_action": (
            {"mode": "baseline"}
            if gate_entry_action is None
            else gate_entry_action
        ),
        "execution_node": execution_node,
        "cost_reloc": num_relocates,
        "cost_recnot": sum(1 for flag in recnot_flags if flag),
        "cost_release": num_epr_release,
        "routing_cost": compute_routing_cost(
            num_relocates,
            sum(1 for flag in recnot_flags if flag),
            num_epr_release,
        ),
    }

def choose_qucomm_gate_rollout_plan(
    *,
    blocks,
    aggs,
    block_ids,
    block_index,
    position_table,
    channel_dict,
    atom_paths,
    interact_info=None,
    connectivity,
    lookahead_depth,
    candidate_eval_mode="active_chip_nodes",
    one_meet_tiebreak_mode="legacy_direct",
    disable_searchspace=False,
    disable_costfn=False,
    disable_future_touch=False,
    enable_teleport_hybrid=False,
    double_count_future_ops=False,
    beam_width=DEFAULT_GATE_BEAM_WIDTH,
    candidate_limit=DEFAULT_GATE_CANDIDATE_LIMIT,
    enable_foresight=False,
    planning_option="opt0",
    sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE,
    iris_guidance=None,
    enable_critical_future_blocks=False,
    critical_future_scan_depth=2,
    critical_future_topk=1,
    critical_future_pair_weight=0.25,
    critical_future_multipair_weight=0.125,
    enable_same_chip_future_pressure=False,
    same_chip_future_pair_weight=0.25,
    same_chip_future_multipair_weight=0.125,
    enable_pair_distance_future_pressure=False,
    pair_distance_future_weight=0.125,
    future_block_decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE,
    beam_prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE,
    disable_exact_top_tie_refinement=False,
    block_levels=None,
    collect_debug=True,
):
    option = str(planning_option).lower()
    common = {
        "blocks": blocks,
        "aggs": aggs,
        "block_ids": block_ids,
        "block_index": block_index,
        "position_table": position_table,
        "channel_dict": channel_dict,
        "atom_paths": atom_paths,
        "interact_info": interact_info,
        "connectivity": connectivity,
        "lookahead_depth": lookahead_depth,
        "candidate_eval_mode": candidate_eval_mode,
        "one_meet_tiebreak_mode": one_meet_tiebreak_mode,
        "disable_searchspace": disable_searchspace,
        "disable_costfn": disable_costfn,
        "disable_future_touch": disable_future_touch,
        "enable_teleport_hybrid": enable_teleport_hybrid,
        "double_count_future_ops": double_count_future_ops,
        "beam_width": beam_width,
        "candidate_limit": candidate_limit,
        "enable_foresight": enable_foresight,
        "sort_mode": sort_mode,
        "iris_guidance": iris_guidance,
        "enable_critical_future_blocks": enable_critical_future_blocks,
        "critical_future_scan_depth": critical_future_scan_depth,
        "critical_future_topk": critical_future_topk,
        "critical_future_pair_weight": critical_future_pair_weight,
        "critical_future_multipair_weight": critical_future_multipair_weight,
        "enable_same_chip_future_pressure": enable_same_chip_future_pressure,
        "same_chip_future_pair_weight": same_chip_future_pair_weight,
        "same_chip_future_multipair_weight": same_chip_future_multipair_weight,
        "enable_pair_distance_future_pressure": enable_pair_distance_future_pressure,
        "pair_distance_future_weight": pair_distance_future_weight,
        "future_block_decay_mode": future_block_decay_mode,
        "beam_prune_mode": beam_prune_mode,
        "disable_exact_top_tie_refinement": disable_exact_top_tie_refinement,
        "block_levels": block_levels,
        "collect_debug": collect_debug,
    }
    if option == "opt1":
        return _choose_qucomm_gate_rollout_plan_opt1(**common)
    if option == "opt0":
        return _choose_qucomm_gate_rollout_plan_opt0(**common)
    raise ValueError(f"Unknown QuComm gate lookahead planning option: {planning_option}")


def _choose_qucomm_gate_rollout_plan_opt1(
    *,
    blocks,
    aggs,
    block_ids,
    block_index,
    position_table,
    channel_dict,
    atom_paths,
    interact_info,
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
    enable_foresight,
    iris_guidance,
    enable_critical_future_blocks,
    critical_future_scan_depth,
    critical_future_topk,
    critical_future_pair_weight,
    critical_future_multipair_weight,
    enable_same_chip_future_pressure,
    same_chip_future_pair_weight,
    same_chip_future_multipair_weight,
    enable_pair_distance_future_pressure,
    pair_distance_future_weight,
    future_block_decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE,
    beam_prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE,
    disable_exact_top_tie_refinement=False,
    block_levels=None,
    sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE,
    collect_debug=True,
):
    gate_specs = _flatten_gate_window(blocks, block_ids, block_index, lookahead_depth)
    if not gate_specs:
        return {}, (), {"mode": "empty", "planning_option": "opt1"}
    window_upper = _rollout_window_upper(len(blocks), block_index, lookahead_depth)
    current_block_end = max(
        idx
        for idx, spec in enumerate(gate_specs)
        if spec["block_index"] == block_index
    )

    initial_state = {
        "position_table": position_table.copy(),
        "channel_dict": channel_dict.copy(),
        "atom_paths": {k: list(v) for k, v in atom_paths.items()},
        "interact_info": init_interact_info(interact_info, PRINT_DEBUG=False),
        "block_orig_positions_by_block": {},
    }
    beam = [
        {
            "state": initial_state,
            "_mk": _mapping_key(initial_state["position_table"]),
            "actions": (),
            "_ak": (),
            "cost_vector": [],
            "sort_cost_vector": [],
            "prune_prefix_cost": 0.0,
            "current_block_total_cost": 0.0,
            "sort_total_cost": 0.0,
            "total_cost": 0.0,
            "teleports": 0,
            "recnots": 0,
            "releases": 0,
            "block_aggs": {},
            "prefix_states": {},
            "guidance_total_adjustment": 0.0,
            "guidance_trace": (),
            "critical_future_total_adjustment": 0.0,
            "critical_future_trace": (),
        }
    ]
    _prefix_keep_indices = frozenset({current_block_end})
    candidate_counts = []
    raw_candidate_counts = []
    unique_mapping_counts = []
    _preserve_objective_ties = bool(
        iris_guidance and iris_guidance.get("preserve_objective_ties", False)
    )
    # Branch-alt diversity snapshot: when the outer harness installed a sink,
    # we record the post-prune beam at depth=current_block_end so that every
    # captured alt represents a *distinct routing of block_index itself* — not
    # a future-lookahead variant that happens to share block_index actions.
    _block_k_beam_snapshot = None

    for depth, gate_spec in enumerate(gate_specs):
        future_specs = _same_block_future_specs(gate_specs, depth)
        future_gates = [spec["gate"] for spec in future_specs]
        routing_cost_weight = _future_block_decay_weight(
            block_index,
            gate_spec["block_index"],
            decay_mode=future_block_decay_mode,
            block_levels=block_levels,
        )
        s, t = gate_spec["gate"]
        active_qubits = {s, t}
        for spec in future_specs:
            gs, gt = spec["gate"]
            active_qubits.add(gs)
            active_qubits.add(gt)
        iris_seed_target_node, iris_seed_target_chip = _iris_candidate_seed_target(
            iris_guidance,
            gate_spec,
        )
        use_iris_candidate_seed = (
            iris_seed_target_node is not None or iris_seed_target_chip is not None
        )

        next_beam = []
        expanded_candidate_count = 0

        seed_actions = None
        if not enable_foresight:
            seed_node = beam[0]
            seed_state = seed_node["state"]
            gcache = GraphCache(connectivity)
            block_agg = _resolve_block_agg(
                seed_node,
                gate_spec,
                blocks=blocks,
                aggs=aggs,
                connectivity=connectivity,
                start_block_index=block_index,
            )
            pos_s = seed_state["position_table"][s]
            pos_t = seed_state["position_table"][t]
            if disable_searchspace:
                candidate_nodes = sorted({pos_s, pos_t})
            else:
                candidate_nodes = _candidate_nodes_for_mode(
                    active_qubits,
                    seed_state["position_table"],
                    connectivity,
                    gcache,
                    candidate_eval_mode,
                )
            dyn_agg = compute_dynamic_agg(
                (s, t),
                future_gates,
                seed_state["position_table"],
                block_agg,
                connectivity,
                gcache,
                seed_state["channel_dict"],
                PRINT_DEBUG=False,
                candidate_nodes=candidate_nodes,
            )
            seed_actions = _enumerate_gate_actions(
                s=s,
                t=t,
                pos_s=pos_s,
                pos_t=pos_t,
                dyn_agg=dyn_agg,
                future_gates=future_gates,
                qubit_positions=seed_state["position_table"],
                active_qubits=active_qubits,
                connectivity=connectivity,
                gcache=gcache,
                channel_dict=seed_state["channel_dict"],
                candidate_eval_mode=candidate_eval_mode,
                one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                disable_searchspace=disable_searchspace,
                disable_costfn=disable_costfn,
                disable_future_touch=disable_future_touch,
                double_count_future_ops=double_count_future_ops,
                candidate_limit=candidate_limit,
                iris_target_node=iris_seed_target_node,
                iris_target_chip=iris_seed_target_chip,
                use_iris_candidate_seed=use_iris_candidate_seed,
            )
            expanded_candidate_count = len(seed_actions)

        for node in beam:
            state = node["state"]
            if enable_foresight:
                gcache = GraphCache(connectivity)
                block_agg = _resolve_block_agg(
                    node,
                    gate_spec,
                    blocks=blocks,
                    aggs=aggs,
                    connectivity=connectivity,
                    start_block_index=block_index,
                )
                pos_s = state["position_table"][s]
                pos_t = state["position_table"][t]
                if disable_searchspace:
                    candidate_nodes = sorted({pos_s, pos_t})
                else:
                    candidate_nodes = _candidate_nodes_for_mode(
                        active_qubits,
                        state["position_table"],
                        connectivity,
                        gcache,
                        candidate_eval_mode,
                    )
                dyn_agg = compute_dynamic_agg(
                    (s, t),
                    future_gates,
                    state["position_table"],
                    block_agg,
                    connectivity,
                    gcache,
                    state["channel_dict"],
                    PRINT_DEBUG=False,
                    candidate_nodes=candidate_nodes,
                )
                actions = _enumerate_gate_actions(
                    s=s,
                    t=t,
                    pos_s=pos_s,
                    pos_t=pos_t,
                    dyn_agg=dyn_agg,
                    future_gates=future_gates,
                    qubit_positions=state["position_table"],
                    active_qubits=active_qubits,
                    connectivity=connectivity,
                    gcache=gcache,
                    channel_dict=state["channel_dict"],
                    candidate_eval_mode=candidate_eval_mode,
                    one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    double_count_future_ops=double_count_future_ops,
                    candidate_limit=candidate_limit,
                    iris_target_node=iris_seed_target_node,
                    iris_target_chip=iris_seed_target_chip,
                    use_iris_candidate_seed=use_iris_candidate_seed,
                )
                expanded_candidate_count += len(actions)
            else:
                actions = seed_actions
            for action in actions:
                result = simulate_qucomm_gate_transition(
                    gate_spec=gate_spec,
                    future_gate_specs=future_specs,
                    state=state,
                    connectivity=connectivity,
                    aggregation_node=block_agg,
                    candidate_eval_mode=candidate_eval_mode,
                    one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    enable_teleport_hybrid=enable_teleport_hybrid,
                    double_count_future_ops=double_count_future_ops,
                    forced_action=None if action["mode"] == "baseline" else action,
                )
                step_state = _wrap_simulate_result(result)
                guidance_step = _iris_guidance_step(
                    iris_guidance=iris_guidance,
                    gate_spec=gate_spec,
                    active_qubits=active_qubits,
                    result=result,
                    step_state=step_state,
                    gcache=gcache,
                )
                critical_future_step = _critical_future_block_step(
                    gate_specs=gate_specs,
                    gate_offset=depth,
                    step_state=step_state,
                    blocks=blocks,
                    block_ids=block_ids,
                    block_levels=block_levels,
                    connectivity=connectivity,
                    lookahead_depth=lookahead_depth,
                    enabled=enable_critical_future_blocks,
                    scan_depth=critical_future_scan_depth,
                    topk=critical_future_topk,
                    pair_weight=critical_future_pair_weight,
                    multipair_weight=critical_future_multipair_weight,
                    enable_same_chip_pressure=enable_same_chip_future_pressure,
                    same_chip_pair_weight=same_chip_future_pair_weight,
                    same_chip_multipair_weight=(
                        same_chip_future_multipair_weight
                    ),
                    enable_pair_distance_pressure=(
                        enable_pair_distance_future_pressure
                    ),
                    pair_distance_weight=pair_distance_future_weight,
                    future_block_decay_mode=future_block_decay_mode,
                )
                cost_vector = list(node["cost_vector"]) + [
                    result["routing_cost"] * routing_cost_weight
                ]
                guidance_total_adjustment = round(
                    node.get("guidance_total_adjustment", 0.0)
                    + guidance_step["total_adjustment"],
                    8,
                )
                critical_future_total_adjustment = round(
                    node.get("critical_future_total_adjustment", 0.0)
                    + critical_future_step["total_adjustment"],
                    8,
                )
                new_actions = node["actions"] + ((gate_spec, result["selected_action"]),)
                _sel = result["selected_action"]
                new_ak = node.get("_ak", ()) + ((
                    gate_spec["block_index"],
                    gate_spec["local_gate_index"],
                    _sel["mode"],
                    _sel.get("meeting_node"),
                    _sel.get("move_qubit"),
                ),)
                total_cv = round(sum(cost_vector), 8)
                child = {
                    "state": step_state,
                    "_mk": _mapping_key(step_state["position_table"]),
                    "_ak": new_ak,
                    "block_aggs": dict(node["block_aggs"]),
                    "actions": new_actions,
                    "cost_vector": cost_vector,
                    "objective_cost_vector": list(cost_vector),
                    "future_cost_vector": [],
                    "prune_prefix_cost": round(
                        float(node.get("prune_prefix_cost", 0.0))
                        + float(result["routing_cost"]),
                        8,
                    ),
                    "current_block_total_cost": total_cv,
                    "total_cost": total_cv,
                    "teleports": node["teleports"]
                    + result["cost_reloc"]
                    + result["cost_release"],
                    "recnots": node["recnots"] + result["cost_recnot"],
                    "releases": node["releases"] + result["cost_release"],
                    "prefix_states": {**node["prefix_states"], depth: step_state} if depth in _prefix_keep_indices else node["prefix_states"],
                    "guidance_total_adjustment": guidance_total_adjustment,
                    "guidance_trace": node.get("guidance_trace", ())
                    + (guidance_step,),
                    "critical_future_total_adjustment": (
                        critical_future_total_adjustment
                    ),
                    "critical_future_trace": node.get("critical_future_trace", ())
                    + (critical_future_step,),
                }
                _apply_guidance_sort_fields(
                    child,
                    list(cost_vector),
                    child["total_cost"],
                )
                next_beam.append(
                    child
                )

        candidate_counts.append(expanded_candidate_count)
        raw_candidate_counts.append(len(next_beam))
        if enable_foresight:
            beam, prune_meta = _diversity_prune_beam(
                next_beam,
                beam_width,
                sort_mode,
                prune_mode=beam_prune_mode,
            )
        else:
            next_beam.sort(
                key=lambda node: _beam_prune_key(
                    node,
                    beam_prune_mode,
                    sort_mode,
                )
            )
            beam = next_beam[: max(1, int(beam_width))]
            beam.sort(key=lambda node: _beam_sort_key(node, sort_mode))
            prune_meta = {
                "raw_candidates": len(next_beam),
                "unique_mappings": len(
                    {
                        (node.get("_mk") or _mapping_key(node["state"]["position_table"]))
                        for node in next_beam
                    }
                ),
                "prune_mode": str(beam_prune_mode),
            }
        unique_mapping_counts.append(prune_meta["unique_mappings"])

        # Snapshot all explored block-k completions right after we finish
        # processing the last gate of block_index. We use the pre-prune
        # ``next_beam`` (every child considered at this gate, before the
        # beam_width cutoff), then dedupe by _mk so each unique post-block-k
        # state appears exactly once. This preserves the full diversity of
        # "ways the planner could have routed block_index" — not just the
        # 16 that survived pruning. node["teleports"] at this depth holds
        # exactly the block_index routing cost, which is what we hand to
        # the outer harness for branch replay.
        if depth == current_block_end and _BRANCH_ALT_SINK is not None:
            # Build a maximally-diverse snapshot of "what could block_index
            # have been". The non-foresight beam search reuses seed_actions
            # from beam[0] for every parent, which artificially collapses
            # diversity at the block boundary. Re-expand here per parent's
            # own state (foresight-style enumeration), then dedupe by _mk so
            # each unique post-block-k mapping is captured exactly once.
            _seen_mk = set()
            _block_k_beam_snapshot = []
            # First, take whatever next_beam already produced.
            for _cand in next_beam:
                _mk = _cand.get("_mk") or _mapping_key(
                    _cand["state"]["position_table"]
                )
                if _mk in _seen_mk:
                    continue
                _seen_mk.add(_mk)
                _block_k_beam_snapshot.append(_cand)

            # Then enrich with per-parent re-enumeration on the same gate.
            # We rerun simulate_qucomm_gate_transition for each (parent, act)
            # using the parent's own action set, so even parents that share
            # block_index history with beam[0] can branch into states the
            # main beam never visited.
            _enrich_s, _enrich_t = gate_spec["gate"]
            _enrich_active = {_enrich_s, _enrich_t}
            for _spec in future_specs:
                _enrich_active.update(_spec["gate"])
            for _parent in beam:
                _pstate = _parent["state"]
                _gcache = GraphCache(connectivity)
                _block_agg = _resolve_block_agg(
                    _parent,
                    gate_spec,
                    blocks=blocks,
                    aggs=aggs,
                    connectivity=connectivity,
                    start_block_index=block_index,
                )
                _pos_s = _pstate["position_table"][_enrich_s]
                _pos_t = _pstate["position_table"][_enrich_t]
                if disable_searchspace:
                    _cnodes = sorted({_pos_s, _pos_t})
                else:
                    _cnodes = _candidate_nodes_for_mode(
                        _enrich_active,
                        _pstate["position_table"],
                        connectivity,
                        _gcache,
                        candidate_eval_mode,
                    )
                _dyn_agg = compute_dynamic_agg(
                    (_enrich_s, _enrich_t),
                    future_gates,
                    _pstate["position_table"],
                    _block_agg,
                    connectivity,
                    _gcache,
                    _pstate["channel_dict"],
                    PRINT_DEBUG=False,
                    candidate_nodes=_cnodes,
                )
                _per_parent_actions = _enumerate_gate_actions(
                    s=_enrich_s,
                    t=_enrich_t,
                    pos_s=_pos_s,
                    pos_t=_pos_t,
                    dyn_agg=_dyn_agg,
                    future_gates=future_gates,
                    qubit_positions=_pstate["position_table"],
                    active_qubits=_enrich_active,
                    connectivity=connectivity,
                    gcache=_gcache,
                    channel_dict=_pstate["channel_dict"],
                    candidate_eval_mode=candidate_eval_mode,
                    one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    double_count_future_ops=double_count_future_ops,
                    candidate_limit=candidate_limit,
                    iris_target_node=iris_seed_target_node,
                    iris_target_chip=iris_seed_target_chip,
                    use_iris_candidate_seed=use_iris_candidate_seed,
                )
                for _action in _per_parent_actions:
                    _result = simulate_qucomm_gate_transition(
                        gate_spec=gate_spec,
                        future_gate_specs=future_specs,
                        state=_pstate,
                        connectivity=connectivity,
                        aggregation_node=_block_agg,
                        candidate_eval_mode=candidate_eval_mode,
                        one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                        disable_searchspace=disable_searchspace,
                        disable_costfn=disable_costfn,
                        disable_future_touch=disable_future_touch,
                        enable_teleport_hybrid=enable_teleport_hybrid,
                        double_count_future_ops=double_count_future_ops,
                        forced_action=None if _action["mode"] == "baseline" else _action,
                    )
                    _step_state = _wrap_simulate_result(_result)
                    _mk = _mapping_key(_step_state["position_table"])
                    if _mk in _seen_mk:
                        continue
                    _seen_mk.add(_mk)
                    _enriched_node = {
                        "state": _step_state,
                        "_mk": _mk,
                        "_ak": _parent.get("_ak", ()) + ((
                            gate_spec["block_index"],
                            gate_spec["local_gate_index"],
                            _result["selected_action"]["mode"],
                            _result["selected_action"].get("meeting_node"),
                            _result["selected_action"].get("move_qubit"),
                        ),),
                        "prefix_states": {
                            **_parent.get("prefix_states", {}),
                            current_block_end: _step_state,
                        },
                        "teleports": (
                            _parent["teleports"]
                            + _result["cost_reloc"]
                            + _result["cost_release"]
                        ),
                        "recnots": _parent["recnots"] + _result["cost_recnot"],
                        "releases": _parent["releases"] + _result["cost_release"],
                    }
                    _block_k_beam_snapshot.append(_enriched_node)

            import sys as _sys
            print(
                f"[branch-snap] block={block_index} next_beam={len(next_beam)} "
                f"parents={len(beam)} unique_after_enrich={len(_block_k_beam_snapshot)}",
                file=_sys.stderr,
                flush=True,
            )

    beam.sort(key=lambda node: _beam_sort_key(node, sort_mode))
    best = beam[0]

    # Branch alternative capture (opt-in, additive). Iterates the block-k
    # snapshot taken above (NOT the end-of-loop beam, which only varies in
    # the lookahead future), so each captured alt is a real alternative way
    # to route block_index. We hand the alt's post-block-k state to the outer
    # harness; the harness uses it as start_state for a suffix replay.
    if (
        _BRANCH_ALT_SINK is not None
        and _block_k_beam_snapshot is not None
        and len(_block_k_beam_snapshot) > 1
    ):
        # Exclude the alt whose post-block-k state matches the chosen's: it
        # would replay identically to chosen and clutter the figure.
        _chosen_block_k_state = best.get("prefix_states", {}).get(current_block_end)
        _chosen_block_k_mk = (
            _mapping_key(_chosen_block_k_state["position_table"])
            if _chosen_block_k_state is not None
            else None
        )
        _alt_rank_counter = 0
        for _alt_node in _block_k_beam_snapshot:
            _alt_state = _alt_node.get("prefix_states", {}).get(current_block_end)
            if _alt_state is None:
                continue
            _alt_mk = _mapping_key(_alt_state["position_table"])
            if _alt_mk == _chosen_block_k_mk:
                continue  # same effective state as chosen
            _alt_rank_counter += 1
            _alt_pt = dict(_alt_state["position_table"])
            _alt_cd = dict(_alt_state["channel_dict"])
            _alt_ap = {q: list(p) for q, p in _alt_state["atom_paths"].items()}
            _alt_ii = _copy.deepcopy(_alt_state.get("interact_info"))
            _BRANCH_ALT_SINK.append({
                "rank": _alt_rank_counter,
                "block_index": block_index,
                "block_k_state": {
                    "position_table": _alt_pt,
                    "channel_dict": _alt_cd,
                    "atom_paths": _alt_ap,
                    "interact_info": _alt_ii,
                },
                "block_k_teleports": int(_alt_node.get("teleports", 0)),
                "block_k_recnots": int(_alt_node.get("recnots", 0)),
                "block_k_releases": int(_alt_node.get("releases", 0)),
            })

    mode = "gate_level_rollout_foresight" if enable_foresight else "gate_level_rollout"
    return _summarize_gate_rollout_result(
        best=best,
        iris_guidance=iris_guidance,
        block_index=block_index,
        lookahead_depth=lookahead_depth,
        window_upper=window_upper,
        beam_width=beam_width,
        beam_prune_mode=beam_prune_mode,
        candidate_limit=candidate_limit,
        candidate_counts=candidate_counts,
        raw_candidate_counts=raw_candidate_counts,
        unique_mapping_counts=unique_mapping_counts,
        current_block_end=current_block_end,
        mode=mode,
        planning_option="opt1",
        blocks=blocks,
        block_ids=block_ids,
        block_levels=block_levels,
        connectivity=connectivity,
        enable_critical_future_blocks=enable_critical_future_blocks,
        critical_future_scan_depth=critical_future_scan_depth,
        critical_future_topk=critical_future_topk,
        critical_future_pair_weight=critical_future_pair_weight,
        critical_future_multipair_weight=critical_future_multipair_weight,
        enable_same_chip_future_pressure=enable_same_chip_future_pressure,
        same_chip_future_pair_weight=same_chip_future_pair_weight,
        same_chip_future_multipair_weight=same_chip_future_multipair_weight,
        enable_pair_distance_future_pressure=enable_pair_distance_future_pressure,
        pair_distance_future_weight=pair_distance_future_weight,
        future_block_decay_mode=future_block_decay_mode,
        sort_mode=sort_mode,
        collect_debug=collect_debug,
    )


def _choose_qucomm_gate_rollout_plan_opt0(
    *,
    blocks,
    aggs,
    block_ids,
    block_index,
    position_table,
    channel_dict,
    atom_paths,
    interact_info,
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
    enable_foresight,
    iris_guidance,
    enable_critical_future_blocks,
    critical_future_scan_depth,
    critical_future_topk,
    critical_future_pair_weight,
    critical_future_multipair_weight,
    enable_same_chip_future_pressure,
    same_chip_future_pair_weight,
    same_chip_future_multipair_weight,
    enable_pair_distance_future_pressure,
    pair_distance_future_weight,
    future_block_decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE,
    beam_prune_mode=DEFAULT_GATE_BEAM_PRUNE_MODE,
    disable_exact_top_tie_refinement=False,
    block_levels=None,
    sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE,
    collect_debug=True,
):
    gate_specs = _flatten_gate_window(blocks, block_ids, block_index, 0)
    if not gate_specs:
        return {}, (), {"mode": "empty", "planning_option": "opt0"}

    window_upper = _rollout_window_upper(len(blocks), block_index, lookahead_depth)
    current_block_end = len(gate_specs) - 1
    initial_state = {
        "position_table": position_table.copy(),
        "channel_dict": channel_dict.copy(),
        "atom_paths": {k: list(v) for k, v in atom_paths.items()},
        "interact_info": init_interact_info(interact_info, PRINT_DEBUG=False),
        "block_orig_positions_by_block": {},
    }
    initial_future_cost_vector, initial_window_aggs, _ = _estimate_future_block_suffix(
        state=initial_state,
        blocks=blocks,
        aggs=aggs,
        block_levels=block_levels,
        connectivity=connectivity,
        current_block_index=block_index,
        lookahead_depth=lookahead_depth,
        future_block_decay_mode=future_block_decay_mode,
    )
    initial_total_cost = sum(initial_future_cost_vector)
    beam = [
        {
            "state": initial_state,
            "_mk": _mapping_key(initial_state["position_table"]),
            "actions": (),
            "_ak": (),
            "cost_vector": [],
            "objective_cost_vector": list(initial_future_cost_vector),
            "future_cost_vector": list(initial_future_cost_vector),
            "estimated_window_aggs": list(initial_window_aggs),
            "prune_prefix_cost": 0.0,
            "total_cost": initial_total_cost,
            "current_block_total_cost": 0.0,
            "teleports": 0,
            "recnots": 0,
            "releases": 0,
            "block_aggs": {},
            "prefix_states": {},
            "guidance_total_adjustment": 0.0,
            "guidance_trace": (),
        }
    ]
    _prefix_keep_indices = frozenset({current_block_end})
    _apply_guidance_sort_fields(beam[0], list(initial_future_cost_vector), initial_total_cost)
    candidate_counts = []
    raw_candidate_counts = []
    unique_mapping_counts = []

    for depth, gate_spec in enumerate(gate_specs):
        future_specs = _same_block_future_specs(gate_specs, depth)
        future_gates = [spec["gate"] for spec in future_specs]
        s, t = gate_spec["gate"]
        active_qubits = {s, t}
        for spec in future_specs:
            gs, gt = spec["gate"]
            active_qubits.add(gs)
            active_qubits.add(gt)

        iris_seed_target_node, iris_seed_target_chip = _iris_candidate_seed_target(
            iris_guidance,
            gate_spec,
        )
        use_iris_candidate_seed = (
            iris_seed_target_node is not None or iris_seed_target_chip is not None
        )

        next_beam = []
        expanded_candidate_count = 0
        seed_actions = None
        seed_direct_ab_tie_keys = set()
        seed_plain_selected_action_key = None

        if not enable_foresight:
            seed_node = beam[0]
            seed_state = seed_node["state"]
            gcache = GraphCache(connectivity)
            block_agg = _resolve_block_agg(
                seed_node,
                gate_spec,
                blocks=blocks,
                aggs=aggs,
                connectivity=connectivity,
                start_block_index=block_index,
            )
            pos_s = seed_state["position_table"][s]
            pos_t = seed_state["position_table"][t]
            if disable_searchspace:
                candidate_nodes = sorted({pos_s, pos_t})
            else:
                candidate_nodes = _candidate_nodes_for_mode(
                    active_qubits,
                    seed_state["position_table"],
                    connectivity,
                    gcache,
                    candidate_eval_mode,
                )
            dyn_agg = compute_dynamic_agg(
                (s, t),
                future_gates,
                seed_state["position_table"],
                block_agg,
                connectivity,
                gcache,
                seed_state["channel_dict"],
                PRINT_DEBUG=False,
                candidate_nodes=candidate_nodes,
            )
            (
                seed_actions,
                seed_direct_ab_tie_keys,
                seed_plain_selected_action_key,
            ) = _enumerate_gate_actions_with_metadata(
                s=s,
                t=t,
                pos_s=pos_s,
                pos_t=pos_t,
                dyn_agg=dyn_agg,
                future_gates=future_gates,
                qubit_positions=seed_state["position_table"],
                active_qubits=active_qubits,
                connectivity=connectivity,
                gcache=gcache,
                channel_dict=seed_state["channel_dict"],
                candidate_eval_mode=candidate_eval_mode,
                one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                disable_searchspace=disable_searchspace,
                disable_costfn=disable_costfn,
                disable_future_touch=disable_future_touch,
                double_count_future_ops=double_count_future_ops,
                candidate_limit=candidate_limit,
                iris_target_node=iris_seed_target_node,
                iris_target_chip=iris_seed_target_chip,
                use_iris_candidate_seed=use_iris_candidate_seed,
            )
            expanded_candidate_count = len(seed_actions)

        preserve_objective_ties = bool(
            iris_guidance and iris_guidance.get("preserve_objective_ties", False)
        )

        for node in beam:
            state = node["state"]
            if enable_foresight:
                gcache = GraphCache(connectivity)
                block_agg = _resolve_block_agg(
                    node,
                    gate_spec,
                    blocks=blocks,
                    aggs=aggs,
                    connectivity=connectivity,
                    start_block_index=block_index,
                )
                pos_s = state["position_table"][s]
                pos_t = state["position_table"][t]
                if disable_searchspace:
                    candidate_nodes = sorted({pos_s, pos_t})
                else:
                    candidate_nodes = _candidate_nodes_for_mode(
                        active_qubits,
                        state["position_table"],
                        connectivity,
                        gcache,
                        candidate_eval_mode,
                    )
                dyn_agg = compute_dynamic_agg(
                    (s, t),
                    future_gates,
                    state["position_table"],
                    block_agg,
                    connectivity,
                    gcache,
                    state["channel_dict"],
                    PRINT_DEBUG=False,
                    candidate_nodes=candidate_nodes,
                )
                (
                    actions,
                    direct_ab_tie_keys,
                    plain_selected_action_key,
                ) = _enumerate_gate_actions_with_metadata(
                    s=s,
                    t=t,
                    pos_s=pos_s,
                    pos_t=pos_t,
                    dyn_agg=dyn_agg,
                    future_gates=future_gates,
                    qubit_positions=state["position_table"],
                    active_qubits=active_qubits,
                    connectivity=connectivity,
                    gcache=gcache,
                    channel_dict=state["channel_dict"],
                    candidate_eval_mode=candidate_eval_mode,
                    one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    double_count_future_ops=double_count_future_ops,
                    candidate_limit=candidate_limit,
                    iris_target_node=iris_seed_target_node,
                    iris_target_chip=iris_seed_target_chip,
                    use_iris_candidate_seed=use_iris_candidate_seed,
                )
                expanded_candidate_count += len(actions)
            else:
                actions = seed_actions
                direct_ab_tie_keys = seed_direct_ab_tie_keys
                plain_selected_action_key = seed_plain_selected_action_key

            node_children = []
            for action in actions:
                result = simulate_qucomm_gate_transition(
                    gate_spec=gate_spec,
                    future_gate_specs=future_specs,
                    state=state,
                    connectivity=connectivity,
                    aggregation_node=block_agg,
                    candidate_eval_mode=candidate_eval_mode,
                    one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    enable_teleport_hybrid=enable_teleport_hybrid,
                    double_count_future_ops=double_count_future_ops,
                    forced_action=None if action["mode"] == "baseline" else action,
                )
                step_state = _wrap_simulate_result(result)
                guidance_step = _iris_guidance_step(
                    iris_guidance=iris_guidance,
                    gate_spec=gate_spec,
                    active_qubits=active_qubits,
                    result=result,
                    step_state=step_state,
                    gcache=gcache,
                )
                exact_cost_vector = list(node["cost_vector"]) + [result["routing_cost"]]
                future_cost_vector, estimated_window_aggs, _ = _estimate_future_block_suffix(
                    state=step_state,
                    blocks=blocks,
                    aggs=aggs,
                    block_levels=block_levels,
                    connectivity=connectivity,
                    current_block_index=block_index,
                    lookahead_depth=lookahead_depth,
                    future_block_decay_mode=future_block_decay_mode,
                )
                objective_cost_vector = exact_cost_vector + future_cost_vector
                current_block_total_cost = sum(exact_cost_vector)
                selected_action_key = _forced_action_to_key(result["selected_action"])
                guidance_total_adjustment = round(
                    node.get("guidance_total_adjustment", 0.0)
                    + guidance_step["total_adjustment"],
                    8,
                )
                new_actions = node["actions"] + ((gate_spec, result["selected_action"]),)
                _sel = result["selected_action"]
                new_ak = node.get("_ak", ()) + ((
                    gate_spec["block_index"],
                    gate_spec["local_gate_index"],
                    _sel["mode"],
                    _sel.get("meeting_node"),
                    _sel.get("move_qubit"),
                ),)
                child = {
                    "state": step_state,
                    "_mk": _mapping_key(step_state["position_table"]),
                    "_ak": new_ak,
                    "block_aggs": dict(node["block_aggs"]),
                    "actions": new_actions,
                    "cost_vector": exact_cost_vector,
                    "objective_cost_vector": objective_cost_vector,
                    "future_cost_vector": future_cost_vector,
                    "estimated_window_aggs": list(estimated_window_aggs),
                    "prune_prefix_cost": round(
                        float(node.get("prune_prefix_cost", 0.0))
                        + float(result["routing_cost"]),
                        8,
                    ),
                    "current_block_total_cost": current_block_total_cost,
                    "proxy_total_cost": sum(objective_cost_vector),
                    "total_cost": round(sum(objective_cost_vector), 8),
                    "teleports": node["teleports"]
                    + result["cost_reloc"]
                    + result["cost_release"],
                    "recnots": node["recnots"] + result["cost_recnot"],
                    "releases": node["releases"] + result["cost_release"],
                    "prefix_states": {**node["prefix_states"], depth: step_state} if depth in _prefix_keep_indices else node["prefix_states"],
                    "selected_action_key": selected_action_key,
                    "plain_selected_action_key": plain_selected_action_key,
                    "guidance_total_adjustment": guidance_total_adjustment,
                    "guidance_trace": node.get("guidance_trace", ())
                    + (guidance_step,),
                }
                _apply_guidance_sort_fields(
                    child,
                    objective_cost_vector,
                    child["total_cost"],
                )
                node_children.append(child)

            if not enable_foresight:
                _apply_exact_suffix_refinement_to_children(
                    children=node_children,
                    gate_spec=gate_spec,
                    blocks=blocks,
                    aggs=aggs,
                    block_ids=block_ids,
                    block_index=block_index,
                    connectivity=connectivity,
                    lookahead_depth=lookahead_depth,
                    candidate_eval_mode=candidate_eval_mode,
                    one_meet_tiebreak_mode=one_meet_tiebreak_mode,
                    disable_searchspace=disable_searchspace,
                    disable_costfn=disable_costfn,
                    disable_future_touch=disable_future_touch,
                    enable_teleport_hybrid=enable_teleport_hybrid,
                    double_count_future_ops=double_count_future_ops,
                    beam_width=beam_width,
                    candidate_limit=candidate_limit,
                    direct_ab_tie_keys=direct_ab_tie_keys,
                    sort_mode=sort_mode,
                )
            if preserve_objective_ties:
                _preserve_objective_tie_sort_fields(node_children)
            next_beam.extend(node_children)

        candidate_counts.append(expanded_candidate_count)
        raw_candidate_counts.append(len(next_beam))
        if enable_foresight:
            beam, prune_meta = _diversity_prune_beam(
                next_beam,
                beam_width,
                sort_mode,
                prune_mode=beam_prune_mode,
            )
        else:
            next_beam.sort(
                key=lambda node: _beam_prune_key(
                    node,
                    beam_prune_mode,
                    sort_mode,
                )
            )
            beam = next_beam[: max(1, int(beam_width))]
            beam.sort(key=lambda node: _beam_sort_key(node, sort_mode))
            prune_meta = {
                "raw_candidates": len(next_beam),
                "unique_mappings": len(
                    {
                        (node.get("_mk") or _mapping_key(node["state"]["position_table"]))
                        for node in next_beam
                    }
                ),
                "prune_mode": str(beam_prune_mode),
            }
        unique_mapping_counts.append(prune_meta["unique_mappings"])

    beam.sort(key=lambda node: _beam_sort_key(node, sort_mode))
    best = beam[0]

    # ── Branch alternative capture (opt-in, additive) ─────────────────────
    # When an outer harness installs a sink via set_branch_alt_sink(), record
    # one entry per non-best beam node so the harness can replay discarded
    # paths. The captured forced_plan mirrors the format produced by
    # _summarize_gate_rollout_result below, so callers can pass it directly
    # to _route_single_block via qucomm_forced_gate_meet_plan=...
    if _BRANCH_ALT_SINK is not None and len(beam) > 1:
        for _alt_rank in range(1, len(beam)):
            _alt_node = beam[_alt_rank]
            _alt_forced_plan = {}
            for _spec, _action in _alt_node["actions"]:
                if _spec["block_index"] != block_index:
                    continue
                if _action["mode"] not in {"one_meet", "teleport"}:
                    continue
                _alt_forced_plan[_spec["local_gate_index"]] = dict(_action)
            _BRANCH_ALT_SINK.append({
                "rank": _alt_rank,
                "block_index": block_index,
                "forced_plan": _alt_forced_plan,
                "planner_teleports": int(_alt_node.get("teleports", 0)),
                "planner_recnots": int(_alt_node.get("recnots", 0)),
                "planner_releases": int(_alt_node.get("releases", 0)),
            })

    # ── Baseline safeguard ──
    # If the chosen plan produces more actual teleports (relocates + releases)
    # than the QuComm baseline path through this block, fall back to the
    # baseline to preserve the ForeSight >= QuComm invariant.
    # The baseline child is the one whose every per-gate action matches what
    # QuComm would pick (plain_selected_action_key at the last gate).
    if not enable_foresight and len(beam) > 1:
        baseline_node = None
        for node in beam:
            if node.get("selected_action_key") == node.get("plain_selected_action_key"):
                if baseline_node is None or node["teleports"] < baseline_node["teleports"]:
                    baseline_node = node
        if baseline_node is not None and best["teleports"] > baseline_node["teleports"]:
            best = baseline_node

    mode = "gate_level_rollout_foresight" if enable_foresight else "gate_level_rollout"
    return _summarize_gate_rollout_result(
        best=best,
        iris_guidance=iris_guidance,
        block_index=block_index,
        lookahead_depth=lookahead_depth,
        window_upper=window_upper,
        beam_width=beam_width,
        beam_prune_mode=beam_prune_mode,
        candidate_limit=candidate_limit,
        candidate_counts=candidate_counts,
        raw_candidate_counts=raw_candidate_counts,
        unique_mapping_counts=unique_mapping_counts,
        current_block_end=current_block_end,
        mode=mode,
        planning_option="opt0",
        blocks=blocks,
        block_ids=block_ids,
        connectivity=connectivity,
        enable_critical_future_blocks=enable_critical_future_blocks,
        critical_future_scan_depth=critical_future_scan_depth,
        critical_future_topk=critical_future_topk,
        critical_future_pair_weight=critical_future_pair_weight,
        critical_future_multipair_weight=critical_future_multipair_weight,
        enable_same_chip_future_pressure=enable_same_chip_future_pressure,
        same_chip_future_pair_weight=same_chip_future_pair_weight,
        same_chip_future_multipair_weight=same_chip_future_multipair_weight,
        enable_pair_distance_future_pressure=enable_pair_distance_future_pressure,
        pair_distance_future_weight=pair_distance_future_weight,
        future_block_decay_mode=future_block_decay_mode,
        sort_mode=sort_mode,
        collect_debug=collect_debug,
    )


def _summarize_gate_rollout_result(
    *,
    best,
    iris_guidance,
    block_index,
    lookahead_depth,
    window_upper,
    beam_width,
    beam_prune_mode,
    candidate_limit,
    candidate_counts,
    raw_candidate_counts,
    unique_mapping_counts,
    current_block_end,
    mode,
    planning_option,
    blocks=None,
    block_ids=None,
    block_levels=None,
    connectivity=None,
    enable_critical_future_blocks=False,
    critical_future_scan_depth=2,
    critical_future_topk=1,
    critical_future_pair_weight=0.25,
    critical_future_multipair_weight=0.125,
    enable_same_chip_future_pressure=False,
    same_chip_future_pair_weight=0.25,
    same_chip_future_multipair_weight=0.125,
    enable_pair_distance_future_pressure=False,
    pair_distance_future_weight=0.125,
    future_block_decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE,
    sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE,
    collect_debug=True,
):
    forced_plan = {}
    for spec, action in best["actions"]:
        if spec["block_index"] != block_index:
            continue
        if action["mode"] not in {"one_meet", "teleport"}:
            continue
        forced_plan[spec["local_gate_index"]] = dict(action)

    predicted_state_after_block = None
    if current_block_end in best.get("prefix_states", {}):
        _s = best["prefix_states"][current_block_end]
        predicted_state_after_block = {
            "position_table": _s["position_table"].copy(),
            "channel_dict": _s["channel_dict"].copy(),
            "atom_paths": {k: list(v) for k, v in _s["atom_paths"].items()},
        }
        if _s.get("interact_info") is not None:
            predicted_state_after_block["interact_info"] = init_interact_info(
                _s["interact_info"],
                PRINT_DEBUG=False,
            )

    current_block_cost_vector = list(best["cost_vector"][: current_block_end + 1])
    future_cost_vector = list(best.get("future_cost_vector", []))
    objective_cost_vector = list(
        best.get("objective_cost_vector", current_block_cost_vector + future_cost_vector)
    )
    if not future_cost_vector and len(objective_cost_vector) > len(current_block_cost_vector):
        future_cost_vector = list(objective_cost_vector[len(current_block_cost_vector) :])
    current_block_actions = []
    if collect_debug:
        guidance_trace = list(best.get("guidance_trace", []))
        guidance_by_gate = {
            (item["block_index"], item["local_gate_index"]): item
            for item in guidance_trace
        }
        for spec, action in best["actions"]:
            if spec["block_index"] != block_index:
                continue
            guidance_step = guidance_by_gate.get(
                (spec["block_index"], spec["local_gate_index"]),
                {},
            )
            current_block_actions.append(
                {
                    "block_index": spec["block_index"],
                    "local_gate_index": spec["local_gate_index"],
                    "gate": spec["gate"],
                    "mode": action["mode"],
                    "meeting_node": action.get("meeting_node"),
                    "move_qubit": action.get("move_qubit"),
                    "iris_seed": action.get("iris_seed", False),
                    "label": action.get("label"),
                    "path": (list(action["path"]) if action.get("path") else action.get("path")),
                    "q_d": action.get("q_d"),
                    "dest": action.get("dest"),
                    "displace_path": (list(action["displace_path"]) if action.get("displace_path") else action.get("displace_path")),
                    "main_path": (list(action["main_path"]) if action.get("main_path") else action.get("main_path")),
                    "iris_target_node": guidance_step.get("execution_target_node"),
                    "execution_node": guidance_step.get("execution_node"),
                    "guidance_adjustment": guidance_step.get("total_adjustment", 0.0),
                    "guidance_execution_penalty": guidance_step.get(
                        "execution_penalty",
                        0.0,
                    ),
                    "guidance_residency_penalty": guidance_step.get(
                        "residency_penalty",
                        0.0,
                    ),
                }
            )
    guidance_total_adjustment = round(
        best.get("guidance_total_adjustment", 0.0),
        8,
    )
    critical_trace = list(best.get("critical_future_trace", []))
    current_block_critical_step = {
        "block_index": block_index,
        "total_adjustment": 0.0,
        "component_adjustments": {
            "split_pair_adjustment": 0.0,
            "same_chip_adjustment": 0.0,
            "pair_distance_adjustment": 0.0,
        },
        "risky_blocks": [],
    }
    for step in critical_trace:
        if step.get("block_index") != block_index:
            continue
        current_block_critical_step = step
    current_block_critical_adjustment = round(
        current_block_critical_step.get("total_adjustment", 0.0),
        8,
    )
    current_block_critical_components = dict(
        current_block_critical_step.get("component_adjustments", {})
    )
    current_block_critical_risky_blocks = list(
        current_block_critical_step.get("risky_blocks", [])
    )
    critical_future_total_adjustment = round(
        best.get("critical_future_total_adjustment", 0.0),
        8,
    )
    critical_future_probe_adjustment = 0.0
    critical_future_probe_risky_blocks = []
    if (
        predicted_state_after_block is not None
        and blocks is not None
        and block_ids is not None
        and connectivity is not None
        and max(0, int(critical_future_scan_depth)) > 0
    ):
        (
            critical_future_probe_risky_blocks,
            critical_future_probe_adjustment,
            critical_future_probe_components,
        ) = _future_block_alignment_risk_summary(
            state=predicted_state_after_block,
            blocks=blocks,
            block_ids=block_ids,
            block_levels=block_levels,
            connectivity=connectivity,
            current_block_index=block_index,
            lookahead_depth=lookahead_depth,
            scan_depth=critical_future_scan_depth,
            topk=critical_future_topk,
            pair_weight=critical_future_pair_weight,
            multipair_weight=critical_future_multipair_weight,
            enable_split_pairs=enable_critical_future_blocks,
            enable_same_chip_pressure=enable_same_chip_future_pressure,
            same_chip_pair_weight=same_chip_future_pair_weight,
            same_chip_multipair_weight=same_chip_future_multipair_weight,
            enable_pair_distance_pressure=enable_pair_distance_future_pressure,
            pair_distance_weight=pair_distance_future_weight,
            future_block_decay_mode=future_block_decay_mode,
        )
    else:
        critical_future_probe_components = {
            "split_pair_adjustment": 0.0,
            "same_chip_adjustment": 0.0,
            "pair_distance_adjustment": 0.0,
        }
    guided_blocks = sorted((iris_guidance or {}).get("blocks", {}))

    return forced_plan, tuple(objective_cost_vector), {
        "mode": mode,
        "planning_option": planning_option,
        "foresight_enabled": bool("foresight" in mode),
        "beam_width": max(1, int(beam_width)),
        "beam_prune_mode": str(beam_prune_mode),
        "candidate_limit": candidate_limit,
        "planning_window_depth": max(0, int(lookahead_depth)),
        "effective_future_proxy_depth": _effective_future_proxy_depth(
            lookahead_depth
        ),
        "planning_window_block_count": max(0, window_upper - block_index),
        "future_block_decay_mode": str(future_block_decay_mode),
        "future_block_decay_target_distance": FUTURE_BLOCK_DECAY_TARGET_DISTANCE,
        "future_block_decay_target_weight": FUTURE_BLOCK_DECAY_TARGET_WEIGHT,
        "future_block_extra_decay_start_distance": (
            FUTURE_BLOCK_EXTRA_DECAY_START_DISTANCE
        ),
        "future_block_extra_decay_per_block": FUTURE_BLOCK_EXTRA_DECAY_PER_BLOCK,
        "general_exact_suffix_refinement_max_actions": (
            GENERAL_EXACT_SUFFIX_REFINEMENT_MAX_ACTIONS
        ),
        "general_exact_suffix_refinement_proxy_margin": (
            GENERAL_EXACT_SUFFIX_REFINEMENT_PROXY_MARGIN
        ),
        "general_exact_suffix_refinement_local_gate_limit": (
            GENERAL_EXACT_SUFFIX_REFINEMENT_LOCAL_GATE_LIMIT
        ),
        "candidate_counts": candidate_counts,
        "raw_candidate_counts": raw_candidate_counts,
        "unique_mapping_counts": unique_mapping_counts,
        "forced_gate_indices": sorted(forced_plan.keys()),
        "actions": current_block_actions,
        "planned_gate_count": len(
            [spec for spec, _action in best["actions"] if spec["block_index"] == block_index]
        ),
        "current_block_cost_vector": current_block_cost_vector,
        "future_block_estimate_vector": future_cost_vector,
        "objective_cost_vector": objective_cost_vector,
        "estimated_future_window_aggs": list(best.get("estimated_window_aggs", [])),
        "current_block_rollout_cost": round(sum(current_block_cost_vector), 8),
        "estimated_future_rollout_cost": round(sum(future_cost_vector), 8),
        "predicted_state_after_block": predicted_state_after_block,
        "objective_total_cost": round(best["total_cost"], 8),
        "total_cost": round(
            best.get("sort_total_cost", best["total_cost"]),
            8,
        ),
        "selection_total_cost": round(
            best.get("sort_total_cost", best["total_cost"]),
            8,
        ),
        "iris_guidance_enabled": bool(iris_guidance),
        "iris_guidance_guided_blocks": guided_blocks,
        "iris_guidance_total_adjustment": guidance_total_adjustment,
        "iris_guidance_target_distance_weight": (
            IRIS_GUIDANCE_TARGET_DISTANCE_WEIGHT
        ),
        "iris_guidance_residency_weight": IRIS_GUIDANCE_RESIDENCY_WEIGHT,
        "critical_future_enabled": bool(enable_critical_future_blocks),
        "critical_future_total_adjustment": critical_future_total_adjustment,
        "critical_future_scan_depth": max(0, int(critical_future_scan_depth)),
        "critical_future_topk": max(0, int(critical_future_topk)),
        "critical_future_pair_weight": float(critical_future_pair_weight),
        "critical_future_multipair_weight": float(
            critical_future_multipair_weight
        ),
        "same_chip_future_enabled": bool(enable_same_chip_future_pressure),
        "same_chip_future_pair_weight": float(same_chip_future_pair_weight),
        "same_chip_future_multipair_weight": float(
            same_chip_future_multipair_weight
        ),
        "pair_distance_future_enabled": bool(
            enable_pair_distance_future_pressure
        ),
        "pair_distance_future_weight": float(pair_distance_future_weight),
        "current_block_critical_future_adjustment": (
            current_block_critical_adjustment
        ),
        "current_block_critical_future_components": (
            current_block_critical_components if collect_debug else {}
        ),
        "current_block_critical_future_risky_blocks": (
            current_block_critical_risky_blocks if collect_debug else []
        ),
        "critical_future_probe_total_adjustment": round(
            critical_future_probe_adjustment,
            8,
        ),
        "critical_future_probe_components": (
            critical_future_probe_components if collect_debug else {}
        ),
        "critical_future_probe_risky_blocks": (
            critical_future_probe_risky_blocks if collect_debug else []
        ),
        "critical_future_trace": critical_trace if collect_debug else [],
    }


def _enumerate_gate_actions_with_metadata(
    *,
    s,
    t,
    pos_s,
    pos_t,
    dyn_agg,
    future_gates,
    qubit_positions,
    active_qubits,
    connectivity,
    gcache,
    channel_dict,
    candidate_eval_mode,
    one_meet_tiebreak_mode,
    disable_searchspace,
    disable_costfn,
    disable_future_touch,
    double_count_future_ops,
    candidate_limit,
    iris_target_node=None,
    iris_target_chip=None,
    use_iris_candidate_seed=False,
):
    if disable_searchspace:
        candidate_nodes = sorted({pos_s, pos_t})
    else:
        candidate_nodes = _candidate_nodes_for_mode(
            active_qubits,
            qubit_positions,
            connectivity,
            gcache,
            candidate_eval_mode,
        )

    actions = [{"mode": "baseline"}]
    cands = enumerate_one_sided_meet_candidates(
        pos_s,
        pos_t,
        s,
        t,
        future_gates,
        qubit_positions,
        dyn_agg,
        channel_dict,
        gcache,
        candidate_nodes=candidate_nodes,
        tiebreak_mode=one_meet_tiebreak_mode,
        disable_searchspace=disable_searchspace,
        disable_costfn=disable_costfn,
        disable_future_touch=disable_future_touch,
        double_count_future_ops=double_count_future_ops,
        PRINT_DEBUG=False,
    )
    direct_ab_tie_keys = equivalent_direct_ab_tie_action_keys(
        cands,
        pos_s,
        pos_t,
        s,
        t,
    )
    plain_selected_action_key = None
    if cands:
        plain_selected_action_key = _candidate_key(cands[0])

    seen = set()
    for cand in cands:
        key = _candidate_key(cand)
        if key in seen:
            continue
        seen.add(key)
        actions.append(
            {
                "mode": "one_meet",
                "meeting_node": cand["meeting_node"],
                "move_qubit": cand["move_qubit"],
            }
        )
        if len(actions) >= max(1, candidate_limit):
            break
    if use_iris_candidate_seed and cands:
        seeded = None
        if iris_target_node is not None:
            iris_target_node = tuple(iris_target_node)
            for cand in cands:
                if tuple(cand["meeting_node"]) == iris_target_node:
                    seeded = cand
                    break
        if seeded is None and iris_target_chip is not None:
            for cand in cands:
                cand_chip = _node_chip_key(cand["meeting_node"], gcache)
                if cand_chip == iris_target_chip:
                    seeded = cand
                    break
        if seeded is not None:
            key = _candidate_key(seeded)
            if key not in seen:
                actions.append(
                    {
                        "mode": "one_meet",
                        "meeting_node": seeded["meeting_node"],
                        "move_qubit": seeded["move_qubit"],
                        "iris_seed": True,
                    }
                )
    return actions, direct_ab_tie_keys, plain_selected_action_key


def set_branch_alt_sink(sink):
    """Install (or clear) a list to receive discarded-beam alternative records.

    Pass a fresh ``list`` before each block's planner call to capture the
    final beam's non-best nodes; pass ``None`` afterwards to disable.
    """
    global _BRANCH_ALT_SINK
    _BRANCH_ALT_SINK = sink


def get_branch_alt_sink():
    return _BRANCH_ALT_SINK


_BRANCH_ALT_SINK = None
