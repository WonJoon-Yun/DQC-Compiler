"""Pure-Python reference implementations."""

def init_interact_info(interact_info, PRINT_DEBUG=False):
    if interact_info is None:
        return None
    ii = {q: list(gate_list) for (q, gate_list) in interact_info.items()}
    return ii

def _involved_qubits(future_gates):
    involved = set()
    for (s, t) in future_gates:
        involved.add(s)
        involved.add(t)
    return involved
from ..channel import link_capacity

def _deterministic_topology_shortest_path(src, dst, gcache):
    if src == dst:
        return [src]
    key = (src, dst)
    cached = gcache._paths.get(key)
    if cached is not None:
        return cached
    path = [src]
    curr = src
    while curr != dst:
        curr_dist = gcache.sp_len(curr, dst)
        if curr_dist is None or curr_dist <= 0:
            gcache._paths[key] = None
            return None
        next_hop = None
        for nb in gcache.neighbors(curr):
            nb_dist = gcache.sp_len(nb, dst)
            if nb_dist is not None and nb_dist == curr_dist - 1:
                next_hop = nb
                break
        if next_hop is None:
            gcache._paths[key] = None
            return None
        path.append(next_hop)
        curr = next_hop
    gcache._paths[key] = path
    return path

def anchor_convergence_cost(pos_map, future_gates, gcache, anchor_node, channel_dict=None):
    move_cost = 0
    release_penalty = 0
    edge_demand = {}
    for q in sorted(_involved_qubits(future_gates)):
        pq = pos_map.get(q)
        if pq is None or pq == anchor_node:
            continue
        d = gcache.sp_len(pq, anchor_node)
        if d is None:
            return (float('inf'), float('inf'), float('inf'))
        move_cost += d
        if not channel_dict:
            continue
        path = _deterministic_topology_shortest_path(pq, anchor_node, gcache)
        if path is None:
            return (float('inf'), float('inf'), float('inf'))
        for i in range(len(path) - 1):
            edge = (path[i], path[i + 1])
            edge_demand[edge] = edge_demand.get(edge, 0) + 1
    if channel_dict:
        for ((u, v), demand) in edge_demand.items():
            release_penalty += max(0, demand - link_capacity(u, v, channel_dict))
    return (move_cost, release_penalty, move_cost + release_penalty)

def lookahead_cost(pos_map, future_gates, gcache, anchor_node=None, channel_dict=None, include_release_penalty=False):
    if anchor_node is not None:
        (move_cost, release_penalty, total_cost) = anchor_convergence_cost(pos_map, future_gates, gcache, anchor_node, channel_dict=channel_dict if include_release_penalty else None)
        if include_release_penalty:
            return total_cost
        return move_cost
    total = 0
    for (s, t) in future_gates:
        ps = pos_map.get(s)
        pt = pos_map.get(t)
        if ps is None or pt is None or ps == pt:
            continue
        d = gcache.sp_len(ps, pt)
        if d is not None:
            total += d
    return total