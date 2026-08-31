import os
import time
from collections import Counter, defaultdict
from pathlib import Path
import networkx as nx
from route import BenchmarkSetup, schedule_blocks
from route.cache import clear_graph_cache
from route.route.qucomm import build_qucomm_execution_window
from router.block_formation.buffer_design import communication_buffer_design
from router.optim.block_routing.iris import RoutingState
from router.optim.restore_path import clear_performance_caches as clear_restore_path_caches
from router.optim.early_execution import pipeline_optimization, remove_duplicate_rows
from utils import atomic_json_dump, logger
from ._baseline import BaselineRouter
from ._constants import _normalize_channels_struct_only
from ._dag import BuildBlockDAG
from ._utils import _qucomm_window_lookahead_depth, routing_method
from ._validation import get_agg_node

def _slim_atom_paths(atom_paths):
    """Return {qubit: [current_pos]} — just the tip of each path."""
    return {k: [v[-1]] for (k, v) in atom_paths.items()}

def _merge_atom_path_moves(canonical, plan_paths):
    for (q, path) in plan_paths.items():
        if len(path) > 1:
            if q in canonical:
                canonical[q].extend(path[1:])
            else:
                canonical[q] = list(path)

class IRISRouter(BaselineRouter):

    @staticmethod
    def _is_new_model(args):
        return getattr(args, 'system_qubits_per_chip', None) is not None and getattr(args, 'num_communication_per_link', None) is not None

    @staticmethod
    def _neighbor_count(cx, cy, numchipletsx, numchipletsy):
        count = 0
        if cx > 0:
            count += 1
        if cx < numchipletsx - 1:
            count += 1
        if cy > 0:
            count += 1
        if cy < numchipletsy - 1:
            count += 1
        return count

    def _get_comm_qubits_per_link(self):
        """Return the per-link EPR capacity."""
        if self._is_new_model(self.args):
            return int(self.args.num_communication_per_link)
        return int(self.args.num_communication_qubits)

    def _get_node_epr_capacity(self, node):
        """Return total EPR capacity for a chip node (cx, cy)."""
        if self._is_new_model(self.args):
            (cx, cy) = node
            n = self._neighbor_count(cx, cy, self.args.numchipletsx, self.args.numchipletsy)
            return int(self.args.num_communication_per_link) * n
        return int(self.args.num_communication_qubits)

    def __init__(self, args, qubit_mapping=None, atom_idx_to_physical_pos=None):
        super().__init__(args, qubit_mapping, atom_idx_to_physical_pos)
        self.compile_time_circuit_rewriting = 0
        self.compile_time_block_updating = 0
        self.compile_time_communication_fusion = 0
        self.compile_time_for_block_scheduling = 0
        self.compile_time_for_early_execution = 0
        self.distribution_of_channels_on_large_block = []
        self.distribution_of_channels_on_small_blocks = []
        self.operation_info_on_large_block = []
        self.operation_info_on_small_blocks = []
        self.num_external_qubits_on_large_block = []
        self.num_internal_qubits_on_large_block = []
        self.num_external_qubits_on_small_blocks = []
        self.num_internal_qubits_on_small_blocks = []
        self.block_is_split = []
        self.pre_schedule_channel_dict = None

    def _run_pipeline_optimization(self, pipeline, initial_channel_dict, min_comm_value, max_comm_value):
        (opt_pipeline, early_executed_dict) = pipeline_optimization(list(pipeline), dict(initial_channel_dict), min_comm_value, max_comm_value, debug=True, progress_fn=None, retry_trace_interval=0, block_trace_interval=0)
        return (opt_pipeline, early_executed_dict)

    @staticmethod
    def _merge_schedule_segments(schedules, after_schedule):
        if len(schedules) == 0:
            return list(after_schedule)
        for after_sch in after_schedule:
            prev_atoms = set()
            for sched_entry in schedules[-1]:
                prev_atoms.add(sched_entry['SIdx'])
                prev_atoms.add(sched_entry['TIdx'])
            curr_atoms = set()
            for sched_entry in after_sch:
                curr_atoms.add(sched_entry['SIdx'])
                curr_atoms.add(sched_entry['TIdx'])
            if len(curr_atoms & prev_atoms) == 0:
                schedules[-1].extend(after_sch)
            else:
                schedules.append(after_sch)
        return schedules

    @staticmethod
    def _build_ees_flat_pipeline(schedule_segments):
        from .optim.ees import append_schedule_segment_to_pipeline
        pipeline = []
        duplicated = set()
        segment_start = 0
        current_segment_max_time = None
        prev_segment_atoms = set()
        for schedule in schedule_segments:
            curr_atoms = set()
            for entry in schedule:
                curr_atoms.add(entry['SIdx'])
                curr_atoms.add(entry['TIdx'])
            seg_max_time = max((entry['Time'] for entry in schedule), default=0)
            if current_segment_max_time is None:
                append_schedule_segment_to_pipeline(pipeline, schedule, start_T=segment_start, duplicated=duplicated)
                current_segment_max_time = seg_max_time
                prev_segment_atoms = curr_atoms
                continue
            overlap = len(curr_atoms & prev_segment_atoms)
            if overlap == 0:
                append_schedule_segment_to_pipeline(pipeline, schedule, start_T=segment_start, duplicated=duplicated)
                current_segment_max_time = max(current_segment_max_time, seg_max_time)
                prev_segment_atoms.update(curr_atoms)
                continue
            segment_start += int(current_segment_max_time) + 1
            append_schedule_segment_to_pipeline(pipeline, schedule, start_T=segment_start, duplicated=duplicated)
            current_segment_max_time = seg_max_time
            prev_segment_atoms = curr_atoms
        return pipeline

    @staticmethod
    def _flatten_epoch_pipelines(epoch_pipelines):
        flat_pipeline = []
        time_offset = 0
        for epoch_pipeline in epoch_pipelines:
            if len(epoch_pipeline) == 0:
                continue
            for row in epoch_pipeline:
                new_row = row.copy()
                new_row['Time'] += time_offset
                flat_pipeline.append(new_row)
            time_offset += max((row['Time'] for row in epoch_pipeline)) + 1
        return flat_pipeline

    @staticmethod
    def _merge_early_executed_dicts(dst, src):
        for (host_block, rows) in src.items():
            if host_block not in dst:
                dst[host_block] = []
            dst[host_block].extend((row.copy() for row in rows))
        return dst

    def _build_uniform_channel_dict(self):
        channel_dict = defaultdict(int)
        numchipletsx = self.args.numchipletsx
        numchipletsy = self.args.numchipletsy
        num_comm_per_link = self._get_comm_qubits_per_link()
        for x in range(numchipletsx):
            for y in range(numchipletsy):
                for (dx, dy) in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    (px, py) = (x + dx, y + dy)
                    if 0 <= px < numchipletsx and 0 <= py < numchipletsy:
                        channel_dict[(x, y), (px, py)] = num_comm_per_link
                        channel_dict[(px, py), (x, y)] = num_comm_per_link
        return channel_dict

    def _build_initial_channel_dict(self):
        if getattr(self, 'pre_schedule_channel_dict', None):
            return defaultdict(int, {tuple(edge): int(cap) for (edge, cap) in self.pre_schedule_channel_dict.items()})
        channel_dict = self._build_uniform_channel_dict()
        for (edge, cap) in getattr(self, 'pre_schedule_channel_overrides', {}).items():
            channel_dict[tuple(edge)] = int(cap)
        return channel_dict

    def schedule_qucomm(self, layers, verbose=False):
        clear_graph_cache()
        clear_restore_path_caches()
        route_algo = getattr(self.args, 'qucomm_route_algo', None) or 'our_qucomm'
        self.start_time = time.time()
        logger.info('Starting IRISRouter schedule execution')
        self.reset_metrics(layers)
        self.initialize_atom_dag()
        self.n_gates_called = defaultdict(int)
        for layer in layers:
            for (g0, g1) in layer:
                self.n_gates_called[g0] += 1
                self.n_gates_called[g1] += 1
        n_gates_called_sum = sum(self.n_gates_called.values())
        for (k, v) in self.n_gates_called.items():
            self.n_gates_called[k] = v / max(1, n_gates_called_sum)
        _circuit_rewriting_start = time.time()
        self.preprocess_gates()
        self.compile_time_circuit_rewriting = time.time() - _circuit_rewriting_start
        uniform_channel_dict = dict(self._build_uniform_channel_dict())
        partition = {int(atom): pos for (atom, pos) in self.position_table.items()}
        epr_capacity = {node: self._get_node_epr_capacity(node) for node in self.connectivity.nodes()}
        dist_matrix = dict(nx.all_pairs_shortest_path_length(self.connectivity))
        (updated_partition, updated_epr_capacity, channel_dict_for_buffer) = communication_buffer_design([gate for gate in self.gate_order if not gate.is_done], partition, self.connectivity, dist_matrix, epr_capacity, dict(uniform_channel_dict), None)
        self.pre_schedule_channel_dict = dict(channel_dict_for_buffer)
        for (atom, old_pos) in partition.items():
            new_pos = tuple(updated_partition.get(atom, old_pos))
            self.position_table[atom] = new_pos
            if self.atom_idx_to_physical_pos is not None and atom in self.atom_idx_to_physical_pos:
                p = list(self.atom_idx_to_physical_pos[atom])
                if len(p) >= 2:
                    (p[0], p[1]) = new_pos
                    self.atom_idx_to_physical_pos[atom] = tuple(p)
        for gate in self.gate_order:
            gate.pos0 = self.position_table[int(gate.atom0)]
            gate.pos1 = self.position_table[int(gate.atom1)]
        for gate in self.gates:
            gate.pos0 = self.position_table[int(gate.atom0)]
            gate.pos1 = self.position_table[int(gate.atom1)]
        for (node, cap) in updated_epr_capacity.items():
            if node in self.num_ancillae_per_chip:
                self.num_ancillae_per_chip[node] = int(cap)
        self.CommunicationFusion(verbose=True)
        self.num_ops_per_comm_block = [len(l) for l in self.communication_blocks]
        self.count_dict = dict(Counter(self.num_ops_per_comm_block))
        (self.DAG, self.levels, self.depth) = BuildBlockDAG(self.communication_blocks, self.aggregation_nodes)
        self.num_blocks = len(self.DAG.nodes())
        atom_paths = defaultdict(list)
        for (atom, pos) in self.position_table.items():
            atom_paths[int(atom)].append(pos)
        enable_ees = bool(getattr(self.args, 'enable_ees', False))
        schedules = []
        ees_pipeline = []
        ees_epochs = []
        ees_duplicated = set()
        ees_segment_start = 0
        ees_current_segment_max_time = None
        ees_prev_segment_atoms = set()
        self._reset_block_metric_tracking()
        channel_dict = self._build_initial_channel_dict()
        self.pre_schedule_chip_data_qubit_counts = {tuple(node): int(count) for (node, count) in sorted(Counter(self.position_table.values()).items(), key=lambda item: str(item[0]))}
        initial_channel_dict = dict(channel_dict)
        cnt = 0
        gate_cnt = 0
        block_id_cnt = 0
        round_num = 0
        position_at_t = {k: v[-1] for (k, v) in atom_paths.items()}
        start_time = time.time()
        blocks = self.communication_blocks
        self.compile_time_communication_fusion = time.time() - start_time
        interact_info = defaultdict(list)
        for block in blocks:
            for g in block:
                interact_info[int(g.atom0)].append(g)
                interact_info[int(g.atom1)].append(g)
        interact_info = dict(interact_info)
        while gate_cnt < self.num_gates:
            position_at_t = {k: v[-1] for (k, v) in atom_paths.items()}
            program_weights = self.get_program_weights(blocks, position_at_t)
            v_sum = sum(program_weights.values())
            program_dist = defaultdict(float)
            manhattan_dist_max = abs(self.args.numchipletsx - 1) + abs(self.args.numchipletsy - 1)
            for (k, v) in program_weights.items():
                md = abs(k[0][0] - k[1][0]) + abs(k[0][1] - k[1][1])
                program_dist[int(md)] += v / v_sum
            distribution = [program_dist[i] for i in range(manhattan_dist_max + 1)]
            self.program_weights_over_time.append(distribution)
            cnt += 1
            window = build_qucomm_execution_window(blocks=blocks, execution_block_count=self.args.K1, block_id_start=block_id_cnt, position_table=position_at_t, connectivity=self.connectivity, base_agg_func=get_agg_node, lookahead_depth=_qucomm_window_lookahead_depth(self.args), block_level_lookup=self.levels, future_window_mode=self.args.qucomm_future_window_mode)
            next_blocks = window['next_blocks']
            future_blocks = window['future_blocks']
            window_blocks = window['window_blocks']
            window_aggs = window['window_aggs']
            window_ids = window['window_ids']
            window_block_levels = [self.levels.get(block_id) for block_id in window_ids]
            start_state = RoutingState(position_table=dict(position_at_t), channel_dict=_normalize_channels_struct_only(dict(channel_dict)), atom_paths=_slim_atom_paths(atom_paths))
            K = window['execution_k']
            start_time = time.time()
            setup = BenchmarkSetup(blocks=window_blocks, aggs=window_aggs, block_ids=window_ids, start_state=start_state, connectivity=self.connectivity, interact_info=interact_info, K=K)
            plan = schedule_blocks(setup.blocks, setup.aggs, setup.block_ids, setup.start_state, setup.connectivity, setup.K, block_levels=window_block_levels, interact_info=setup.interact_info, route_algo=route_algo, qucomm_enable_gate_lookahead=self.args.qucomm_enable_gate_lookahead, qucomm_gate_lookahead_depth=self.args.qucomm_gate_lookahead_depth, qucomm_gate_lookahead_beam_width=self.args.qucomm_gate_lookahead_beam_width, qucomm_gate_lookahead_option=self.args.qucomm_gate_lookahead_option, qucomm_gate_lookahead_sort_mode=self.args.qucomm_gate_lookahead_sort_mode, qucomm_gate_lookahead_prune_mode=self.args.qucomm_gate_lookahead_prune_mode, qucomm_future_block_decay_mode=self.args.qucomm_future_block_decay_mode, qucomm_enable_gate_foresight=self.args.qucomm_enable_gate_foresight, save_qucomm_block_lookahead_debug=self.args.save_qucomm_block_lookahead_debug, candidate_eval_mode=self.args.qucomm_candidate_eval_mode, one_meet_tiebreak_mode=self.args.qucomm_one_meet_tiebreak_mode, enable_teleport_hybrid=self.args.qucomm_enable_teleport_hybrid, disable_future_touch=getattr(self.args, 'qucomm_disable_future_touch', False))
            end_time = time.time()
            self.compile_time_for_block_scheduling += end_time - start_time
            self._record_qucomm_lookahead_debug(plan)
            self.distribution_of_channels_on_large_block.append(dict(plan.state_after.channel_dict))
            self.num_external_qubits_on_large_block.append([info.num_external_qubits for info in plan.per_block_info])
            self.num_internal_qubits_on_large_block.append([info.num_internal_qubits for info in plan.per_block_info])
            self.operation_info_on_large_block.append([(m.relocates, m.recnots, m.releases) for m in plan.per_block_metrics])
            n_done = len(plan.done_ids)
            done_blocks = next_blocks[:n_done]
            blocks = next_blocks[n_done:] + future_blocks
            block_id_cnt += n_done
            for (block_id, block, block_agg) in zip(plan.done_ids, done_blocks, plan.aggs):
                self.blocks_agg_node[block_id] = block_agg
                for gate in block:
                    gate.is_done = True
                    gate_cnt += 1
            segment_start_channel_dict = dict(channel_dict)
            channel_dict = dict(plan.state_after.channel_dict)
            _merge_atom_path_moves(atom_paths, plan.state_after.atom_paths)
            if plan.interact_info is None:
                interact_info = None
            else:
                interact_info = {q: list(gates) for (q, gates) in plan.interact_info.items()}
            after_schedule = plan.combined_schedule
            if enable_ees:
                from .optim.ees import append_schedule_segment_to_pipeline
                for after_sch in after_schedule:
                    curr_atoms = set()
                    for s in after_sch:
                        curr_atoms.add(s['SIdx'])
                        curr_atoms.add(s['TIdx'])
                    seg_max_time = max((s['Time'] for s in after_sch), default=0)
                    if ees_current_segment_max_time is None:
                        append_schedule_segment_to_pipeline(ees_pipeline, after_sch, start_T=ees_segment_start, duplicated=ees_duplicated)
                        ees_current_segment_max_time = seg_max_time
                        ees_prev_segment_atoms = curr_atoms
                    else:
                        overlap = len(curr_atoms & ees_prev_segment_atoms)
                        if overlap == 0:
                            append_schedule_segment_to_pipeline(ees_pipeline, after_sch, start_T=ees_segment_start, duplicated=ees_duplicated)
                            ees_current_segment_max_time = max(ees_current_segment_max_time, seg_max_time)
                            ees_prev_segment_atoms.update(curr_atoms)
                        else:
                            ees_segment_start += int(ees_current_segment_max_time) + 1
                            append_schedule_segment_to_pipeline(ees_pipeline, after_sch, start_T=ees_segment_start, duplicated=ees_duplicated)
                            ees_current_segment_max_time = seg_max_time
                            ees_prev_segment_atoms = curr_atoms
                ees_epochs.append({'initial_channel_dict': segment_start_channel_dict, 'schedules': [list(seg) for seg in after_schedule]})
            schedules = self._merge_schedule_segments(schedules, after_schedule)
            for (block_id, per_block_metric) in zip(plan.done_ids, plan.per_block_metrics):
                self._record_plan_block_metric(block_id, per_block_metric)
            round_num += 1
        from .optim.ees import run_ees
        mode_tag = f'{self.args.K1}-{self.args.K2}'
        if enable_ees:
            epoch_pipelines = [remove_duplicate_rows(self._build_ees_flat_pipeline(epoch['schedules'])) for epoch in ees_epochs]
            pipeline = self._flatten_epoch_pipelines(epoch_pipelines)
            if getattr(self.args, 'save_pipeline_json', False):
                base = Path(self.args.routing_output_dir)
                os.makedirs(base, exist_ok=True)
                atomic_json_dump(pipeline, base / f'no-opt-{mode_tag}.json', sort_keys=True)
            start_time = time.time()
            opt_pipeline = []
            early_executed_dict = {}
            for (epoch, epoch_pipeline) in zip(ees_epochs, epoch_pipelines):
                if len(epoch_pipeline) == 0:
                    continue
                (epoch_opt_pipeline, epoch_early_executed_dict) = self._run_pipeline_optimization(epoch_pipeline, epoch['initial_channel_dict'], 0, self._get_comm_qubits_per_link() * 2)
                opt_pipeline = self._merge_schedule_segments(opt_pipeline, epoch_opt_pipeline)
                self._merge_early_executed_dicts(early_executed_dict, epoch_early_executed_dict)
            self.compile_time_for_early_execution += time.time() - start_time
            self.early_executed_dict = early_executed_dict
            cnt = 0
            self.IRLayers = []
            for p in opt_pipeline:
                self.IRLayers.append(self.GetQuCommLookaheadIR(p, verbose=verbose, cnt=cnt))
                cnt += 1
        else:
            cnt = 0
            self.IRLayers = []
            for schedule in schedules:
                LookaheadIRs = self.GetQuCommLookaheadIR(schedule, verbose=verbose, cnt=cnt)
                cnt += 1
                self.IRLayers.append(LookaheadIRs)
            (opt_pipeline, early_executed_dict, elapsed) = run_ees(schedules=schedules, initial_channel_dict=initial_channel_dict, num_communication_qubits=self._get_comm_qubits_per_link(), output_base=self.args.routing_output_dir, mode_tag=mode_tag, enable_ees=False, save_pipeline_json=getattr(self.args, 'save_pipeline_json', False))
            self.compile_time_for_early_execution += elapsed
        self.post_metrics()
        return self.results

    @routing_method
    def schedule(self, layers, verbose=False):
        return self.schedule_qucomm(layers, verbose=verbose)