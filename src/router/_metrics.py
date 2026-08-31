"""Metrics mixin — extracted from _baseline.py."""
import copy
import math
import time
from collections import defaultdict
from ._constants import compute_execution_layers_from_dag, compute_inter_block_distance_metric, compute_routing_cost, logger
from ._utils import serialize_dict

class MetricsMixin:
    """Methods for computing and reporting compilation metrics."""

    def _op_fidelity(self, operation):
        if operation == 'Local CNOT':
            return float(self.args.fidelity_2Q)
        if operation == 'Transfer':
            return float(self.args.fidelity_transfer)
        if operation == 'Re-CNOT':
            return float(self.args.fidelity_remote_2Q)
        if operation == 'RELOCATE':
            return float(self.args.fidelity_relocation)
        return 1.0

    def _counts_after_operation(self, operation):
        return {'local_cnots': int(getattr(self, 'num_CNOTs', 0)) + int(operation == 'Local CNOT'), 'transfers': int(getattr(self, 'num_transfers', 0)) + int(operation == 'Transfer'), 'remote_cnots': int(getattr(self, 'num_interconnect_CNOTs', 0)) + int(operation == 'Re-CNOT'), 'relocates': int(getattr(self, 'num_interconnect_SWAPs', 0)) + int(operation == 'RELOCATE')}

    def _decoherence_fidelity_at_time(self, event_end_time):
        num_qubits = int(getattr(self.args, 'num_qubits', 0) or 0)
        coherence_time = float(getattr(self.args, 'coherence_time', 0) or 0)
        if num_qubits <= 0 or coherence_time <= 0:
            return 1.0
        return float(math.exp(-num_qubits * float(event_end_time) / coherence_time))

    def _resolved_total_execution_time(self):
        total_execution_time = getattr(self, 'total_execution_time', None)
        if total_execution_time is not None:
            return float(total_execution_time)
        tracer = getattr(self, 'tracer', None)
        if tracer is None:
            return 0.0
        try:
            df = tracer.to_dataframe(sort_by_count=True)
        except Exception:
            return 0.0
        if df.empty or 'end_time' not in df.columns:
            return 0.0
        return float(df['end_time'].max())

    def _build_tracer_fidelity_metadata(self, operation, event_end_time):
        counts = self._counts_after_operation(operation)
        cum_fidelity_local_2q = float(self.args.fidelity_2Q) ** counts['local_cnots']
        cum_fidelity_transfer = float(self.args.fidelity_transfer) ** counts['transfers']
        cum_fidelity_remote_2q = float(self.args.fidelity_remote_2Q) ** counts['remote_cnots']
        cum_fidelity_relocation = float(self.args.fidelity_relocation) ** counts['relocates']
        cum_fidelity_deco = self._decoherence_fidelity_at_time(event_end_time)
        cum_fidelity_total = cum_fidelity_local_2q * cum_fidelity_transfer * cum_fidelity_remote_2q * cum_fidelity_relocation * cum_fidelity_deco
        op_fidelity = self._op_fidelity(operation)
        return {'op_fidelity': op_fidelity, 'op_infidelity': 1.0 - op_fidelity, 'cum_local_cnots': counts['local_cnots'], 'cum_transfers': counts['transfers'], 'cum_remote_cnots': counts['remote_cnots'], 'cum_relocates': counts['relocates'], 'cum_fidelity_local_2q': cum_fidelity_local_2q, 'cum_fidelity_transfer': cum_fidelity_transfer, 'cum_fidelity_remote_2q': cum_fidelity_remote_2q, 'cum_fidelity_relocation': cum_fidelity_relocation, 'cum_fidelity_deco': cum_fidelity_deco, 'cum_fidelity_total': cum_fidelity_total}

    def _update_total_fidelity_metrics(self):
        self.fidelity_2Q = float(self.args.fidelity_2Q) ** int(getattr(self, 'num_local_cnots', 0))
        self.fidelity_transfer = float(self.args.fidelity_transfer) ** int(getattr(self, 'num_transfers', 0))
        self.fidelity_remote_2Q_total = float(self.args.fidelity_remote_2Q) ** int(getattr(self, 'num_gate_teleportations', 0))
        self.fidelity_relocation_total = float(self.args.fidelity_relocation) ** int(getattr(self, 'num_state_teleportations', 0))
        self.fidelity_int = self.fidelity_remote_2Q_total * self.fidelity_relocation_total
        self.total_execution_time = self._resolved_total_execution_time()
        self.fidelity_deco = self._decoherence_fidelity_at_time(self.total_execution_time)
        self.fidelity_total = self.fidelity_2Q * self.fidelity_transfer * self.fidelity_int * self.fidelity_deco
        self.latency_penalty = self.total_execution_time
        self.fidelity_penalty = -math.log(self.fidelity_total) if self.fidelity_total > 0 else float('inf')
        self.total_cost = float(getattr(self.args, 'alpha', 0)) * self.latency_penalty + float(getattr(self.args, 'beta', 0)) * self.fidelity_penalty

    @property
    def effective_number_of_cnots(self):
        num_local_ops    = self.num_CNOTs
        num_local_swaps  = (self.num_transfers
                            * (1-self.args.fidelity_transfer)/(1-self.args.fidelity_2Q)
                            * (self.args.time_transfer+self.args.time_move)/(self.args.time_2Q + self.args.time_move)
        )
        num_remote_cnots = (self.num_interconnect_CNOTs
                            * (1 - self.args.fidelity_remote_2Q) / (1 - self.args.fidelity_2Q)
                            * (self.args.time_int_2Q)/(self.args.time_2Q + self.args.time_move)
        )
        num_relocations  = (
            self.num_interconnect_SWAPs
            * (1 - self.args.fidelity_relocation) / (1 - self.args.fidelity_2Q)
            * (self.args.time_int_SWAP)/(self.args.time_2Q + self.args.time_move)
        )
        return int(num_local_ops + num_local_swaps + num_remote_cnots + num_relocations)

    def xop2localop(self, gates):
        """Convert X-ops to LocalOps"""
        if not hasattr(self, 'remote_cnot_info'):
            self.remote_cnot_info = {}
        logger.info(f'Converting {len(gates)} X-ops to LocalOps')
        for (idx, gate) in enumerate(gates):
            optype = gate[2]
            (src, dst) = (gate[4][0], gate[4][1])
            (src_pos, dst_pos) = (gate[1][0], gate[1][1])
            if 'Re-CNOT' == optype:
                if self.remote_cnot_info.get(src, None) is None:
                    self.remote_cnot_info[src] = {'dst': dst, 'src_pos': src_pos, 'dst_pos': dst_pos}
                    continue
                if self.remote_cnot_info[src]['src_pos'] == src_pos and self.remote_cnot_info[src]['dst_pos'] == dst_pos:
                    gate_tmp = list(gate)
                    if optype == 'Re-CNOT':
                        gate_tmp[2] = 'Local CNOT'
                        gate_tmp[3] = self.args.time_2Q + self.args.time_move
                        self.ccop_to_localop.add(gate[-1].split('_')[0])
                    gates[idx] = tuple(gate_tmp)
                else:
                    self.remote_cnot_info[src] = {'dst': dst, 'src_pos': src_pos, 'dst_pos': dst_pos}
                    continue
            elif 'RELOCATE' == optype:
                self.remote_cnot_info[src] = None
            elif 'Local CNOT' == optype:
                self.remote_cnot_info[src] = None
        return gates

    def post_metrics(self):
        self.get_executable()
        self.num_local_cnots = int(getattr(self, 'num_CNOTs', 0))
        self.num_state_teleportations = int(getattr(self, 'num_interconnect_SWAPs', 0))
        self.num_gate_teleportations = int(getattr(self, 'num_interconnect_CNOTs', 0))
        self.num_effective_cnots = int(self.num_local_cnots + self.num_state_teleportations * (self.args.time_int_SWAP / (self.args.time_2Q + self.args.time_move) * (1 - self.args.fidelity_relocation) / (1 - self.args.fidelity_2Q)) + self.num_gate_teleportations * (self.args.time_int_2Q / (self.args.time_2Q + self.args.time_move) * (1 - self.args.fidelity_remote_2Q) / (1 - self.args.fidelity_2Q)))
        self._update_total_fidelity_metrics()
        end_time = time.time()
        self.args.compile_time_router = end_time - self.start_time
        return self.results

    def get_program_weights(self, blocks, position_table_at_t):
        weights = defaultdict(int)
        for block in blocks:
            for gate in block:
                edge = (position_table_at_t[gate.atom0], position_table_at_t[gate.atom1])
                edge_reverse = (position_table_at_t[gate.atom1], position_table_at_t[gate.atom0])
                if edge == edge_reverse:
                    weights[edge] += 1
                else:
                    weights[edge] += 1
                    weights[edge_reverse] += 1
        weights = {k: v for (k, v) in weights.items() if k[0] <= k[1]}
        return weights

    def _compute_inter_block_distance_metric(self):
        communication_blocks = getattr(self, 'communication_blocks', [])
        if not communication_blocks:
            return (0.0, 0, 0)
        execution_layers = {}
        dag = getattr(self, 'DAG', None)
        if dag is not None:
            try:
                execution_layers = compute_execution_layers_from_dag(dag)
            except ValueError:
                execution_layers = {}
        if not execution_layers:
            execution_layers = getattr(self, 'levels', {}) or {}
        return compute_inter_block_distance_metric(communication_blocks, execution_layers=execution_layers)

    @property
    def results(self):
        per_block_metrics = copy.deepcopy(self.per_block_metric_records)
        num_evictions = sum((metric['evictions'] for metric in per_block_metrics))
        num_relocations = sum((metric['relocates'] for metric in per_block_metrics))
        num_recnots = sum((metric['recnots'] for metric in per_block_metrics))
        num_channel_releases = sum((metric['releases'] for metric in per_block_metrics))
        routing_cost = compute_routing_cost(num_relocations, num_recnots, num_channel_releases)
        num_blocks = len(self.blocks_actual)
        (ibd_mean, ibd_max, ibd_min) = self._compute_inter_block_distance_metric()
        results = {'distribution_of_channels_on_large_block': serialize_dict(self.distribution_of_channels_on_large_block), 'num_external_qubits_on_large_block': self.num_external_qubits_on_large_block, 'num_internal_qubits_on_large_block': self.num_internal_qubits_on_large_block, 'operation_info_on_large_block': self.operation_info_on_large_block, 'distribution_of_channels_on_small_blocks': serialize_dict(self.distribution_of_channels_on_small_blocks), 'num_external_qubits_on_small_blocks': self.num_external_qubits_on_small_blocks, 'num_internal_qubits_on_small_blocks': self.num_internal_qubits_on_small_blocks, 'operation_info_on_small_blocks': self.operation_info_on_small_blocks, 'block_is_split': self.block_is_split, 'blocks_agg_node': self.blocks_agg_node, 'compile_time_circuit_rewriting': self.compile_time_circuit_rewriting, 'compile_time_block_updating': self.compile_time_block_updating, 'compile_time_communication_fusion': self.compile_time_communication_fusion, 'compile_time_for_block_scheduling': self.compile_time_for_block_scheduling, 'compile_time_for_early_execution': self.compile_time_for_early_execution, 'channel_imbalance': self.channel_imbalance, 'block_updated': self.block_updated, 'block_updated_count': len(self.block_updated), 'blocks_anticipated': {k: v for (k, v) in self.blocks_anticipated.items() if k < num_blocks}, 'blocks_actual': self.blocks_actual, 'program_weights_over_time': self.program_weights_over_time, 'per_block_metrics': per_block_metrics, 'num_evictions': num_evictions, 'num_relocations': num_relocations, 'num_recnots': num_recnots, 'num_channel_releases': num_channel_releases, 'routing_cost': routing_cost, 'early_executed_dict': self.early_executed_dict, 'ees_motivation': getattr(self, 'ees_motivation', {}), 'num_blocks': self.num_blocks, 'dag_depth': self.depth, 'avg_xops_per_block': (self.num_state_teleportation_cnot_ops + self.num_gate_teleportations) / self.num_blocks if self.num_blocks > 0 else 0, 'init_min_block_size': min(self.count_dict.keys()), 'init_avg_block_size': sum([k * v for (k, v) in self.count_dict.items()]) / sum(self.count_dict.values()) if sum(self.count_dict.values()) > 0 else 0, 'init_max_block_size': max(self.count_dict.keys()), 'total_gate_count': self.num_gates, 'num_local_cnots': self.num_local_cnots, 'num_gate_teleportations': self.num_gate_teleportations, 'num_state_teleportations': self.num_state_teleportations, 'num_effective_cnots': self.num_effective_cnots, 'total_fidelity_local_2q': self.fidelity_2Q, 'total_fidelity_transfer': getattr(self, 'fidelity_transfer', 1.0), 'total_fidelity_remote_2q': getattr(self, 'fidelity_remote_2Q_total', 1.0), 'total_fidelity_relocation': getattr(self, 'fidelity_relocation_total', 1.0), 'total_fidelity_interconnect': self.fidelity_int, 'total_fidelity_deco': self.fidelity_deco, 'total_fidelity_total': self.fidelity_total, 'latency_penalty': self.latency_penalty, 'fidelity_penalty': self.fidelity_penalty, 'total_cost': self.total_cost, 'fidelity_model': {'fidelity_1Q': float(getattr(self.args, 'fidelity_1Q', 1.0)), 'fidelity_2Q': float(getattr(self.args, 'fidelity_2Q', 1.0)), 'fidelity_transfer': float(getattr(self.args, 'fidelity_transfer', 1.0)), 'fidelity_remote_2Q': float(getattr(self.args, 'fidelity_remote_2Q', 1.0)), 'fidelity_relocation': float(getattr(self.args, 'fidelity_relocation', 1.0)), 'coherence_time': float(getattr(self.args, 'coherence_time', 0.0)), 'num_qubits': int(getattr(self.args, 'num_qubits', 0) or 0)}, 'total_execution_time': self.total_execution_time, 'inter_block_dist_mean': ibd_mean, 'inter_block_dist_max': ibd_max, 'inter_block_dist_min': ibd_min, 'inter_block_dist_basis': 'execution_layer'}
        results['pre_schedule_chip_data_qubit_counts'] = {str(k): int(v) for (k, v) in sorted(getattr(self, 'pre_schedule_chip_data_qubit_counts', {}).items(), key=lambda item: str(item[0]))}
        return results