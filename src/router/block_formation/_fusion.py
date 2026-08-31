import networkx as nx
from .._constants import build_comm_topology_from_chiplets
def _build_runtime_comm_topology(router):
    channel_dict = getattr(router, "pre_schedule_channel_dict", None)
    if not channel_dict:
        num_comm = getattr(router.args, "num_communication_qubits", None)
        if num_comm is None:
            num_comm = getattr(router.args, "num_communication_per_link", None)
        if num_comm is None or (router.args.numchipletsx <= 1 and router.args.numchipletsy <= 1):
            return nx.Graph()
        return build_comm_topology_from_chiplets(
            router.args.numchipletsx,
            router.args.numchipletsy,
            num_comm - 1)
    G = nx.Graph()
    for x in range(router.args.numchipletsx):
        for y in range(router.args.numchipletsy):
            G.add_node((x, y))
            for dx, dy in [(1, 0), (0, 1)]:
                px, py = x + dx, y + dy
                if 0 <= px < router.args.numchipletsx and 0 <= py < router.args.numchipletsy:
                    fwd = int(channel_dict.get(((x, y), (px, py)), 0)); rev = int(channel_dict.get(((px, py), (x, y)), 0)); cap = max(min(fwd, rev) - 1, 0)
                    G.add_edge((x, y), (px, py), cap=cap)
    return G
class CommunicationFusionMixin:
    def CommunicationFusion(self, verbose=False):
        from collections import Counter
        import networkx as nx
        circuit = self.gate_order
        position_table = self.position_table
        if not circuit:
            self.communication_blocks = []
            self.aggregation_nodes = []
            return
        self.comm_topology = _build_runtime_comm_topology(self)
        T = self.comm_topology
        def _block_qubits(gates):
            qs = set()
            for g in gates:
                qs.add(g.atom0)
                qs.add(g.atom1)
            return qs
        def _edge_demand(gates, agg_node):
            demand = Counter()
            for q in _block_qubits(gates):
                src = position_table[q]
                if src == agg_node:
                    continue
                try:
                    path = nx.shortest_path(T, src, agg_node)
                except nx.NetworkXNoPath:
                    return None
                for i in range(len(path) - 1):
                    demand[frozenset((path[i], path[i + 1]))] += 1
            return demand
        def _fusion_cost(gates):
            best = float("inf")
            for a in T.nodes:
                dem = _edge_demand(gates, a)
                if dem is None:
                    continue
                total_cost = 0
                for u, v, data in T.edges(data=True):
                    ek = frozenset((u, v)); d = int(dem.get(ek, 0)); c = int(data["cap"]); ov = max(d - c, 0)
                    total_cost += 2 * ov + min(c, d)
                if total_cost < best:
                    best = total_cost
            return best
        blk_list = []; blk = []; cost0 = 0
        for g in circuit:
            if g.is_ccop:
                cost1 = _fusion_cost([circuit[i] if isinstance(i, int) else i for i in blk] + [g]) if blk else _fusion_cost([g])
                cost2 = _fusion_cost([g])
                if blk and cost1 <= cost0 + cost2:
                    blk.append(g)
                    cost0 = cost1
                else:
                    if blk:
                        blk_list.append(blk)
                    blk = [g]
                    cost0 = cost2
            else:
                blk.append(g)
        if blk:
            blk_list.append(blk)
        self.communication_blocks = blk_list
        self.aggregation_nodes = []
