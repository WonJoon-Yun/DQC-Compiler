from ...constants import INF
from ._helpers import _node_sort_key

def _teleport_option_arrival_node(label, info):
    if label in {'A', 'B'}:
        path = info.get('path', [])
    elif label in {'D', 'E'}:
        path = info.get('main_path', [])
    else:
        path = []
    if not path:
        return None
    return path[-1]

def _teleport_option_sort_key(option):
    (cost, label, info) = option
    arrival = _teleport_option_arrival_node(label, info)
    label_priority = {'A': 1, 'B': 2, 'D': 4, 'E': 5}.get(label, INF)
    if label in {'A', 'B'}:
        aux = (tuple(info.get('path', [])),)
    else:
        aux = (tuple(info.get('main_path', [])), tuple(info.get('displace_path', [])), info.get('q_d'), _node_sort_key(info.get('dest')))
    return (cost, label_priority, _node_sort_key(arrival), aux)

def _teleport_action_from_option(option):
    (_cost, label, info) = option
    action = {'mode': 'teleport', 'label': label}
    if label in {'A', 'B'}:
        action['path'] = list(info.get('path', []))
        return action
    action['q_d'] = info.get('q_d')
    action['dest'] = info.get('dest')
    action['displace_path'] = list(info.get('displace_path', []))
    action['main_path'] = list(info.get('main_path', []))
    return action

def _teleport_action_matches_option(action, option):
    if not action or action.get('mode') != 'teleport':
        return False
    (_cost, label, info) = option
    if action.get('label') != label:
        return False
    if label in {'A', 'B'}:
        return list(action.get('path', [])) == list(info.get('path', []))
    return action.get('q_d') == info.get('q_d') and action.get('dest') == info.get('dest') and (list(action.get('displace_path', [])) == list(info.get('displace_path', []))) and (list(action.get('main_path', [])) == list(info.get('main_path', [])))

def _hybrid_one_meet_cost(candidate, disable_costfn):
    """Scalar comparator for hybrid teleport-vs-one-meet selection.

    Keep exact Anbang-compatible mode on the legacy pairwise lookahead path.
    Otherwise use the same one-meet score components that selected the
    candidate in `find_best_one_sided_meet`, so revised-cost variants do not
    silently fall back to legacy lookahead during the hybrid decision.
    """
    if disable_costfn:
        return (
            candidate['dist']
            + candidate['post_pair_dist']
            + candidate['legacy_lookahead']
        )
    return (
        candidate['teleport_cost']
        + candidate['post_pair_dist']
        + candidate['effective_lookahead']
    )
