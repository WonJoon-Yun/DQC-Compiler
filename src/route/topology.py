import networkx as nx
def build_connectivity_graph(cols, rows):
    """Build a 2D grid connectivity graph."""
    G = nx.Graph()
    for c in range(cols):
        for r in range(rows):
            G.add_node((c, r))
    for c in range(cols):
        for r in range(rows):
            if c + 1 < cols: G.add_edge((c, r), (c + 1, r))
            if r + 1 < rows: G.add_edge((c, r), (c, r + 1))
    return G