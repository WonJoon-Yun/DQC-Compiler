from .lookahead import anchor_convergence_cost
from .pathfinding import find_path_with_capacity, path_cost
from .lookahead import lookahead_cost
from .pathfinding import path_cost
ONE_MEET_TIEBREAK_ORIGINAL = 'original'
ONE_MEET_TIEBREAK_LEGACY_DIRECT = 'legacy_direct'
ONE_MEET_SELECTION_SORTED_COST_ORDER = 'sorted_cost_order'
ONE_MEET_TIEBREAK_MODES = (ONE_MEET_TIEBREAK_ORIGINAL, ONE_MEET_TIEBREAK_LEGACY_DIRECT)

def _simulate_channel_after_path(ch, path):
    """Return channel map after consuming one unit along `path`."""
    ch_after = dict(ch)
    for i in range(len(path) - 1):
        (u, v) = (path[i], path[i + 1])
        ch_after[u, v] = ch_after.get((u, v), 0) + 1
        ch_after[v, u] = ch_after.get((v, u), 0) - 1
    return ch_after

def _node_sort_key(node):
    return str(node)

def _future_gates_all_local(pos_map, future_gates):
    for (s, t) in future_gates:
        ps = pos_map.get(s)
        pt = pos_map.get(t)
        if ps is None or pt is None or ps != pt:
            return False
    return True

def _collect_meeting_nodes(pos_s, pos_t, dyn_agg, gcache, allowed_nodes=None):
    """Deterministic candidate set for one-sided meeting."""
    if allowed_nodes is not None:
        return sorted(set(allowed_nodes))
    seeds = {pos_s, pos_t, dyn_agg}
    out = set()
    for node in seeds:
        if node is None:
            continue
        out.add(node)
    for node in list(seeds):
        if node is None:
            continue
        for nb in gcache.neighbors(node):
            out.add(nb)
    return sorted(out)

def _evaluate_meeting_candidate(move_qubit, src_pos, meet_pos,
                                partner_pos, qubit_positions, future_gates,
                                future_touches, dyn_agg, tie_bias,
                                ch, gcache, disable_future_touch=False,
                                double_count_future_ops=False):
    p = find_path_with_capacity(src_pos, meet_pos, ch, gcache=gcache)
    if p is None:
        return None
    d = path_cost(p)
    if d <= 0:
        return None

    topo_dist = gcache.sp_len(src_pos, meet_pos)
    if topo_dist is None:
        return None
    # The experimental "revised cost func" variant is currently selected via
    # `disable_future_touch=True`. Keep the legacy scorer unchanged unless that
    # variant is explicitly requested.
    use_revised_costfn = disable_future_touch
    blocked_teleport = d > topo_dist
    teleport_cost = (2 * d) if (use_revised_costfn and blocked_teleport) else d

    pos_sim = dict(qubit_positions)
    pos_sim[move_qubit] = meet_pos
    future_all_local = _future_gates_all_local(pos_sim, future_gates)
    if future_all_local:
        anchor_move_la = 0
        anchor_release_penalty = 0
        anchor_la = 0
        legacy_la = 0
    else:
        ch_after = _simulate_channel_after_path(ch, p)
        anchor_move_la, anchor_release_penalty, anchor_la = anchor_convergence_cost(
            pos_sim,
            future_gates,
            gcache,
            meet_pos,
            channel_dict=ch_after,
        )
        legacy_la = lookahead_cost(
            pos_sim,
            future_gates,
            gcache,
        )

    la = anchor_la
    if use_revised_costfn and double_count_future_ops:
        la = legacy_la

    post_pair_dist = gcache.sp_len(meet_pos, partner_pos)
    if post_pair_dist is None:
        return None

    future_touch_count = future_touches.get(move_qubit, 0)
    future_touch_penalty = 0
    if not use_revised_costfn:
        future_touch_penalty = max(0, future_touch_count - 1)
    effective_la = la + future_touch_penalty
    agg_bias = 0 if meet_pos == dyn_agg else 1
    channel_imbalance = None

    return {
        'meeting_node': meet_pos,
        'move_qubit': move_qubit,
        'path': p,
        'dist': d,
        'topo_dist': topo_dist,
        'blocked_teleport': blocked_teleport,
        'teleport_cost': teleport_cost,
        'lookahead': la,
        'anchor_lookahead': anchor_la,
        'anchor_move_lookahead': anchor_move_la,
        'anchor_release_penalty': anchor_release_penalty,
        'legacy_lookahead': legacy_la,
        'future_all_local': future_all_local,
        'post_pair_dist': post_pair_dist,
        'future_touches': future_touch_count,
        'future_touch_penalty': future_touch_penalty,
        'ping_pong_penalty': 0.0,
        'stay_local_run': 0,
        'meet_local_run': 0,
        'effective_lookahead': effective_la,
        'channel_imbalance': channel_imbalance,
        'agg_bias': agg_bias,
        'tie_bias': tie_bias,
    }

def find_best_one_sided_meet(pos_s, pos_t, s, t, future_gates,
                             qubit_positions, dyn_agg, ch, gcache,
                             candidate_nodes=None,
                             tiebreak_mode=ONE_MEET_TIEBREAK_LEGACY_DIRECT,
                             disable_searchspace=False,
                             disable_costfn=False,
                             disable_future_touch=False,
                             double_count_future_ops=False,
                             PRINT_DEBUG=False):
    cands = enumerate_one_sided_meet_candidates(
        pos_s, pos_t, s, t, future_gates,
        qubit_positions, dyn_agg, ch, gcache,
        candidate_nodes=candidate_nodes,
        tiebreak_mode=tiebreak_mode,
        disable_searchspace=disable_searchspace,
        disable_costfn=disable_costfn,
        disable_future_touch=disable_future_touch,
        double_count_future_ops=double_count_future_ops,
        PRINT_DEBUG=PRINT_DEBUG,
    )
    if not cands:
        return None
    best, selected_key, selection_mode = select_one_sided_meet_candidate(
        cands,
        pos_s,
        pos_t,
        s,
        t,
    )
    if best is None:
        return None
    best['selected_key'] = selected_key
    best['selection_mode'] = selection_mode
    return best

def select_one_sided_meet_candidate(cands, pos_s, pos_t, s, t):
    if not cands:
        return (None, None, None)
    best = cands[0]
    return (best, best.get('cost_key'), ONE_MEET_SELECTION_SORTED_COST_ORDER)

def enumerate_one_sided_meet_candidates(pos_s, pos_t, s, t, future_gates,
                                        qubit_positions, dyn_agg, ch, gcache,
                                        candidate_nodes=None,
                                        tiebreak_mode=ONE_MEET_TIEBREAK_LEGACY_DIRECT,
                                        disable_searchspace=False,
                                        disable_costfn=False,
                                        disable_future_touch=False,
                                        double_count_future_ops=False,
                                        PRINT_DEBUG=False):
    if disable_searchspace:
        meet_nodes = sorted({pos_s, pos_t})
    else:
        meet_nodes = _collect_meeting_nodes(
            pos_s, pos_t, dyn_agg, gcache, allowed_nodes=candidate_nodes
        )
    future_touches = _count_future_touches(future_gates)
    cands = []

    for meet in meet_nodes:
        result = _evaluate_meeting_candidate(
            s, pos_s, meet, pos_t, qubit_positions, future_gates,
            future_touches, dyn_agg, 0, ch, gcache,
            disable_future_touch=disable_future_touch,
            double_count_future_ops=double_count_future_ops)
        if result is not None:
            cands.append(result)

        result = _evaluate_meeting_candidate(
            t, pos_t, meet, pos_s, qubit_positions, future_gates,
            future_touches, dyn_agg, 1, ch, gcache,
            disable_future_touch=disable_future_touch,
            double_count_future_ops=double_count_future_ops)
        if result is not None:
            cands.append(result)

    if not cands:
        return []

    if tiebreak_mode not in ONE_MEET_TIEBREAK_MODES:
        raise ValueError(
            f"Unknown one-meet tiebreak_mode={tiebreak_mode}. "
            f"Supported: {ONE_MEET_TIEBREAK_MODES}"
        )

    # Historical our_qucomm scorer:
    #   immediate completion cost -> effective lookahead -> structural fields.
    #
    # Experimental cost-disabled mode:
    #   use an Anbang-compatible direct cost as the primary term
    #   (move distance + pairwise legacy lookahead), extended with
    #   post_pair_dist for extra one-meet-only meeting nodes.
    use_anbang_direct_tie_break = (
        not disable_costfn and
        tiebreak_mode == ONE_MEET_TIEBREAK_LEGACY_DIRECT and
        _should_apply_anbang_direct_tie_break(cands, pos_s, pos_t, s, t)
    )
    for c in cands:
        c['use_anbang_direct_tie_break'] = use_anbang_direct_tie_break
        c['anbang_compat_rank'] = _anbang_compat_rank(
            c, pos_s, pos_t, s, t, use_anbang_direct_tie_break
        )
        c['original_cost_key'] = (
            c['teleport_cost'] + c['post_pair_dist'],
            c['effective_lookahead'],
            c['agg_bias'],
            c['teleport_cost'],
            c['post_pair_dist'],
            _node_sort_key(c['meeting_node']),
            c['move_qubit'],
            tuple(c['path']),
        )
        c['anbang_cost_key'] = (
            c['dist'] + c['post_pair_dist'] + c['legacy_lookahead'],
            _anbang_like_one_meet_priority(c, pos_s, pos_t, s, t),
            c['dist'] + c['post_pair_dist'],
            c['legacy_lookahead'],
            _node_sort_key(c['meeting_node']),
            c['move_qubit'],
            tuple(c['path']),
        )
        c['cost_key'] = (
            c['anbang_cost_key']
            if disable_costfn
            else c['original_cost_key']
        )
    cands.sort(
        key=lambda x: (
            x['cost_key'],
            x['move_qubit'],
            tuple(x['path']),
        )
    )

    if PRINT_DEBUG:
        best, selected_key, selection_mode = select_one_sided_meet_candidate(
            cands,
            pos_s,
            pos_t,
            s,
            t,
        )
        for c in cands:
            print(f"    [ONE-MEET*] target@{c['meeting_node']} move q{c['move_qubit']} "
                  f"d={c['dist']} td={c['topo_dist']} blocked={c['blocked_teleport']} "
                  f"tc={c['teleport_cost']} future_local={c['future_all_local']} "
                  f"post={c['post_pair_dist']} la={c['lookahead']:.1f} "
                  f"amla={c['anchor_move_lookahead']:.1f} "
                  f"arls={c['anchor_release_penalty']:.1f} "
                  f"ft={c['future_touches']} pen={c['future_touch_penalty']} "
                  f"pp={c['ping_pong_penalty']:.1f} "
                  f"run={c['stay_local_run']}→{c['meet_local_run']} "
                  f"ela={c['effective_lookahead']:.1f} "
                  f"imb={c['channel_imbalance']} "
                  f"key={c['cost_key']}")
        print(f"    [ONE-MEET*] ★ pick target@{best['meeting_node']} "
              f"move q{best['move_qubit']} policy={selection_mode} "
              f"selected_key={selected_key}")

    return cands

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


def _is_direct_ab_candidate(candidate, pos_s, pos_t, s, t):
    meet = candidate['meeting_node']
    move_qubit = candidate['move_qubit']
    return (
        (meet == pos_s and move_qubit == t) or
        (meet == pos_t and move_qubit == s)
    )


def _count_future_touches(future_gates):
    counts = {}
    for gs, gt in future_gates:
        counts[gs] = counts.get(gs, 0) + 1
        counts[gt] = counts.get(gt, 0) + 1
    return counts


def _should_apply_anbang_direct_tie_break(cands, pos_s, pos_t, s, t):
    """Only activate Anbang ordering for true direct A/B legacy ties.

    The mode is meant to be a tie-break, not a new primary scorer. We therefore
    only intervene when both direct endpoint candidates exist and their legacy
    direct costs are exactly tied.
    """
    direct_a = None
    direct_b = None

    for candidate in cands:
        meet = candidate['meeting_node']
        move_qubit = candidate['move_qubit']
        if meet == pos_s and move_qubit == t:
            direct_a = candidate
        elif meet == pos_t and move_qubit == s:
            direct_b = candidate

    if direct_a is None or direct_b is None:
        return False

    direct_a_cost = direct_a['dist'] + direct_a['legacy_lookahead']
    direct_b_cost = direct_b['dist'] + direct_b['legacy_lookahead']
    return direct_a_cost == direct_b_cost


def _anbang_compat_rank(candidate, pos_s, pos_t, s, t, use_direct_tie_break):
    """Compatibility rank against Anbang's direct A/B tie-breaking.

    This is intentionally narrow: only when the direct endpoint A/B choices
    exist and have the same legacy direct cost do we prefer A over B and place
    extra one-meet-only candidates after them. Otherwise we return a neutral
    rank and preserve the original our_qucomm ordering.
    """
    if not use_direct_tie_break:
        return (1,)

    family = _anbang_like_one_meet_priority(candidate, pos_s, pos_t, s, t)
    if _is_direct_ab_candidate(candidate, pos_s, pos_t, s, t):
        return (0, family)
    return (1,)


def _anbang_like_one_meet_priority(candidate, pos_s, pos_t, s, t):
    """Match Anbang-style tie priority as closely as possible.

    Mapping from current one-meet candidates to legacy teleport families:
    - A / fcost1: move t directly to s's current node
    - B / fcost2: move s directly to t's current node
    - D / fcost4: other candidates that move t
    - E / fcost5: other candidates that move s

    our_qucomm has more meeting-node choices than anbang_qucomm, so non-direct
    one-meet options are placed after the direct A/B-style moves.
    """
    meet = candidate['meeting_node']
    move_qubit = candidate['move_qubit']

    if meet == pos_s and move_qubit == t:
        return 1
    if meet == pos_t and move_qubit == s:
        return 2
    if move_qubit == t:
        return 4
    if move_qubit == s:
        return 5
    return 6
