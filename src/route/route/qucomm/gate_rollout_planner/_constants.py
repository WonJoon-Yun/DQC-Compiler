import functools
import math
DEFAULT_GATE_BEAM_WIDTH = 16
DEFAULT_GATE_CANDIDATE_LIMIT = 6
DEFAULT_GATE_LOOKAHEAD_SORT_MODE = 'current_then_total'
DEFAULT_GATE_BEAM_PRUNE_MODE = 'scheduled_prefix_cost'
DEFAULT_FUTURE_BLOCK_DECAY_MODE = 'linear'
FUTURE_BLOCK_DECAY_TARGET_DISTANCE = 10
FUTURE_BLOCK_DECAY_TARGET_WEIGHT = 0.25
FUTURE_BLOCK_EXTRA_DECAY_START_DISTANCE = 3
FUTURE_BLOCK_EXTRA_DECAY_PER_BLOCK = 0.25
IRIS_GUIDANCE_TARGET_DISTANCE_WEIGHT = 0.5
IRIS_GUIDANCE_RESIDENCY_WEIGHT = 0.25
_DECAY_BASE = math.exp(math.log(FUTURE_BLOCK_DECAY_TARGET_WEIGHT) / float(FUTURE_BLOCK_DECAY_TARGET_DISTANCE))

@functools.lru_cache(maxsize=512)
def _node_sort_key(node):
    return (str(type(node)), str(node))

@functools.lru_cache(maxsize=16)
def _normalize_beam_sort_mode(sort_mode):
    mode = str(sort_mode).lower()
    if mode not in {'current_then_total', 'total_then_current'}:
        return DEFAULT_GATE_LOOKAHEAD_SORT_MODE
    return mode

@functools.lru_cache(maxsize=16)
def _normalize_beam_prune_mode(prune_mode):
    mode = str(prune_mode or DEFAULT_GATE_BEAM_PRUNE_MODE).lower()
    if mode not in {'scheduled_prefix_cost', 'selection_sort', 'current_teleports_only', 'selection_plus_current_teleports'}:
        return DEFAULT_GATE_BEAM_PRUNE_MODE
    return mode

@functools.lru_cache(maxsize=16)
def _normalize_future_block_decay_mode(decay_mode):
    mode = str(decay_mode or DEFAULT_FUTURE_BLOCK_DECAY_MODE).lower()
    if mode not in {'linear', 'none', 'dag_depth'}:
        return DEFAULT_FUTURE_BLOCK_DECAY_MODE
    return mode

def _future_block_effective_distance(start_block_index, gate_block_index, *, decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE, block_levels=None):
    return max(0, int(gate_block_index) - int(start_block_index))

def _future_block_decay_weight(start_block_index, gate_block_index, *, horizon_depth=None, decay_mode=DEFAULT_FUTURE_BLOCK_DECAY_MODE, block_levels=None):
    block_distance = _future_block_effective_distance(start_block_index, gate_block_index, decay_mode=decay_mode, block_levels=block_levels)
    if block_distance <= 0:
        return 1.0
    weight = _DECAY_BASE ** block_distance
    if horizon_depth is not None:
        extra_distance = max(0, block_distance - FUTURE_BLOCK_EXTRA_DECAY_START_DISTANCE)
        if extra_distance > 0:
            weight *= FUTURE_BLOCK_EXTRA_DECAY_PER_BLOCK ** extra_distance
    return weight

@functools.lru_cache(maxsize=1024)
def _rollout_window_upper(block_count, block_index, future_block_depth):
    if block_count <= 0 or block_index >= block_count:
        return block_index
    return min(block_count, block_index + 1 + max(0, int(future_block_depth)))


GENERAL_EXACT_SUFFIX_REFINEMENT_LOCAL_GATE_LIMIT = 2


GENERAL_EXACT_SUFFIX_REFINEMENT_MAX_ACTIONS = 3


GENERAL_EXACT_SUFFIX_REFINEMENT_PROXY_MARGIN = 2.0


@functools.lru_cache(maxsize=64)
def _effective_future_proxy_depth(lookahead_depth):
    return max(0, int(lookahead_depth))


MAX_EXACT_TIE_SUFFIX_REFINEMENT_DEPTH = 5


DIRECT_TIE_EXACT_REFINEMENT_BEAM_WIDTH = 4


DIRECT_TIE_EXACT_REFINEMENT_CANDIDATE_LIMIT = 4
