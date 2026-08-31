"""Window-Based Circuit Partitioning (WBCP)"""
import math
from collections import Counter, defaultdict
import networkx as nx
import pymetis

def _build_window_graph(gates, prev_partition=None):
    """Build an interaction graph for one window of 2-qubit gates."""
    edge_counts = defaultdict(int)
    active_qubits = set()
    for (q1, q2) in gates:
        key = (min(q1, q2), max(q1, q2))
        edge_counts[key] += 1
        active_qubits.add(q1)
        active_qubits.add(q2)
    G = nx.Graph()
    G.add_nodes_from(sorted(active_qubits))
    for ((q1, q2), count) in edge_counts.items():
        if prev_partition is not None:
            p1 = prev_partition.get(q1)
            p2 = prev_partition.get(q2)
            if p1 is not None and p2 is not None and (p1 == p2):
                weight = 2 * count
            else:
                weight = count
        else:
            weight = count
        G.add_edge(q1, q2, weight=weight)
    return G

def _partition_with_metis(G, num_partitions, capacity):
    """K-way partition of *G* using METIS, with overflow repair."""
    nodes = sorted(G.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    if num_partitions <= 1:
        return {node: 0 for node in nodes}
    if n <= num_partitions:
        return {node: i % num_partitions for (i, node) in enumerate(nodes)}
    node_to_idx = {node: idx for (idx, node) in enumerate(nodes)}
    xadj = [0]
    adjncy = []
    eweights = []
    for idx in range(n):
        node = nodes[idx]
        for neighbor in G.neighbors(node):
            adjncy.append(node_to_idx[neighbor])
            eweights.append(int(G[node][neighbor].get('weight', 1)))
        xadj.append(len(adjncy))
    vweights = [1] * n
    try:
        (_edgecut, partitions) = pymetis.part_graph(nparts=num_partitions, xadj=xadj, adjncy=adjncy, eweights=eweights, vweights=vweights)
    except Exception:
        partitions = [i % num_partitions for i in range(n)]
    part_sizes = Counter(partitions)
    for p in list(part_sizes):
        if part_sizes[p] <= capacity:
            continue
        overflow = [i for i in range(n) if partitions[i] == p]
        overflow.sort(key=lambda i: sum((G[nodes[i]][nodes[j]].get('weight', 1) for j in range(n) if j != i and partitions[j] == p and G.has_edge(nodes[i], nodes[j]))))
        while part_sizes[p] > capacity and overflow:
            node_idx = overflow.pop(0)
            for target_p in range(num_partitions):
                if target_p != p and part_sizes[target_p] < capacity:
                    partitions[node_idx] = target_p
                    part_sizes[p] -= 1
                    part_sizes[target_p] += 1
                    break
    return {nodes[i]: partitions[i] for i in range(n)}

def _nonlocal_gate_count(gates, partition):
    """Count gates whose endpoints land in different partitions."""
    cost = 0
    for (q1, q2) in gates:
        p1 = partition.get(q1)
        p2 = partition.get(q2)
        if p1 is not None and p2 is not None and (p1 != p2):
            cost += 1
    return cost

def _majority_vote_collapse(qubit_partition_weights, num_partitions, capacity, all_qubits):
    """Collapse per-window partitions → single static mapping."""
    preferences = []
    for q in sorted(all_qubits):
        pw = qubit_partition_weights.get(q, {})
        if pw:
            sorted_prefs = sorted(pw.items(), key=lambda x: -x[1])
        else:
            sorted_prefs = [(0, 0)]
        preferences.append((q, sorted_prefs))

    def _confidence(prefs):
        if len(prefs) <= 1:
            return prefs[0][1] if prefs else 0
        return prefs[0][1] - prefs[1][1]
    preferences.sort(key=lambda x: -_confidence(x[1]))
    partition_map = {}
    part_sizes = Counter()
    for (q, prefs) in preferences:
        assigned = False
        for (p, _w) in prefs:
            if part_sizes[p] < capacity:
                partition_map[q] = p
                part_sizes[p] += 1
                assigned = True
                break
        if not assigned:
            for p in range(num_partitions):
                if part_sizes[p] < capacity:
                    partition_map[q] = p
                    part_sizes[p] += 1
                    assigned = True
                    break
        if not assigned:
            partition_map[q] = 0
            part_sizes[0] += 1
    return partition_map

def wbcp_partition(program, num_qubits, num_partitions, chiplet_capacity, window_length=None, seed=0):
    T = len(program)
    if T == 0:
        return ({}, 0, 0)
    if window_length is None:
        window_length = max(50, T // 10)
    m = math.ceil(T / window_length)
    windows = []
    for i in range(m):
        start = i * window_length
        end = min((i + 1) * window_length, T)
        windows.append(program[start:end])
    all_qubits = set()
    for (q1, q2) in program:
        all_qubits.add(q1)
        all_qubits.add(q2)
    current_partition = {}
    total_ec = 0
    qubit_partition_weights = defaultdict(lambda : defaultdict(int))
    for (i, window) in enumerate(windows):
        if i == 0:
            G_w = _build_window_graph(window, prev_partition=None)
            new_partition = _partition_with_metis(G_w, num_partitions, chiplet_capacity)
            window_cost = _nonlocal_gate_count(window, new_partition)
            total_ec += window_cost
            current_partition = dict(new_partition)
        else:
            G_w = _build_window_graph(window, prev_partition=current_partition)
            active_qubits = set(G_w.nodes())
            if len(active_qubits) < 2:
                window_cost = _nonlocal_gate_count(window, current_partition)
                total_ec += window_cost
            else:
                new_partition = _partition_with_metis(G_w, num_partitions, chiplet_capacity)
                merged_new = dict(current_partition)
                merged_new.update(new_partition)
                moves = sum((1 for q in active_qubits if q in current_partition and q in new_partition and (current_partition[q] != new_partition[q])))
                ec_new = _nonlocal_gate_count(window, merged_new) + moves
                ec_old = _nonlocal_gate_count(window, current_partition)
                if ec_new <= ec_old:
                    current_partition = merged_new
                    total_ec += ec_new
                else:
                    total_ec += ec_old
        for (q1, q2) in window:
            if q1 in current_partition:
                qubit_partition_weights[q1][current_partition[q1]] += 1
            if q2 in current_partition:
                qubit_partition_weights[q2][current_partition[q2]] += 1
    final_partition = _majority_vote_collapse(qubit_partition_weights, num_partitions, chiplet_capacity, all_qubits)
    return (final_partition, total_ec, m)