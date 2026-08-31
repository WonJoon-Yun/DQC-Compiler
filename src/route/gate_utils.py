def normalize_block_to_gates(block):
    gates = []
    for g in block:
        if hasattr(g, "atom0") and hasattr(g, "atom1"): gates.append((g.atom0, g.atom1))
        else: gates.append((g[0], g[1]))
    return gates
def gate_matches(gate_obj, s, t):
    if hasattr(gate_obj, 'atom0') and hasattr(gate_obj, 'atom1'):
        return ((gate_obj.atom0 == s and gate_obj.atom1 == t) or
                (gate_obj.atom0 == t and gate_obj.atom1 == s))
    if isinstance(gate_obj, (tuple, list)) and len(gate_obj) >= 2:
        return ((gate_obj[0] == s and gate_obj[1] == t) or
                (gate_obj[0] == t and gate_obj[1] == s))
    return False