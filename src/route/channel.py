def link_capacity(u, v, ch):
    return max(0, ch.get((v, u), 0) - 1)

def assert_channel_invariant(ch, context=''):
    for (edge, val) in ch.items():
        assert val > 0, f"[ASSERT] channel {edge} = {val} (>0 required) ctx='{context}'"

def assert_edge_in_connectivity(connectivity, u, v, context=''):
    assert connectivity.has_node(u) and connectivity.has_node(v), f"[ASSERT] Node(s) {u},{v} not in graph. ctx='{context}'"
    assert connectivity.has_edge(u, v), f"[ASSERT] Edge ({u},{v}) not in graph. ctx='{context}'\n  Neighbors of {u}: {list(connectivity.neighbors(u))}"

def assert_safe_to_consume(u, v, ch, context=''):
    rev = ch.get((v, u), 0)
    assert rev >= 2, f"[ASSERT] Cannot consume ({u},{v}): ch[({v},{u})]={rev}, need>=2. ctx='{context}'"

def consume_capacity(connectivity, u, v, ch, context='', skip_assert=False):
    if not skip_assert:
        assert_edge_in_connectivity(connectivity, u, v, context=f'consume {context}')
        assert_safe_to_consume(u, v, ch, context=f'consume {context}')
    ch[u, v] = ch.get((u, v), 0) + 1
    ch[v, u] = ch.get((v, u), 0) - 1
    assert ch[v, u] > 0, f"[ASSERT] ch[({v},{u})]={ch[v, u]} after consume. ctx='{context}'"

def consume_path(connectivity, path, ch, context=''):
    for i in range(len(path) - 1):
        consume_capacity(connectivity, path[i], path[i + 1], ch, context=f'{context} hop {i}: {path[i]}→{path[i + 1]}')

def reserve_recnot_channel(connectivity, u, v, ch, context=''):
    assert_edge_in_connectivity(connectivity, u, v, context=f'recnot reserve {context}')
    uv = ch.get((u, v), 0)
    vu = ch.get((v, u), 0)
    assert uv >= 1 and vu >= 1, f"[ASSERT] Cannot reserve Re-CNOT channel on ({u},{v}): ch[({u},{v})]={uv}, ch[({v},{u})]={vu}. ctx='{context}'"
    ch[u, v] = uv - 1
    ch[v, u] = vu - 1
    assert ch[u, v] >= 0 and ch[v, u] >= 0, f"[ASSERT] Negative Re-CNOT reservation on ({u},{v}). ctx='{context}'"

def release_recnot_channel(u, v, ch):
    ch[u, v] = ch.get((u, v), 0) + 1
    ch[v, u] = ch.get((v, u), 0) + 1

def channel_snapshot(ch):
    return dict(ch)

def print_channel_delta(before, after, label=''):
    changes = []
    for edge in sorted(set(before) | set(after), key=str):
        (vb, va) = (before.get(edge, 0), after.get(edge, 0))
        if vb != va:
            d = va - vb
            changes.append(f'    {edge[0]}→{edge[1]}: {vb}→{va} (Δ={d:+d})')
    if changes:
        print(f'  [Δ] {label}')
        for line in changes:
            print(line)