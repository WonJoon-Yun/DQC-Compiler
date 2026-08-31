from .constants import INF
from .lookahead import lookahead_cost
def _build_dep_graph(gates):
    n = len(gates); preds = [set() for _ in range(n)]; succs = [set() for _ in range(n)]; last_on_qubit = {}
    for i, (a, b) in enumerate(gates):
        for q in (a, b):
            if q in last_on_qubit:
                p = last_on_qubit[q]
                preds[i].add(p)
                succs[p].add(i)
            last_on_qubit[q] = i
    return preds, succs
def _estimate_gate_score(i, gates, pos_map, remaining_indices,
                         lookahead_depth, gcache):
    s, t = gates[i]
    ps, pt = pos_map[s], pos_map[t]
    d = gcache.sp_len(ps, pt)
    if d is None:
        d = INF
    future_pairs = [gates[j] for j in remaining_indices[:lookahead_depth]]
    pos_a = dict(pos_map)
    pos_a[s] = pt
    la_a = lookahead_cost(pos_a, future_pairs, gcache)
    pos_b = dict(pos_map)
    pos_b[t] = ps
    la_b = lookahead_cost(pos_b, future_pairs, gcache)
    return (d, min(la_a, la_b), i)
def reorder_gates(gates, pos0, lookahead_depth, gcache):
    n = len(gates)
    preds, succs = _build_dep_graph(gates)
    indeg = [len(preds[i]) for i in range(n)]; ready = {i for i in range(n) if indeg[i] == 0}; order = []; sim_pos = dict(pos0); remaining = list(range(n))
    while ready:
        unscheduled = [j for j in remaining if j not in set(order)]
        best_i, best_score = None, None
        for i in sorted(ready):
            score = _estimate_gate_score(i, gates, sim_pos, unscheduled, lookahead_depth, gcache)
            if best_score is None or score < best_score:
                best_score = score
                best_i = i
        order.append(best_i)
        ready.remove(best_i)
        s, t = gates[best_i]
        ps, pt = sim_pos[s], sim_pos[t]
        if ps != pt:
            remaining_after = [gates[j] for j in unscheduled if j != best_i][:lookahead_depth]; d = gcache.sp_len(ps, pt); d = d if d is not None else INF; pos_a = dict(sim_pos)
            pos_a[s] = pt
            la_a = lookahead_cost(pos_a, remaining_after, gcache)
            pos_b = dict(sim_pos)
            pos_b[t] = ps
            la_b = lookahead_cost(pos_b, remaining_after, gcache)
            if (d, la_a) <= (d, la_b):
                sim_pos[s] = pt
            else:
                sim_pos[t] = ps
        for j in succs[best_i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.add(j)
    return [gates[i] for i in order]