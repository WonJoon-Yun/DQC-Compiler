import math
from collections import Counter, defaultdict
import networkx as nx
import pymetis
from mapper._baseline import BaselineMapper
from mapper._graph import build_graph_numba

class ProposedMapper(BaselineMapper):

    def __init__(self, args, hardware, program):
        super().__init__(args, hardware, program)
        self.num_partitions = None
        self.partition_chip_selection = None

    def build_graph(self, program):
        G = build_graph_numba(program, self.args.num_qubits)
        return G

    def _compact_graph(self, G):
        idx_to_node = sorted(G.nodes())
        node_to_idx = {node: idx for (idx, node) in enumerate(idx_to_node)}
        H = nx.Graph()
        H.add_nodes_from(range(len(idx_to_node)))
        for (u, v, data) in G.edges(data=True):
            cu = node_to_idx[u]
            cv = node_to_idx[v]
            H.add_edge(cu, cv, weight=int(data.get('weight', 1)))
        return (H, node_to_idx, idx_to_node)

    def _adjlist_from_graph(self, G):
        n = G.number_of_nodes()
        adj = [{} for _ in range(n)]
        for (u, v, data) in G.edges(data=True):
            if u == v:
                continue
            w = float(data.get('weight', 1.0))
            adj[u][v] = w
            adj[v][u] = w
        return adj

    def _cut_cost(self, adj, partitions):
        cost = 0.0
        for i in range(len(adj)):
            pi = partitions[i]
            for (j, w) in adj[i].items():
                if j > i and pi != partitions[j]:
                    cost += w
        return cost

    def _compute_D(self, adj, partitions, k):
        n = len(adj)
        D = [[0.0] * k for _ in range(n)]
        for i in range(n):
            sums = [0.0] * k
            for (j, w) in adj[i].items():
                sums[partitions[j]] += w
            base = sums[partitions[i]]
            for l in range(k):
                D[i][l] = sums[l] - base
            D[i][partitions[i]] = 0.0
        return D

    def _best_exchange_pair(self, unlocked, partitions, D, adj):
        best_a = None
        best_b = None
        best_gain = float('-inf')
        for i1 in range(len(unlocked)):
            a = unlocked[i1]
            pa = partitions[a]
            Da = D[a]
            adj_a = adj[a]
            for i2 in range(i1 + 1, len(unlocked)):
                b = unlocked[i2]
                pb = partitions[b]
                if pa == pb:
                    continue
                wab = adj_a.get(b, 0.0)
                gain = Da[pb] + D[b][pa] - 2.0 * wab
                if gain > best_gain or (gain == best_gain and (best_a is None or (a, b) < (best_a, best_b))):
                    best_gain = gain
                    best_a = a
                    best_b = b
        return (best_a, best_b, best_gain)

    def _update_D_after_swap(self, D, adj, partitions, unlocked_set, a, b, pa, pb, k):
        for i in unlocked_set:
            pi = partitions[i]
            wia = adj[i].get(a, 0.0)
            wib = adj[i].get(b, 0.0)
            if pi == pa:
                D[i][pb] += 2.0 * wia - 2.0 * wib
                delta = wia - wib
                for l in range(k):
                    if l != pa and l != pb:
                        D[i][l] += delta
                D[i][pa] = 0.0
            elif pi == pb:
                D[i][pa] += 2.0 * wib - 2.0 * wia
                delta = wib - wia
                for l in range(k):
                    if l != pa and l != pb:
                        D[i][l] += delta
                D[i][pb] = 0.0
            else:
                D[i][pa] += wib - wia
                D[i][pb] += wia - wib

    def oee_refine_partitions(self, G, partitions, k, max_passes=5, tol=0.0):
        n = G.number_of_nodes()
        if n == 0:
            return (partitions, 0.0)
        current = list(partitions)
        adj = self._adjlist_from_graph(G)
        for _ in range(max_passes):
            start_partitions = current[:]
            work_partitions = current[:]
            D = self._compute_D(adj, work_partitions, k)
            unlocked = list(range(n))
            unlocked_set = set(unlocked)
            chosen_pairs = []
            gains = []
            while len(unlocked) >= 2:
                (a, b, gain) = self._best_exchange_pair(unlocked, work_partitions, D, adj)
                if a is None or b is None:
                    break
                chosen_pairs.append((a, b))
                gains.append(gain)
                unlocked_set.remove(a)
                unlocked_set.remove(b)
                unlocked = [x for x in unlocked if x in unlocked_set]
                (pa, pb) = (work_partitions[a], work_partitions[b])
                (work_partitions[a], work_partitions[b]) = (pb, pa)
                self._update_D_after_swap(D=D, adj=adj, partitions=work_partitions, unlocked_set=unlocked_set, a=a, b=b, pa=pa, pb=pb, k=k)
            best_prefix = 0
            best_total_gain = 0.0
            running_gain = 0.0
            for (idx, gain) in enumerate(gains, start=1):
                running_gain += gain
                if running_gain > best_total_gain:
                    best_total_gain = running_gain
                    best_prefix = idx
            if best_total_gain <= tol:
                break
            new_partitions = start_partitions[:]
            for i in range(best_prefix):
                (a, b) = chosen_pairs[i]
                (new_partitions[a], new_partitions[b]) = (new_partitions[b], new_partitions[a])
            current = new_partitions
        return (current, self._cut_cost(adj, current))

    def _naive_initial_partitions(self, idx_to_node, size_chiplet):
        initial_mapping = self.naive_mapping()
        chiplet_to_partition = {}
        partition_chip_selection = {}
        partitions = []
        for node in idx_to_node:
            physical_qubit = int(initial_mapping[node])
            (chip_x, chip_y) = self.hardware.qubit_idx_to_physical_idx[physical_qubit][:2]
            chiplet_id = chip_x * self.args.numchipletsy + chip_y
            if chiplet_id not in chiplet_to_partition:
                partition_id = len(chiplet_to_partition)
                chiplet_to_partition[chiplet_id] = partition_id
                partition_chip_selection[partition_id] = chiplet_id
            partitions.append(chiplet_to_partition[chiplet_id])
        part_sizes = Counter(partitions)
        if any((size > size_chiplet for size in part_sizes.values())):
            raise ValueError('[FATAL] Naive OEE initialization exceeded chiplet capacity.')
        return (partitions, partition_chip_selection)

    def k_partitioning(self, G, num_program_qubits, size_chiplet, chip_capacities=None):
        """1) Compact graph to dense node ids"""
        (H, node_to_idx, idx_to_node) = self._compact_graph(G)
        n = H.number_of_nodes()
        if n == 0:
            self.num_partitions = 0
            self.partition_chip_selection = {}
            return (0, 0, {})
        self.partition_chip_selection = None
        if self.args.mapping_method in ('OEE', 'OEE-ILP'):
            (partitions, self.partition_chip_selection) = self._naive_initial_partitions(idx_to_node, size_chiplet)
            num_partitions = len(self.partition_chip_selection)
            edgecut = self._cut_cost(self._adjlist_from_graph(H), partitions)
            updated_partitions = list(partitions)
        else:
            xadj = [0]
            adjncy = []
            eweights = []
            for node in range(n):
                neighbors = list(H.neighbors(node))
                for neighbor in neighbors:
                    adjncy.append(neighbor)
                    eweights.append(int(H[node][neighbor]['weight']))
                xadj.append(len(adjncy))
            vweights = [1] * n
            num_chips = self.args.numchipletsx * self.args.numchipletsy
            num_partitions = min(math.ceil(n / size_chiplet), num_chips)
            sorted_caps = None
            if chip_capacities is not None:
                num_partitions = min(num_chips, n)
                sorted_caps = [chip_capacities[pos] for pos in sorted(chip_capacities.keys())]
            (edgecut, partitions) = pymetis.part_graph(nparts=num_partitions, xadj=xadj, adjncy=adjncy, eweights=eweights, vweights=vweights)
            part_to_nodes = {p: [] for p in range(num_partitions)}
            for (node, part) in enumerate(partitions):
                part_to_nodes[part].append(node)
            if sorted_caps is not None and len(sorted_caps) >= num_partitions:
                per_part_cap = sorted_caps[:num_partitions]
            else:
                per_part_cap = [size_chiplet] * num_partitions
            overflow_parts = {p: nodes[:] for (p, nodes) in part_to_nodes.items() if len(nodes) > per_part_cap[p]}
            updated_partitions = list(partitions)
            part_sizes = {p: len(nodes) for (p, nodes) in part_to_nodes.items()}
            if overflow_parts:
                for (p_over, nodes) in overflow_parts.items():
                    cap_over = per_part_cap[p_over]
                    while part_sizes[p_over] > cap_over:
                        min_loss = float('inf')
                        best_node = None
                        for node in nodes:
                            intra_edges = sum((1 for nbr in H.neighbors(node) if updated_partitions[nbr] == p_over))
                            if intra_edges < min_loss:
                                min_loss = intra_edges
                                best_node = node
                        best_target = None
                        min_cut_cost = float('inf')
                        for p_under in range(num_partitions):
                            if part_sizes[p_under] >= per_part_cap[p_under] or p_under == p_over:
                                continue
                            cut_cost = sum((H[best_node][nbr]['weight'] for nbr in H.neighbors(best_node) if updated_partitions[nbr] == p_under))
                            if cut_cost < min_cut_cost:
                                min_cut_cost = cut_cost
                                best_target = p_under
                        if best_target is None:
                            raise ValueError('[FATAL] No legal target found for overflow fix.')
                        updated_partitions[best_node] = best_target
                        part_sizes[p_over] -= 1
                        part_sizes[best_target] += 1
                        nodes.remove(best_node)
        if getattr(self.args, 'use_oee_refine', True) and num_partitions > 1:
            (updated_partitions, edgecut) = self.oee_refine_partitions(H, updated_partitions, num_partitions, max_passes=getattr(self.args, 'oee_max_passes', 5), tol=getattr(self.args, 'oee_tol', 0.0))
        self.num_partitions = num_partitions
        partition_map = {idx_to_node[i]: int(updated_partitions[i]) for i in range(n)}
        return (num_partitions, edgecut, partition_map)

    def construct_sub_graph(self, G, partitions, num_partitions):
        self.logical_weights = defaultdict(int)
        program_segments = [nx.Graph() for _ in range(num_partitions)]
        cut_graph = nx.Graph()
        total_cut_weight = 0
        for u in G.nodes():
            part_u = partitions[u]
            program_segments[part_u].add_node(u)
        for (u, v, data) in G.edges(data=True):
            w = int(data.get('weight', 1))
            part_u = partitions[u]
            part_v = partitions[v]
            if part_u == part_v:
                program_segments[part_u].add_edge(u, v, weight=w)
            else:
                cut_graph.add_edge(u, v, weight=w)
                total_cut_weight += w
                key = tuple(sorted((part_u, part_v)))
                self.logical_weights[key] += w
        if self.hardware.is_new_model:
            max_cap = max(self.hardware.per_chip_compute_capacity.values())
        else:
            max_cap = self.hardware.num_x * self.hardware.num_y * 2
        for (i, G_seg) in enumerate(program_segments):
            if len(G_seg.nodes()) > max_cap:
                raise ValueError(f'[FATAL] Segment {i} has {len(G_seg.nodes())} qubits, which exceeds max chiplet capacity of {max_cap}')
        return (program_segments, cut_graph)

    def get_subgraphs(self, G, num_program_qubits, size_chiplet, chip_capacities=None):
        (num_partitions, edgecut, partitions) = self.k_partitioning(G, num_program_qubits, size_chiplet, chip_capacities=chip_capacities)
        (program_segments, cut_graph) = self.construct_sub_graph(G, partitions, num_partitions)
        return (program_segments, cut_graph)