from .channel import assert_edge_in_connectivity, consume_capacity, link_capacity
from .constants import EVICT_COOLDOWN_WINDOW
def build_protected_set(q, curr_partner, future_gates, depth=8):
    prot = {q, curr_partner}
    for a, b in future_gates[:depth]:
        if a == q:
            prot.add(b)
        elif b == q:
            prot.add(a)
    return prot
def _score_evict_victim(qid, hop, pq, active_qubits, soon, ii, position_table, gcache):
    is_active = qid in active_qubits; appears_soon = qid in soon; ii_benefit = 0
    if ii is not None and qid in ii and len(ii[qid]) > 0:
        next_gate = ii[qid][0]; partner = _extract_partner(next_gate, qid); partner_pos = position_table.get(partner)
        if partner_pos is not None:
            d_before = gcache.sp_len(hop, partner_pos)
            d_after = gcache.sp_len(pq, partner_pos)
            if d_before is not None and d_after is not None:
                ii_benefit = d_after - d_before
    return (is_active, appears_soon, ii_benefit)
def _extract_partner(gate_obj, qid):
    if hasattr(gate_obj, 'atom0'):
        return gate_obj.atom1 if gate_obj.atom0 == qid else gate_obj.atom0
    return gate_obj[1] if gate_obj[0] == qid else gate_obj[0]
def _collect_soon_qubits(future_gates, depth=8):
    soon = set()
    for a, b in future_gates[:depth]:
        soon.add(a)
        soon.add(b)
    return soon
def try_local_evict(pq, hop, protected, future_gates,
                    position_table, qubit_positions, atom_paths,
                    active_qubits, connectivity, ch, evict_cooldown,
                    move_round, gcache, ii=None, PRINT_DEBUG=False):
    if link_capacity(hop, pq, ch) <= 0:
        return None
    candidates = []
    for qid, pos in position_table.items():
        if pos != hop or qid in protected:
            continue
        last = evict_cooldown.get(qid, -10 ** 9)
        if move_round - last <= EVICT_COOLDOWN_WINDOW:
            continue
        candidates.append(qid)
    if not candidates:
        return None
    soon = _collect_soon_qubits(future_gates)
    candidates.sort(
        key=lambda qid: (
            _score_evict_victim(qid, hop, pq, active_qubits, soon, ii, position_table, gcache),
            qid))
    victim = candidates[0]
    assert_edge_in_connectivity(connectivity, hop, pq, context=f"LOCAL-EVICT q{victim}")
    consume_capacity(connectivity, hop, pq, ch, context=f"LOCAL-EVICT q{victim} {hop}→{pq}")
    position_table[victim] = pq
    if victim in active_qubits:
        qubit_positions[victim] = pq
    atom_paths.setdefault(victim, [pq])
    atom_paths[victim].append(pq)
    evict_cooldown[victim] = move_round
    return victim