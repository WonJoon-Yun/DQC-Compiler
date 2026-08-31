from .cache import GraphCache
def classify_qubits(block, position_table, connectivity, agg_node):
    gcache = GraphCache(connectivity); agg_chip = gcache.chip_of(agg_node); qubits = set()
    for g in block:
        if hasattr(g, 'atom0') and hasattr(g, 'atom1'):
            qubits.add(g.atom0)
            qubits.add(g.atom1)
        else:
            qubits.add(g[0])
            qubits.add(g[1])
    num_internal = 0
    num_external = 0
    for q in qubits:
        pos = position_table.get(q)
        if pos is None:
            num_external += 1
            continue
        q_chip = gcache.chip_of(pos)
        if agg_chip is not None and q_chip == agg_chip:
            num_internal += 1
        else:
            num_external += 1
    return num_internal, num_external