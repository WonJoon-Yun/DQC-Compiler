try:
    from pulp import LpBinary, LpMinimize, LpProblem, LpVariable, lpSum
except ImportError:
    LpProblem = None
    LpMinimize = None
    LpVariable = None
    LpBinary = None
    lpSum = None

def _finalize_chip_selection_result(*, program_segment_count, chiplet_count, chip_selection, best_cost, logical_weights, physical_weights):
    selection = {}
    if chip_selection is not None:
        selection = {int(segment_idx): int(chiplet_idx) for (segment_idx, chiplet_idx) in chip_selection.items()}
    if len(set(selection.values())) != len(selection):
        raise ValueError('[FATAL] Chip selection assigned multiple segments to one chiplet')
    missing_segments = [segment_idx for segment_idx in range(int(program_segment_count)) if segment_idx not in selection]
    free_chiplets = [chiplet_idx for chiplet_idx in range(int(chiplet_count)) if chiplet_idx not in selection.values()]
    if len(free_chiplets) < len(missing_segments):
        raise ValueError('[FATAL] Chip selection returned too few unique chiplets for all segments')
    for (segment_idx, chiplet_idx) in zip(missing_segments, free_chiplets):
        selection[segment_idx] = chiplet_idx
    if best_cost is None:
        best_cost = 0.0
        for ((seg_u, seg_v), weight) in logical_weights.items():
            chip_u = selection[int(seg_u)]
            chip_v = selection[int(seg_v)]
            best_cost += weight * physical_weights[tuple(sorted((chip_u, chip_v)))]
    return (selection, float(best_cost))

def chip_selection_ILP(logical_weights, physical_weights, segment_sizes=None, chip_capacities=None):
    """Optimized ILP for segment-to-chiplet mapping."""
    if LpProblem is None:
        raise ImportError('pulp is required for mapping_method=ILP')
    logical_weights = {(min(s1, s2), max(s1, s2)): w for ((s1, s2), w) in logical_weights.items()}
    physical_weights = {(min(c1, c2), max(c1, c2)): w for ((c1, c2), w) in physical_weights.items()}
    segments = sorted({i for edge in logical_weights for i in edge})
    chiplets = sorted({i for edge in physical_weights for i in edge})
    chiplet_cap = None
    if segment_sizes is not None and chip_capacities is not None:
        positions = sorted(chip_capacities.keys())
        chiplet_cap = {i: chip_capacities[positions[i]] for i in range(len(positions)) if i in chiplets or i < len(positions)}
    prob = LpProblem('Segment_to_Chiplet_Mapping', LpMinimize)
    y = {(s, c): LpVariable(f'y_{s}_{c}', cat=LpBinary) for s in segments for c in chiplets}
    (x, z1, z2) = ({}, {}, {})
    for (s1, s2) in logical_weights:
        for (c1, c2) in physical_weights:
            if c1 == c2:
                continue
            key = (s1, s2, c1, c2)
            x[key] = LpVariable(f'x_{s1}_{s2}_{c1}_{c2}', cat=LpBinary)
            z1[key] = LpVariable(f'z1_{s1}_{s2}_{c1}_{c2}', cat=LpBinary)
            z2[key] = LpVariable(f'z2_{s1}_{s2}_{c1}_{c2}', cat=LpBinary)
    prob += lpSum((logical_weights[s1, s2] * physical_weights[c1, c2] * x[s1, s2, c1, c2] for (s1, s2, c1, c2) in x))
    for s in segments:
        prob += lpSum((y[s, c] for c in chiplets)) == 1
    for c in chiplets:
        prob += lpSum((y[s, c] for s in segments)) <= 1
    for (s1, s2, c1, c2) in x:
        prob += z1[s1, s2, c1, c2] <= y[s1, c1]
        prob += z1[s1, s2, c1, c2] <= y[s2, c2]
        prob += z1[s1, s2, c1, c2] >= y[s1, c1] + y[s2, c2] - 1
        prob += z2[s1, s2, c1, c2] <= y[s1, c2]
        prob += z2[s1, s2, c1, c2] <= y[s2, c1]
        prob += z2[s1, s2, c1, c2] >= y[s1, c2] + y[s2, c1] - 1
        prob += x[s1, s2, c1, c2] == z1[s1, s2, c1, c2] + z2[s1, s2, c1, c2]
    if chiplet_cap is not None and segment_sizes is not None:
        for s in segments:
            seg_sz = segment_sizes.get(s, 0)
            for c in chiplets:
                cap = chiplet_cap.get(c)
                if cap is not None and seg_sz > cap:
                    prob += y[s, c] == 0
    prob.solve()
    segment_to_chiplet = {s: c for (s, c) in y if y[s, c].varValue == 1}
    return (segment_to_chiplet, prob.objective.value(), None, None)

def chip_selection_BruteForce(logical_weights, physical_weights, segment_sizes=None, chip_capacities=None):
    raise RuntimeError('pruned: chip_selection_BruteForce')

def chip_selection_Evolutionary(logical_weights, physical_weights, population_size=50, generations=100, mutation_rate=0.1, patience=10, segment_sizes=None, chip_capacities=None):
    raise RuntimeError('pruned: chip_selection_Evolutionary')