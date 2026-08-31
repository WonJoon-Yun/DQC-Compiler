from collections import Counter
import networkx as nx

def get_agg_node(gates_in_block, position_at_t, connectivity, exclude_nodes=None, print_debug=False):

    def node_sort_key(node):
        return (str(type(node)), str(node))

    def deterministic_min(nodes):
        return min(nodes, key=node_sort_key)

    def sp_path_undirected(u, v):
        if u == v:
            return [u]
        try:
            return nx.shortest_path(connectivity, source=u, target=v)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def sp_length_undirected(u, v):
        if u == v:
            return 0
        try:
            return nx.shortest_path_length(connectivity, source=u, target=v)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return float('inf')

    excluded = set(exclude_nodes or [])
    active_qubits = set()
    for (a, b) in gates_in_block:
        active_qubits.add(a)
        active_qubits.add(b)
    eligible_nodes = sorted([n for n in connectivity.nodes if n not in excluded], key=node_sort_key)
    if not eligible_nodes:
        raise ValueError('No eligible aggregation nodes remain after applying exclude_nodes')
    if not active_qubits:
        return deterministic_min(eligible_nodes)
    try:
        qubit_positions = {q: position_at_t[q] for q in active_qubits}
    except KeyError as e:
        missing = e.args[0]
        raise ValueError(f'Missing position for qubit {missing} in position_at_t') from None
    already_here_count = Counter(qubit_positions.values())
    best_node = None
    best_cost = 10 ** 18
    best_already_here = -1
    infeasible_best_node = None
    infeasible_best_cost = float('inf')
    infeasible_best_already_here = -1
    for candidate in eligible_nodes:
        total_cost = 0
        feasible = True
        debug_paths = []
        qubits_ordered = sorted(qubit_positions.items(), key=lambda kv: (-sp_length_undirected(kv[1], candidate), node_sort_key(kv[1]), node_sort_key(kv[0])))
        for (_, start) in qubits_ordered:
            path = sp_path_undirected(start, candidate)
            debug_paths.append(path)
            if path is None:
                feasible = False
                total_cost = 10 ** 15
                break
            total_cost += len(path) - 1
        if print_debug:
            print(f'[DEBUG] Candidate {candidate}: cost={total_cost}, already_here={already_here_count[candidate]}, feasible={feasible}, paths={debug_paths}')
        ah = already_here_count[candidate]
        if not feasible:
            if total_cost < infeasible_best_cost or (total_cost == infeasible_best_cost and ah > infeasible_best_already_here) or (total_cost == infeasible_best_cost and ah == infeasible_best_already_here and (infeasible_best_node is None or node_sort_key(candidate) < node_sort_key(infeasible_best_node))):
                infeasible_best_node = candidate
                infeasible_best_cost = total_cost
                infeasible_best_already_here = ah
            continue
        if total_cost < best_cost or (total_cost == best_cost and ah > best_already_here) or (total_cost == best_cost and ah == best_already_here and (best_node is None or node_sort_key(candidate) < node_sort_key(best_node))):
            best_node = candidate
            best_cost = total_cost
            best_already_here = ah
    if best_node is not None:
        if print_debug:
            print(f'[DEBUG] Best node by cost rule: {best_node} (cost={best_cost})')
        return best_node
    if infeasible_best_node is not None:
        if print_debug:
            print(f'[DEBUG] No feasible candidate. Choosing least-cost infeasible node: {infeasible_best_node} (proxy_cost={infeasible_best_cost})')
        return infeasible_best_node
    raise ValueError('Failed to select an aggregation node under current constraints.')