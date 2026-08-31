import copy
import json
import os
import time
import networkx.algorithms.community as nx_comm
import numpy as np
from mapper._chip_selection import _finalize_chip_selection_result, chip_selection_BruteForce, chip_selection_Evolutionary, chip_selection_ILP
from mapper._gcp import gcp_partition
from mapper._partitioning import ProposedMapper
from mapper._wbcp import wbcp_partition
from utils import convert_ndarray_to_list

class Mapper(ProposedMapper):

    def __init__(self, args, hardware, program):
        super().__init__(args, hardware, program)
        self.num_logical_qubits = self.args.num_qubits
        if self.hardware.is_new_model:
            self.num_physical_qubits = self.hardware.num_qubits
        else:
            self.num_physical_qubits = self.args.numchipletsx * self.args.numchipletsy * self.hardware.num_x * self.hardware.num_y * 2
        if self.num_logical_qubits > self.num_physical_qubits:
            raise ValueError(f'[FATAL] Program needs {self.num_logical_qubits} logical qubits, but hardware only has {self.num_physical_qubits} compute qubits')

    def naive_mapping(self):
        if self.num_logical_qubits > self.num_physical_qubits:
            raise ValueError(f'[FATAL] Program needs {self.num_logical_qubits} logical qubits, but hardware only has {self.num_physical_qubits} physical qubits')
        np.random.seed(self.args.seed)
        values = np.arange(self.num_logical_qubits)
        np.random.shuffle(values)
        qubit_mapping = {i: values[i] for i in range(self.num_logical_qubits)}
        return qubit_mapping

    def identity_mapping(self):
        if self.num_logical_qubits > self.num_physical_qubits:
            raise ValueError(f'[FATAL] Program needs {self.num_logical_qubits} logical qubits, but hardware only has {self.num_physical_qubits} physical qubits')
        return {i: i for i in range(self.num_logical_qubits)}

    def naive_baseline_mapping(self):
        start_time = time.time()
        mapped_cmap = copy.deepcopy(self.hardware.cmap)
        qubit_mapping = self.naive_mapping()
        physical_program = [(qubit_mapping[q1], qubit_mapping[q2]) for (q1, q2) in self.program]
        cost = self.get_cost(physical_program)
        elapsed = time.time() - start_time
        self.args.mapping_cost = int(cost)
        self.cost = int(cost)
        return (mapped_cmap, physical_program, qubit_mapping, [elapsed, 0.0, 0.0, 0.0, int(cost)])

    def trivial_mapping(self):
        start_time = time.time()
        mapped_cmap = copy.deepcopy(self.hardware.cmap)
        qubit_mapping = self.identity_mapping()
        physical_program = [(qubit_mapping[q1], qubit_mapping[q2]) for (q1, q2) in self.program]
        cost = self.get_cost(physical_program)
        elapsed = time.time() - start_time
        self.args.mapping_cost = int(cost)
        self.cost = int(cost)
        return (mapped_cmap, physical_program, qubit_mapping, [elapsed, 0.0, 0.0, 0.0, int(cost)])

    def _get_chip_capacities(self):
        """Return per-chip compute capacity dict {(cx,cy): int}."""
        (cx, cy) = (self.args.numchipletsx, self.args.numchipletsy)
        if self.hardware.is_new_model:
            return dict(self.hardware.per_chip_compute_capacity)
        uniform = self.hardware.num_x * self.hardware.num_y * 2
        return {(x, y): uniform for x in range(cx) for y in range(cy)}

    def mapping(self):
        print('Initializing mapper...')
        if self.args.mapping_method == 'trivial':
            return self.trivial_mapping()
        if self.args.mapping_method == 'naive':
            return self.naive_baseline_mapping()
        process_time1 = time.time()
        mapped_cmap = copy.deepcopy(self.hardware.cmap)
        G = self.build_graph(self.program)
        num_program_qubits = len(G.nodes)
        NUM_CHIPLETS_X = self.args.numchipletsx
        NUM_CHIPLETS_Y = self.args.numchipletsy
        chip_capacities = self._get_chip_capacities()
        qubits_per_chiplet = max(chip_capacities.values())
        process_time1 = time.time() - process_time1
        if self.args.mapping_method in ('GCP', 'GCP-E', 'GCP-S', 'GCP-ILP'):
            return self._mapping_gcp(mapped_cmap, G, num_program_qubits, NUM_CHIPLETS_X, NUM_CHIPLETS_Y, qubits_per_chiplet, process_time1, variant=self.args.mapping_method, chip_capacities=chip_capacities)
        if self.args.mapping_method in ('WBCP', 'WBCP-noILP'):
            return self._mapping_wbcp(mapped_cmap, G, num_program_qubits, NUM_CHIPLETS_X, NUM_CHIPLETS_Y, qubits_per_chiplet, process_time1, chip_capacities=chip_capacities)
        k_partitioning_time = time.time()
        (program_segments, cut_graph) = self.get_subgraphs(G, num_program_qubits, qubits_per_chiplet, chip_capacities=chip_capacities)
        k_partitioning_time = time.time() - k_partitioning_time
        print(f'[INFO] K-partitioning time: {k_partitioning_time} seconds')
        print(f'[INFO] Logical weights: {self.logical_weights}')
        print(f'[INFO] Physical weights: {self.physical_weights}')
        print(f'[INFO] Chip positions: {self.chip_pos}')
        print(f'[INFO] Program segments: list of length {len(program_segments)}, min element: {min((len(seg) for seg in program_segments))}, max element: {max((len(seg) for seg in program_segments))}  ')
        segment_sizes = {i: len(list(seg.nodes())) for (i, seg) in enumerate(program_segments)}
        chip_selection_time = time.time()
        if self.args.mapping_method in ('ILP', 'OEE-ILP'):
            (chip_selection, best_cost, worst_mapping, worst_cost) = chip_selection_ILP(self.logical_weights, self.physical_weights, segment_sizes=segment_sizes, chip_capacities=chip_capacities)
        elif self.args.mapping_method == 'BruteForce':
            (chip_selection, best_cost, worst_mapping, worst_cost) = chip_selection_BruteForce(self.logical_weights, self.physical_weights, segment_sizes=segment_sizes, chip_capacities=chip_capacities)
        elif self.args.mapping_method == 'Evolutionary':
            (chip_selection, best_cost, worst_mapping, worst_cost) = chip_selection_Evolutionary(self.logical_weights, self.physical_weights, segment_sizes=segment_sizes, chip_capacities=chip_capacities)
        elif self.args.mapping_method == 'MQC':
            chip_selection = {i: i for i in range(len(program_segments))}
            best_cost = sum((self.logical_weights[edge] * self.physical_weights[edge] for edge in self.logical_weights))
        elif self.args.mapping_method == 'OEE':
            chip_selection = self.partition_chip_selection or {i: i for i in range(len(program_segments))}
            best_cost = sum((self.logical_weights[edge] * self.physical_weights[tuple(sorted((chip_selection[edge[0]], chip_selection[edge[1]])))] for edge in self.logical_weights))
        else:
            raise ValueError(f'[FATAL] Invalid chip selection method: {self.args.mapping_method} should be ILP, OEE-ILP, BruteForce, Evolutionary, MQC, OEE, GCP, GCP-E, GCP-ILP, WBCP, WBCP-noILP, naive, or trivial')
        chip_selection_time = time.time() - chip_selection_time
        print(f'[INFO] Chip selection time: {chip_selection_time} seconds')
        (chip_selection, best_cost) = _finalize_chip_selection_result(program_segment_count=len(program_segments), chiplet_count=len(self.chip_pos), chip_selection=chip_selection, best_cost=best_cost, logical_weights=self.logical_weights, physical_weights=self.physical_weights)
        static_oee_cost = int(sum(self.logical_weights.values()))
        self.args.mapping_cost_ilp = int(best_cost)
        self.args.mapping_cost_static_oee = static_oee_cost
        self.args.mapping_cost = static_oee_cost
        self.cost = static_oee_cost
        remap_time = time.time()
        qubit_mapping = self.remap(program_segments, chip_selection)
        remap_time = time.time() - remap_time
        print(f'[INFO] Remap time: {remap_time} seconds')
        physical_program = []
        for (q1, q2) in self.program:
            physical_q1 = qubit_mapping.get(q1, q1)
            physical_q2 = qubit_mapping.get(q2, q2)
            physical_program.append((physical_q1, physical_q2))
        return (mapped_cmap, physical_program, qubit_mapping, [process_time1, k_partitioning_time, chip_selection_time, remap_time, static_oee_cost])

    def _mapping_wbcp(self, mapped_cmap, G, num_program_qubits, NUM_CHIPLETS_X, NUM_CHIPLETS_Y, qubits_per_chiplet, process_time1, chip_capacities=None):
        num_chiplets = NUM_CHIPLETS_X * NUM_CHIPLETS_Y
        if chip_capacities is None:
            chip_capacities = self._get_chip_capacities()
        wbcp_time = time.time()
        window_length = getattr(self.args, 'wbcp_window_length', None)
        (partition_map, wbcp_cost, num_windows) = wbcp_partition(program=self.program, num_qubits=num_program_qubits, num_partitions=num_chiplets, chiplet_capacity=qubits_per_chiplet, window_length=window_length, seed=self.args.seed)
        wbcp_time = time.time() - wbcp_time
        used_parts = sorted(set(partition_map.values()))
        part_remap = {old: new for (new, old) in enumerate(used_parts)}
        num_partitions = len(used_parts)
        remapped = {q: part_remap[p] for (q, p) in partition_map.items()}
        print(f'[INFO] WBCP partition time: {wbcp_time:.3f}s, windows: {num_windows}, dynamic cost: {wbcp_cost}, partitions: {num_partitions}')
        (program_segments, cut_graph) = self.construct_sub_graph(G, remapped, num_partitions)
        print(f'[INFO] WBCP segment sizes: {[len(seg) for seg in program_segments]}')
        segment_sizes = {i: len(list(seg.nodes())) for (i, seg) in enumerate(program_segments)}
        chip_selection_time = time.time()
        if self.args.mapping_method == 'WBCP-noILP':
            chip_selection = {i: i for i in range(num_partitions)}
            best_cost = sum((self.logical_weights[edge] * self.physical_weights[tuple(sorted((chip_selection[edge[0]], chip_selection[edge[1]])))] for edge in self.logical_weights))
        else:
            (chip_selection, best_cost, _, _) = chip_selection_ILP(self.logical_weights, self.physical_weights, segment_sizes=segment_sizes, chip_capacities=chip_capacities)
        chip_selection_time = time.time() - chip_selection_time
        print(f'[INFO] Chip selection time: {chip_selection_time:.3f}s')
        (chip_selection, best_cost) = _finalize_chip_selection_result(program_segment_count=num_partitions, chiplet_count=len(self.chip_pos), chip_selection=chip_selection, best_cost=best_cost, logical_weights=self.logical_weights, physical_weights=self.physical_weights)
        static_oee_cost = int(sum(self.logical_weights.values()))
        self.args.mapping_cost_ilp = int(best_cost)
        self.args.mapping_cost_wbcp_dynamic = int(wbcp_cost)
        self.args.mapping_cost_static_oee = static_oee_cost
        self.args.mapping_cost = static_oee_cost
        self.cost = static_oee_cost
        remap_time = time.time()
        qubit_mapping = self.remap(program_segments, chip_selection)
        remap_time = time.time() - remap_time
        print(f'[INFO] Remap time: {remap_time:.3f}s')
        physical_program = []
        for (q1, q2) in self.program:
            physical_q1 = qubit_mapping.get(q1, q1)
            physical_q2 = qubit_mapping.get(q2, q2)
            physical_program.append((physical_q1, physical_q2))
        return (mapped_cmap, physical_program, qubit_mapping, [process_time1, wbcp_time, chip_selection_time, remap_time, static_oee_cost])

    def _mapping_gcp(self, mapped_cmap, G, num_program_qubits, NUM_CHIPLETS_X, NUM_CHIPLETS_Y, qubits_per_chiplet, process_time1, variant='GCP', chip_capacities=None):
        num_chiplets = NUM_CHIPLETS_X * NUM_CHIPLETS_Y
        if chip_capacities is None:
            chip_capacities = self._get_chip_capacities()
        sorted_caps = [chip_capacities[pos] for pos in sorted(chip_capacities.keys())]
        gcp_time = time.time()
        if variant == 'GCP-S':
            gcp_variant = 'GCP-S'
        else:
            gcp_variant = 'GCP-E'
        (partition_map, gcp_cost) = gcp_partition(program=self.program, num_qubits=num_program_qubits, num_chiplets=num_chiplets, chiplet_capacity=qubits_per_chiplet, chiplet_capacities=sorted_caps, population_size=getattr(self.args, 'gcp_population_size', 50), num_generations=getattr(self.args, 'gcp_num_generations', 100), mutation_k=getattr(self.args, 'gcp_mutation_k', 10), seed=self.args.seed, variant=gcp_variant)
        gcp_time = time.time() - gcp_time
        print(f'[INFO] GCP partition time: {gcp_time} seconds, cost: {gcp_cost}')
        used_parts = sorted(set(partition_map.values()))
        part_remap = {old: new for (new, old) in enumerate(used_parts)}
        num_partitions = len(used_parts)
        remapped = {q: part_remap[p] for (q, p) in partition_map.items()}
        (program_segments, cut_graph) = self.construct_sub_graph(G, remapped, num_partitions)
        print(f'[INFO] GCP partitions: {num_partitions}, segment sizes: {[len(seg) for seg in program_segments]}')
        chip_selection_time = time.time()
        if variant == 'GCP-ILP':
            segment_sizes = {i: len(list(seg.nodes())) for (i, seg) in enumerate(program_segments)}
            (chip_selection, best_cost, _, _) = chip_selection_ILP(self.logical_weights, self.physical_weights, segment_sizes=segment_sizes, chip_capacities=chip_capacities)
        else:
            chip_selection = {i: i for i in range(num_partitions)}
            best_cost = sum((self.logical_weights[edge] * self.physical_weights[tuple(sorted((chip_selection[edge[0]], chip_selection[edge[1]])))] for edge in self.logical_weights))
        chip_selection_time = time.time() - chip_selection_time
        (chip_selection, best_cost) = _finalize_chip_selection_result(program_segment_count=num_partitions, chiplet_count=len(self.chip_pos), chip_selection=chip_selection, best_cost=best_cost, logical_weights=self.logical_weights, physical_weights=self.physical_weights)
        static_oee_cost = int(sum(self.logical_weights.values()))
        self.args.mapping_cost_gcp = int(gcp_cost)
        self.args.mapping_cost_ilp = int(best_cost)
        self.args.mapping_cost_static_oee = static_oee_cost
        self.args.mapping_cost = static_oee_cost
        self.cost = static_oee_cost
        remap_time = time.time()
        qubit_mapping = self.remap(program_segments, chip_selection)
        remap_time = time.time() - remap_time
        print(f'[INFO] Remap time: {remap_time} seconds')
        physical_program = []
        for (q1, q2) in self.program:
            physical_q1 = qubit_mapping.get(q1, q1)
            physical_q2 = qubit_mapping.get(q2, q2)
            physical_program.append((physical_q1, physical_q2))
        return (mapped_cmap, physical_program, qubit_mapping, [process_time1, gcp_time, chip_selection_time, remap_time, static_oee_cost])

    def remap(self, program_segments, chip_selection):
        if self.hardware.is_new_model:
            return self._remap_flat_pool(program_segments, chip_selection)
        return self._remap_aod_slm(program_segments, chip_selection)

    def _remap_flat_pool(self, program_segments, chip_selection):
        new_qubit_mapping = {}
        for (i, program_segment) in enumerate(program_segments):
            logical_qubits = sorted(program_segment.nodes())
            chip_idx = chip_selection[i]
            (cx, cy) = self.chip_pos[chip_idx]
            chip_cap = self.hardware.get_chip_capacity((cx, cy))
            if len(logical_qubits) > chip_cap:
                raise ValueError(f'[FATAL] Segment {i} has {len(logical_qubits)} qubits, which exceeds chip ({cx},{cy}) capacity of {chip_cap}')
            physical_slots = self.hardware.chip_to_qubits[cx, cy]
            for (lq, pq) in zip(logical_qubits, physical_slots):
                new_qubit_mapping[int(lq)] = int(pq)
        return new_qubit_mapping

    def _remap_aod_slm(self, program_segments, chip_selection):
        """Original AOD/SLM remap with Kernighan-Lin bisection."""
        new_qubit_mapping = {}
        physical_idx_to_qubit_idx = {tuple(v): k for (k, v) in self.hardware.qubit_idx_to_physical_idx.items()}
        for (i, program_segment) in enumerate(program_segments):
            logical_qubits = list(program_segment)
            chip_idx = chip_selection[i]
            (cx, cy) = self.chip_pos[chip_idx]
            G_seg = program_segment.subgraph(logical_qubits)
            if len(G_seg.nodes()) > self.hardware.num_x * self.hardware.num_y * 2:
                raise ValueError(f'[FATAL] Segment {i} has {len(G_seg.nodes())} qubits, which exceeds chiplet capacity of {self.hardware.num_x * self.hardware.num_y * 2}')
            try:
                cut_sets = list(nx_comm.kernighan_lin_bisection(G_seg))
            except Exception:
                cut_sets = [logical_qubits[:len(logical_qubits) // 2], logical_qubits[len(logical_qubits) // 2:]]
            (V_aod, V_slm) = cut_sets
            aod_idx_set = [physical_idx_to_qubit_idx[cx, cy, x, y, 1] for x in range(self.hardware.num_x) for y in range(self.hardware.num_y)]
            slm_idx_set = [physical_idx_to_qubit_idx[cx, cy, x, y, 0] for x in range(self.hardware.num_x) for y in range(self.hardware.num_y)]
            print(f'[INFO] AOD/SLM indices: {len(aod_idx_set)}, {len(slm_idx_set)}, len(V_aod): {len(V_aod)}, len(V_slm): {len(V_slm)}')
            if len(V_aod) > len(aod_idx_set) or len(V_slm) > len(slm_idx_set):
                raise ValueError(f'[ERROR] Not enough AOD/SLM qubits for 2-cut assignment on chip ({cx},{cy})')
            for (lq, pq) in zip(V_aod, aod_idx_set):
                new_qubit_mapping[int(lq)] = int(pq)
            for (lq, pq) in zip(V_slm, slm_idx_set):
                new_qubit_mapping[int(lq)] = int(pq)
        return new_qubit_mapping

    def compile(self):
        if self.hardware.is_new_model:
            arch_frag = f'S{self.args.system_qubits_per_chip}C{self.args.num_communication_per_link}-{self.args.numchipletsx}x{self.args.numchipletsy}'
        else:
            arch_frag = f'{self.args.numx}x{self.args.numy}-{self.args.numchipletsx}x{self.args.numchipletsy}'
        result_dir = f'{self.args.results_dir}/{self.args.name}/{self.args.mapping_method}/{arch_frag}'
        (mapped_cmap, physical_program, qubit_mapping, compile_time) = self.mapping()
        layers = self.program_to_layers(physical_program)
        for (i, layer) in enumerate(layers):
            print(f'[INFO] Layer {i}: {layer}')
        self.qubit_mapping = qubit_mapping
        self.mapped_cmap = mapped_cmap
        self.layers = layers
        self.args.compile_time_mapper = sum(compile_time[:4])
        os.makedirs(result_dir, exist_ok=True)
        with open(f'{result_dir}/mapping.json', 'w') as f:
            json_seralizable = convert_ndarray_to_list(self.qubit_mapping)
            print(f'[INFO] Mapping: {json_seralizable}')
            json.dump(json_seralizable, f)
        with open(f'{result_dir}/layers.json', 'w') as f:
            json_seralizable = convert_ndarray_to_list(self.layers)
            json.dump(json_seralizable, f)
        with open(f'{result_dir}/compile_time.json', 'w') as f:
            compile_time_dict = {'preprocessing_time': compile_time[0], 'k_partitioning_time': compile_time[1], 'chip_selection_time': compile_time[2], 'remap_time': compile_time[3], 'cost_static_oee': compile_time[4], 'cost_ilp': getattr(self.args, 'mapping_cost_ilp', None), 'cost_wbcp_dynamic': getattr(self.args, 'mapping_cost_wbcp_dynamic', None)}
            json.dump(compile_time_dict, f)
        return (self.qubit_mapping, self.layers)