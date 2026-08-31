from collections import Counter, defaultdict
import numpy as np

def _build_layers(program, num_qubits):
    n = len(program)
    if n == 0:
        return []
    last_gate = {}
    deps = [[] for _ in range(n)]
    dep_count = [0] * n
    for (idx, (q0, q1)) in enumerate(program):
        if q0 in last_gate:
            deps[last_gate[q0]].append(idx)
            dep_count[idx] += 1
        if q1 in last_gate:
            prev = last_gate[q1]
            if prev != last_gate.get(q0, -1):
                deps[prev].append(idx)
                dep_count[idx] += 1
        last_gate[q0] = idx
        last_gate[q1] = idx
    ready = [i for i in range(n) if dep_count[i] == 0]
    assigned = [False] * n
    layers = []
    while ready:
        layer = []
        used = set()
        next_ready = []
        still_ready = []
        for idx in ready:
            (q0, q1) = program[idx]
            if q0 not in used and q1 not in used:
                layer.append((q0, q1))
                used.add(q0)
                used.add(q1)
                assigned[idx] = True
                for child in deps[idx]:
                    dep_count[child] -= 1
                    if dep_count[child] == 0:
                        next_ready.append(child)
            else:
                still_ready.append(idx)
        layers.append(layer)
        ready = still_ready + next_ready
    return layers

def _precompute_gate_arrays(layers):
    (gl, g0, g1) = ([], [], [])
    for (l, layer_gates) in enumerate(layers):
        for (q0, q1) in layer_gates:
            gl.append(l)
            g0.append(q0)
            g1.append(q1)
    return (np.array(gl, dtype=np.int32), np.array(g0, dtype=np.int32), np.array(g1, dtype=np.int32))

def _build_gate_partners(layers, d):
    """gate_partners[l][q] = list of partner qubits at layer l."""
    gp = [defaultdict(list) for _ in range(d)]
    for (l, layer_gates) in enumerate(layers):
        for (q0, q1) in layer_gates:
            gp[l][q0].append(q1)
            gp[l][q1].append(q0)
    return gp

def _cost_gcps(phi, gate_layers, gate_q0s, gate_q1s):
    """GCP-S cost: number of cut state edges + cut gate edges."""
    state_cost = int(np.count_nonzero(phi[:-1] != phi[1:]))
    if len(gate_layers) == 0:
        return state_cost
    gate_cost = int(np.count_nonzero(phi[gate_layers, gate_q0s] != phi[gate_layers, gate_q1s]))
    return state_cost + gate_cost

def _identify_gate_groups(layers, d):
    qubit_gates = defaultdict(list)
    for (l, layer_gates) in enumerate(layers):
        for (q0, q1) in layer_gates:
            qubit_gates[q0].append((l, q1))
            qubit_gates[q1].append((l, q0))
    candidate_groups = []
    for q in sorted(qubit_gates.keys()):
        gates = qubit_gates[q]
        if len(gates) < 2:
            continue
        candidate_groups.append((q, gates))
    candidate_groups.sort(key=lambda x: -len(x[1]))
    assigned = set()
    final_groups = []
    for (control_q, gates) in candidate_groups:
        available = []
        for (l, partner) in gates:
            gate_key = (l, min(control_q, partner), max(control_q, partner))
            if gate_key not in assigned:
                available.append((l, partner))
        if len(available) < 2:
            continue
        final_groups.append((control_q, available))
        for (l, partner) in available:
            gate_key = (l, min(control_q, partner), max(control_q, partner))
            assigned.add(gate_key)
    return final_groups

def _build_gcpe_edges(layers, d, groups):
    """Build GCP-E redirected edge list."""
    grouped_gates = {}
    for (control_q, group) in groups:
        first_layer = group[0][0]
        for (l, partner) in group:
            gate_key = (l, min(control_q, partner), max(control_q, partner))
            grouped_gates[gate_key] = (control_q, first_layer)
    edges = []
    for (l, layer_gates) in enumerate(layers):
        for (q0, q1) in layer_gates:
            gate_key = (l, min(q0, q1), max(q0, q1))
            if gate_key in grouped_gates:
                (control_q, first_layer) = grouped_gates[gate_key]
                partner = q1 if control_q == q0 else q0
                edges.append((control_q, first_layer, partner, l))
            else:
                edges.append((q0, l, q1, l))
    return edges

def _cost_gcpe(phi, gcpe_edges, num_chiplets):
    state_cost = int(np.count_nonzero(phi[:-1] != phi[1:]))
    source_targets = defaultdict(set)
    for (src_q, src_l, tgt_q, tgt_l) in gcpe_edges:
        src_qpu = phi[src_l, src_q]
        tgt_qpu = phi[tgt_l, tgt_q]
        if src_qpu != tgt_qpu:
            source_targets[src_q, src_l].add(tgt_qpu)
    gate_cost = sum((len(qpus) for qpus in source_targets.values()))
    return state_cost + gate_cost

def _random_balanced_row(n_total, num_chiplets, chiplet_capacities, rng):
    labels = np.empty(n_total, dtype=np.int32)
    idx = 0
    for k in range(num_chiplets):
        cap = chiplet_capacities[k]
        labels[idx:idx + cap] = k
        idx += cap
    if idx < n_total:
        labels[idx:] = num_chiplets - 1
    rng.shuffle(labels)
    return labels

def _crossover(pa, pb, d, rng):
    """Single-point crossover by row (layer)."""
    pt = rng.integers(1, d)
    ca = np.vstack([pa[:pt], pb[pt:]])
    cb = np.vstack([pb[:pt], pa[pt:]])
    return (ca, cb)

def _swap_gain(phi, gate_partners, qi, qj, l, d):
    """KL gain from swapping phi[l][qi] and phi[l][qj]."""
    pa = phi[l, qi]
    pb = phi[l, qj]
    if pa == pb:
        return 0
    i_to_a = i_to_b = 0
    if l > 0:
        p = phi[l - 1, qi]
        i_to_a += p == pa
        i_to_b += p == pb
    if l < d - 1:
        p = phi[l + 1, qi]
        i_to_a += p == pa
        i_to_b += p == pb
    for partner in gate_partners[l].get(qi, ()):
        if partner == qj:
            continue
        p = phi[l, partner]
        i_to_a += p == pa
        i_to_b += p == pb
    j_to_a = j_to_b = 0
    if l > 0:
        p = phi[l - 1, qj]
        j_to_a += p == pa
        j_to_b += p == pb
    if l < d - 1:
        p = phi[l + 1, qj]
        j_to_a += p == pa
        j_to_b += p == pb
    for partner in gate_partners[l].get(qj, ()):
        if partner == qi:
            continue
        p = phi[l, partner]
        j_to_a += p == pa
        j_to_b += p == pb
    return i_to_b - i_to_a + (j_to_a - j_to_b)

def _mutation(cand, gate_partners, n_total, d, rng, k=10):
    l0 = rng.integers(0, d)
    l1 = rng.integers(l0, d)
    for _ in range(k):
        qi = rng.integers(0, n_total)
        qj = rng.integers(0, n_total)
        if qi == qj:
            continue
        for l in range(l0, l1 + 1):
            if cand[l, qi] == cand[l, qj]:
                continue
            if _swap_gain(cand, gate_partners, qi, qj, l, d) > 0:
                (cand[l, qi], cand[l, qj]) = (cand[l, qj], cand[l, qi])
    return cand

def _majority_vote_balanced(phi, num_qubits, num_chiplets, chiplet_capacities):
    prefs = []
    for q in range(num_qubits):
        counts = Counter(phi[:, q].tolist())
        ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        prefs.append((q, ranked))
    prefs.sort(key=lambda x: -x[1][0][1])
    result = {}
    capacity_left = {k: chiplet_capacities[k] for k in range(num_chiplets)}
    for (q, ranked) in prefs:
        placed = False
        for (chiplet_id, _) in ranked:
            if capacity_left[chiplet_id] > 0:
                result[q] = chiplet_id
                capacity_left[chiplet_id] -= 1
                placed = True
                break
        if not placed:
            for k in range(num_chiplets):
                if capacity_left[k] > 0:
                    result[q] = k
                    capacity_left[k] -= 1
                    break
    return result

def gcp_partition(program, num_qubits, num_chiplets, chiplet_capacity, chiplet_capacities=None, population_size=50, num_generations=100, mutation_k=10, seed=42, variant='GCP-S'):
    """Run GCP genetic algorithm to partition qubits to chiplets."""
    rng = np.random.default_rng(seed)
    use_gcpe = variant.upper() == 'GCP-E'
    if chiplet_capacities is None:
        chiplet_capacities = [chiplet_capacity] * num_chiplets
    layers = _build_layers(program, num_qubits)
    d = len(layers)
    if d == 0:
        return ({q: q % num_chiplets for q in range(num_qubits)}, 0)
    n_total = sum(chiplet_capacities)
    if n_total < num_qubits:
        raise ValueError(f'Total chiplet capacity ({n_total}) < num_qubits ({num_qubits})')
    (gate_layers, gate_q0s, gate_q1s) = _precompute_gate_arrays(layers)
    gate_partners = _build_gate_partners(layers, d)
    gcpe_edges = None
    num_groups = 0
    if use_gcpe:
        groups = _identify_gate_groups(layers, d)
        num_groups = len(groups)
        gcpe_edges = _build_gcpe_edges(layers, d, groups)

    def _cost(phi):
        if use_gcpe:
            return _cost_gcpe(phi, gcpe_edges, num_chiplets)
        return _cost_gcps(phi, gate_layers, gate_q0s, gate_q1s)
    population = []
    for _ in range(population_size):
        row = _random_balanced_row(n_total, num_chiplets, chiplet_capacities, rng)
        phi = np.tile(row, (d, 1))
        population.append(phi)
    costs = np.array([_cost(phi) for phi in population])
    best_ever_cost = int(costs.min())
    best_ever_phi = population[int(costs.argmin())].copy()
    stall = 0
    tag = 'GCP-E' if use_gcpe else 'GCP-S'
    print(f'[{tag}] n_qubits={num_qubits}, n_total={n_total}, layers={d}, gates={len(gate_layers)}, chiplets={num_chiplets}' + (f', groups={num_groups}' if use_gcpe else ''))
    print(f'[{tag}] gen=0  best_cost={best_ever_cost}')
    for gen in range(1, num_generations):
        shifted = -(costs - costs.min()).astype(np.float64)
        exp_v = np.exp(shifted)
        probs = exp_v / exp_v.sum()
        new_pop = []
        for _ in range(population_size // 2):
            (ia, ib) = rng.choice(population_size, size=2, p=probs, replace=True)
            (ca, cb) = _crossover(population[ia].copy(), population[ib].copy(), d, rng)
            ca = _mutation(ca, gate_partners, n_total, d, rng, k=mutation_k)
            cb = _mutation(cb, gate_partners, n_total, d, rng, k=mutation_k)
            new_pop.append(ca)
            new_pop.append(cb)
        new_pop[0] = best_ever_phi.copy()
        population = new_pop
        costs = np.array([_cost(phi) for phi in population])
        gen_best = int(costs.min())
        if gen_best < best_ever_cost:
            best_ever_cost = gen_best
            best_ever_phi = population[int(costs.argmin())].copy()
            stall = 0
        else:
            stall += 1
        if gen % 20 == 0 or gen == num_generations - 1:
            print(f'[{tag}] gen={gen}  best_cost={best_ever_cost}  gen_best={gen_best}  stall={stall}')
        if stall >= 30:
            print(f'[{tag}] Early stop at gen={gen} (stall={stall})')
            break
    partition_map = _majority_vote_balanced(best_ever_phi, num_qubits, num_chiplets, chiplet_capacities)
    print(f'[{tag}] Final best_cost={best_ever_cost} (per-layer)')
    return (partition_map, best_ever_cost)