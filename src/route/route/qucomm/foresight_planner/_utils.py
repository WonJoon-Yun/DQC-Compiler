import copy
from ....gate_utils import normalize_block_to_gates
from ....interact import init_interact_info
from ..gate_rollout_planner import DEFAULT_GATE_LOOKAHEAD_SORT_MODE, _beam_sort_key

def _forced_plans_by_block_from_actions(actions):
    forced_plans_by_block = {}
    for (spec, action) in actions:
        if action.get('mode') not in {'one_meet', 'teleport'}:
            continue
        forced_plans_by_block.setdefault(spec['block_index'], {})[spec['local_gate_index']] = copy.deepcopy(action)
    return forced_plans_by_block

def _flatten_all_gate_specs(blocks, block_ids, start_block_index=0):
    specs = []
    plan_index = 0
    for block_index in range(start_block_index, len(blocks)):
        for (local_gate_index, gate) in enumerate(normalize_block_to_gates(blocks[block_index])):
            specs.append({'block_index': block_index, 'block_id': block_ids[block_index], 'local_gate_index': local_gate_index, 'global_gate_index': plan_index, 'gate': gate})
            plan_index += 1
    return specs

def _snapshot_state(position_table, channel_dict, atom_paths, interact_info=None):
    snapshot = {'position_table': position_table.copy(), 'channel_dict': channel_dict.copy(), 'atom_paths': {k: list(v) for (k, v) in atom_paths.items()}}
    if interact_info is not None:
        snapshot['interact_info'] = init_interact_info(interact_info, PRINT_DEBUG=False)
    return snapshot

def _wrap_simulate_result(result):
    state = {'position_table': result['position_table'], 'channel_dict': result['channel_dict'], 'atom_paths': result['atom_paths']}
    if result.get('interact_info') is not None:
        state['interact_info'] = result['interact_info']
    return state

def _copy_predicted_state(state):
    snapshot = {'position_table': state['position_table'].copy(), 'channel_dict': state['channel_dict'].copy(), 'atom_paths': {k: list(v) for (k, v) in state['atom_paths'].items()}}
    if state.get('interact_info') is not None:
        snapshot['interact_info'] = init_interact_info(state['interact_info'], PRINT_DEBUG=False)
    return snapshot

def _build_block_end_gate_indices(gate_specs):
    block_end_indices = {}
    for (gate_index, spec) in enumerate(gate_specs):
        block_end_indices[spec['block_index']] = gate_index
    return block_end_indices

def _beam_sort_key_without_action_tuple(node, sort_mode=DEFAULT_GATE_LOOKAHEAD_SORT_MODE):
    return _beam_sort_key(node, sort_mode)[:-1]

def _current_block_forced_signature_from_node(node, gate_specs, current_block_end_gate_index, current_block_index):
    prefix_actions = node['actions'][:current_block_end_gate_index + 1]
    signature = []
    for (spec, action) in prefix_actions:
        if spec['block_index'] != current_block_index:
            continue
        if action['mode'] not in {'one_meet', 'teleport'}:
            continue
        signature.append((spec['local_gate_index'], action['mode'], tuple(action.get('meeting_node')) if action.get('meeting_node') is not None else None, action.get('move_qubit')))
    return tuple(signature)

def _current_block_forced_signature_from_plan(forced_plan):
    if not forced_plan:
        return ()
    signature = []
    for local_gate_index in sorted(forced_plan):
        action = forced_plan[local_gate_index]
        signature.append((local_gate_index, action['mode'], tuple(action.get('meeting_node')) if action.get('meeting_node') is not None else None, action.get('move_qubit')))
    return tuple(signature)
