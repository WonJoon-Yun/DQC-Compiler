import networkx as nx
def build_connectivity_graph(numchipletsx: int, numchipletsy: int) -> nx.Graph:
    G = nx.grid_2d_graph(numchipletsx, numchipletsy)
    return G
import networkx as nx
def BuildBlockDAG(blocks, agg_nodes, dependency_semantics="auto", allow_successor_edges=True, strict_dup_uids=True, overlap_qubits=None):
    from collections import defaultdict
    import networkx as nx
    if not blocks:
        return nx.DiGraph(), {}, 0
    dag = nx.DiGraph()
    add_node = dag.add_node  # local ref (speedup)
    add_edge = dag.add_edge
    def _uid_of(x):
        return getattr(x, "unique_id", x)
    def _qubits_in_gate(g):
        for a_name, b_name in (("atom0", "atom1"), ("q0", "q1"), ("src", "dst")):
            if hasattr(g, a_name) or hasattr(g, b_name):
                out = set(); a = getattr(g, a_name, None); b = getattr(g, b_name, None)
                if a is not None:
                    out.add(a)
                if b is not None:
                    out.add(b)
                if out:
                    return out
        if isinstance(g, (tuple, list)) and len(g) == 2:
            return {g[0], g[1]}
        for attr in ("atoms", "qubits"):
            if hasattr(g, attr):
                try:
                    s = set(getattr(g, attr))
                    if s:
                        return s
                except Exception:
                    pass
        return set()
    for i in range(len(blocks)):
        add_node(i, block=blocks[i], agg_node=(agg_nodes[i] if i < len(agg_nodes) else None))
    gate_to_block = {}
    dup_uids = defaultdict(set)
    for bidx, block in enumerate(blocks):
        for g in block:
            uid = getattr(g, "unique_id", None)
            if uid is None:
                continue
            if uid in gate_to_block:
                dup_uids[uid].add(gate_to_block[uid])
                dup_uids[uid].add(bidx)
                if strict_dup_uids:
                    pass
                else:
                    continue
            else:
                gate_to_block[uid] = bidx
    if dup_uids and strict_dup_uids:
        detail = "; ".join(f"{uid}: {sorted(s)}" for uid, s in dup_uids.items())
        raise ValueError(f"[DAG error] Same gate.unique_id appears in multiple blocks -> {detail}")
    preds_raw = defaultdict(set); succs_raw = defaultdict(set); unknown_raw = defaultdict(set)
    for curr_bidx, block in enumerate(blocks):
        for g in block:
            deps = getattr(g, "dependency", None)
            if not deps:
                continue
            for d in deps:
                dep_uid = _uid_of(d)
                dep_bidx = gate_to_block.get(dep_uid)
                if dep_bidx is None:
                    unknown_raw[curr_bidx].add(dep_uid)
                    continue
                if dep_bidx == curr_bidx:
                    continue
                if dep_bidx < curr_bidx:
                    preds_raw[curr_bidx].add(dep_bidx)
                else:
                    succs_raw[curr_bidx].add(dep_bidx)
    total_preds = sum(len(v) for v in preds_raw.values())
    total_succs = sum(len(v) for v in succs_raw.values())
    if dependency_semantics not in ("auto", "predecessor", "successor"):
        raise ValueError(f"[DAG error] Unknown dependency_semantics='{dependency_semantics}'")
    inferred = dependency_semantics
    if dependency_semantics == "auto":
        if total_preds > 0 and total_succs == 0:
            inferred = "predecessor"
        elif total_succs > 0 and total_preds == 0:
            inferred = "successor"
        else:
            inferred = "mixed"
    if inferred in ("predecessor", "mixed"):
        for tgt, srcs in preds_raw.items():
            for src in srcs:
                add_edge(src, tgt)
    if inferred in ("successor", "mixed") and allow_successor_edges:
        for src, tgts in succs_raw.items():
            for tgt in tgts:
                add_edge(src, tgt)
    elif inferred == "successor" and not allow_successor_edges and total_preds > 0:
        example_src = next(iter(succs_raw))
        example_tgt = next(iter(succs_raw[example_src]))
        raise ValueError(f"[DAG error] Successor-like deps forbidden: {example_src}->{example_tgt}")
    oq = None if overlap_qubits is None else set(overlap_qubits); qubits_per_block = []; qubit_to_blocks = defaultdict(list)
    for bidx, block in enumerate(blocks):
        s = set()
        for g in block:
            s |= _qubits_in_gate(g)
        if oq is not None:
            s &= oq
        qubits_per_block.append(s)
        for q in s:
            qubit_to_blocks[q].append(bidx)
    latest_level = {}
    levels = {}
    for i, Qi in enumerate(qubits_per_block):
        if not Qi:
            levels[i] = 0
            continue
        prev_levels = [latest_level.get(q, -1) for q in Qi]
        level = max(prev_levels) + 1 if prev_levels else 0
        levels[i] = level
        for q in Qi:
            latest_level[q] = level
    added = 0
    for _, blist in qubit_to_blocks.items():
        if len(blist) < 2:
            continue
        blist.sort()
        for i, j in zip(blist, blist[1:]):
            if not dag.has_edge(i, j):
                add_edge(i, j)
                added += 1
    if added:
        msg = f"[INFO] added {added} edges by overlap serialization (i<j)"
        if oq is not None:
            msg += f" restricted to {sorted(oq)}"
    if not nx.is_directed_acyclic_graph(dag):
        try:
            cycle = next(nx.simple_cycles(dag))
        except StopIteration:
            cycle = []
        hint = []
        if dup_uids:
            hint.append("duplicate uids present")
        if unknown_raw:
            unknown_cnt = sum(len(v) for v in unknown_raw.values())
            hint.append(f"{unknown_cnt} unknown dep uids")
        hint_str = "; ".join(hint) if hint else "no extra hints"
        raise ValueError(f"[DAG error] Cycle detected. Example: {cycle}. Hints: {hint_str}")
    depth = (max(levels.values()) + 1) if levels else 0
    return dag, levels, depth