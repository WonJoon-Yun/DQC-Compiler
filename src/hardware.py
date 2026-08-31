import networkx as nx
import numpy as np
class Hardware:
    def __init__(self, args):
        self.num_chiplets_x = args.numchipletsx
        self.num_chiplets_y = args.numchipletsy
        self.interconnect_edges = None
        self.qubit_idx_to_physical_idx = None
        self.cmap = None
        self.is_new_model = (
            getattr(args, 'system_qubits_per_chip', None) is not None
            and getattr(args, 'num_communication_per_link', None) is not None)
        if not self.is_new_model:
            raise NotImplementedError(
                "Legacy AOD/SLM hardware model was pruned; use --system_qubits_per_chip + --num_communication_per_link.")
        self.num_x = None
        self.num_y = None
        self.system_qubits_per_chip = args.system_qubits_per_chip
        self.num_communication_per_link = args.num_communication_per_link
        self._build_flat_pool(args)
    def _neighbor_count(self, cx, cy):
        count = 0
        if cx > 0:
            count += 1
        if cx < self.num_chiplets_x - 1:
            count += 1
        if cy > 0:
            count += 1
        if cy < self.num_chiplets_y - 1:
            count += 1
        return count
    def _build_flat_pool(self, args):
        cap = {}
        for cx in range(self.num_chiplets_x):
            for cy in range(self.num_chiplets_y):
                n = self._neighbor_count(cx, cy)
                cap[(cx, cy)] = self.system_qubits_per_chip - self.num_communication_per_link * n
        self.per_chip_compute_capacity = cap
        self.num_qubits = sum(cap.values())
        qubit_idx_to_physical_idx = {}; chip_to_qubits = {}; offset = 0
        for cx in range(self.num_chiplets_x):
            for cy in range(self.num_chiplets_y):
                chip_cap = cap[(cx, cy)]
                qubits = list(range(offset, offset + chip_cap))
                chip_to_qubits[(cx, cy)] = qubits
                for local_idx, qid in enumerate(qubits):
                    qubit_idx_to_physical_idx[qid] = [cx, cy, local_idx]
                offset += chip_cap
        self.chip_to_qubits = chip_to_qubits
        self.qubit_idx_to_physical_idx = qubit_idx_to_physical_idx
        coupling_maps = set()
        interconnect_edges = set()
        for (cx, cy), qubits in chip_to_qubits.items():
            for i in range(len(qubits)):
                for j in range(i + 1, len(qubits)):
                    coupling_maps.add((qubits[i], qubits[j]))
                    coupling_maps.add((qubits[j], qubits[i]))
        for cx in range(self.num_chiplets_x):
            for cy in range(self.num_chiplets_y):
                for dx, dy in [(1, 0), (0, 1)]:
                    nx_, ny_ = cx + dx, cy + dy
                    if 0 <= nx_ < self.num_chiplets_x and 0 <= ny_ < self.num_chiplets_y:
                        q_src = chip_to_qubits[(cx, cy)]; q_dst = chip_to_qubits[(nx_, ny_)]; n_links = min(self.num_communication_per_link, len(q_src), len(q_dst))
                        for k in range(n_links):
                            coupling_maps.add((q_src[k], q_dst[k]))
                            coupling_maps.add((q_dst[k], q_src[k]))
                            interconnect_edges.add((q_src[k], q_dst[k]))
                            interconnect_edges.add((q_dst[k], q_src[k]))
        G = nx.Graph()
        G.add_nodes_from(range(self.num_qubits))
        G.add_edges_from(coupling_maps)
        self.interconnect_edges = {(min(q1, q2), max(q1, q2)) for q1, q2 in interconnect_edges}
        self.cmap = G
    def get_chip_capacity(self, chip_pos):
        if self.is_new_model:
            return self.per_chip_compute_capacity[tuple(chip_pos)]
        return self.num_x * self.num_y * 2
    def get_chiplet_pos(self, pos):
        if isinstance(pos, (list, tuple)):
            chip_pos = []
            for p in pos:
                chip_pos.append(np.array(self.qubit_idx_to_physical_idx[p][:2]))
        elif isinstance(pos, int):
            chip_pos = np.array(self.qubit_idx_to_physical_idx[pos][:2])
        return chip_pos