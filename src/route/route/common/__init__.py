import copy
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
import networkx as nx
from ... import debug as dbg
from ...aggregation import compute_dynamic_agg
from ...cache import GraphCache
from ...channel import assert_channel_invariant, assert_edge_in_connectivity, channel_snapshot, consume_capacity, consume_path, link_capacity, release_recnot_channel, reserve_recnot_channel
from ...constants import EVICT_COOLDOWN_WINDOW, INF, MAX_MOVE_ROUNDS, compute_routing_cost
from ...evict import build_protected_set, try_local_evict
from ...gate_utils import normalize_block_to_gates
from ...interact import consume_interact_info, get_still_active_qubits, init_interact_info
from ...meeting import ONE_MEET_TIEBREAK_LEGACY_DIRECT, ONE_MEET_TIEBREAK_MODES, ONE_MEET_TIEBREAK_ORIGINAL, enumerate_one_sided_meet_candidates, find_best_one_sided_meet, _is_direct_ab_candidate
from ...pathfinding import first_hop_with_capacity, nearest_neighbor_toward, relaxed_hop_with_capacity
from ...release import handle_released_qubits
from ...reorder import reorder_gates
from ...teleport import evaluate_teleport_options, execute_teleport
from ._constants import CANDIDATE_EVAL_MODE_ACTIVE_CHIPS, CANDIDATE_EVAL_MODE_ALL, CANDIDATE_EVAL_MODES, STRICT_PHYSICS_VALIDATION
from ._execution import _execute_one_meet, _handle_post_gate_interact, _record_gate_execution
from ._greedy import _resolve_no_path
from ._helpers import _candidate_nodes_for_mode, _gate_progress_state_key, _node_chip_key, _node_sort_key, _predicted_one_meet_state_key, _simulate_channel_after_path
from ._output import _build_detailed_rows, _build_output, _sync_active_positions
from ._teleport_helpers import _hybrid_one_meet_cost, _teleport_action_from_option, _teleport_action_matches_option, _teleport_option_sort_key
from ._validation import _validate_atom_paths, _validate_inputs
__all__ = [name for name in dir() if name not in {'__all__', '__builtins__', '__cached__', '__doc__', '__file__', '__loader__', '__name__', '__package__', '__spec__', '__path__'}]

def equivalent_direct_ab_tie_action_keys(cands, pos_s, pos_t, s, t):
    if not cands:
        return set()

    if not cands[0].get('use_anbang_direct_tie_break', False):
        return set()

    selected_prefix = cands[0]['original_cost_key'][:4]
    return {
        (cand['meeting_node'], cand['move_qubit'])
        for cand in cands
        if _is_direct_ab_candidate(cand, pos_s, pos_t, s, t)
        and cand['original_cost_key'][:4] == selected_prefix
    }
