from .channel import link_capacity
from .constants import INF
from .lookahead import lookahead_cost
from .pathfinding import find_path_with_capacity, path_cost
def _fanout(node, gcache, ch):
    cnt = 0
    for nb in gcache.neighbors(node):
        if link_capacity(node, nb, ch) > 0:
            cnt += 1
    return cnt
def _score_candidate(node, pos_s, pos_t, s, t, qubit_positions,
                     future_pairs, gcache, ch):
    ds_val = gcache.sp_len(pos_s, node) if pos_s is not None else INF
    dt_val = gcache.sp_len(pos_t, node) if pos_t is not None else INF
    if ds_val is None:
        ds_val = INF
    if dt_val is None:
        dt_val = INF
    cs = path_cost(find_path_with_capacity(pos_s, node, ch, gcache=gcache)) if pos_s is not None else INF
    ct = path_cost(find_path_with_capacity(pos_t, node, ch, gcache=gcache)) if pos_t is not None else INF
    move_cost = min(cs, ct)
    if move_cost >= INF:
        la = INF
    else:
        pos_sim = dict(qubit_positions)
        if cs <= ct:
            pos_sim[s] = node
        else:
            pos_sim[t] = node
        la = lookahead_cost(pos_sim, future_pairs, gcache)
    fo = _fanout(node, gcache, ch)
    return (move_cost, la, ds_val + dt_val, -fo, str(node))
def compute_dynamic_agg(current_gate, remaining_gates, qubit_positions,
                        aggregation_node, connectivity, gcache, ch,
                        tie_eps=1e-12, eval_lookahead_depth=8,
                        PRINT_DEBUG=False, candidate_nodes=None):
    s, t = current_gate
    involved = {s, t}
    for gs, gt in remaining_gates:
        involved.add(gs)
        involved.add(gt)
    coords = []
    for q in involved:
        if q in qubit_positions:
            coords.append(gcache.node_coords(qubit_positions[q]))
    if not coords:
        return aggregation_node
    cx = sum(c[0] for c in coords) / len(coords); cy = sum(c[1] for c in coords) / len(coords); pos_s = qubit_positions.get(s); pos_t = qubit_positions.get(t); best_dsq = None; dsq_cands = []
    if candidate_nodes is None:
        node_iter = connectivity.nodes()
    else:
        node_iter = sorted(candidate_nodes, )
    for node in node_iter:
        if node not in connectivity.nodes:
            continue
        nc = gcache.node_coords(node); dsq = (nc[0] - cx) ** 2 + (nc[1] - cy) ** 2; d_end = INF
        if pos_s is not None:
            d = gcache.sp_len(node, pos_s)
            if d is not None:
                d_end = min(d_end, d)
        if pos_t is not None:
            d = gcache.sp_len(node, pos_t)
            if d is not None:
                d_end = min(d_end, d)
        if best_dsq is None or dsq < best_dsq - tie_eps:
            best_dsq = dsq
            dsq_cands = [(node, dsq, d_end)]
        elif abs(dsq - best_dsq) <= tie_eps:
            dsq_cands.append((node, dsq, d_end))
    if not dsq_cands:
        if candidate_nodes:
            return sorted(candidate_nodes, )[0]
        return aggregation_node
    best_d_end = min(d for (_, _, d) in dsq_cands)
    tied_nodes = [n for (n, _, d) in dsq_cands if d == best_d_end]
    if len(tied_nodes) == 1:
        return tied_nodes[0]
    future_pairs = remaining_gates[:eval_lookahead_depth]
    scored = [
        (n, _score_candidate(n, pos_s, pos_t, s, t, qubit_positions,
                             future_pairs, gcache, ch))
        for n in tied_nodes]
    scored.sort(key=lambda x: x[1])
    best_node = scored[0][0]
    return best_node