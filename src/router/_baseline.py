import copy
from collections import defaultdict, deque
from tracer import Tracer
from utils import logger
from ._dag import build_connectivity_graph
from ._metrics import MetricsMixin
from .block_formation import CommunicationFusionMixin
from .preprocessing import GatePreprocessMixin, PositionMixin
from .scheduling import ExecutableMixin, LookaheadMixin

class BaselineRouter(PositionMixin, GatePreprocessMixin, CommunicationFusionMixin, LookaheadMixin, ExecutableMixin, MetricsMixin):

    def __init__(self, args, qubit_mapping, atom_idx_to_physical_pos):
        logger.info('Initializing BaselineRouter')
        self.args = args
        self.qubit_mapping = qubit_mapping
        self.atom_idx_to_physical_pos = atom_idx_to_physical_pos
        self._is_new_hw_model = getattr(self.args, 'system_qubits_per_chip', None) is not None and getattr(self.args, 'num_communication_per_link', None) is not None
        self.num_ancillae_per_chip = defaultdict(int)
        for sx in range(self.args.numchipletsx):
            for sy in range(self.args.numchipletsy):
                if self._is_new_hw_model:
                    n = 0
                    if sx > 0:
                        n += 1
                    if sx < self.args.numchipletsx - 1:
                        n += 1
                    if sy > 0:
                        n += 1
                    if sy < self.args.numchipletsy - 1:
                        n += 1
                    self.num_ancillae_per_chip[sx, sy] = int(self.args.num_communication_per_link) * n
                else:
                    self.num_ancillae_per_chip[sx, sy] = int(self.args.num_communication_qubits)
        self.atom_type = {}
        if atom_idx_to_physical_pos is not None:
            for (atom_idx, atom_pos) in self.atom_idx_to_physical_pos.items():
                if self._is_new_hw_model or len(atom_pos) < 5:
                    self.atom_type[atom_idx] = 'FLAT'
                else:
                    self.atom_type[atom_idx] = 'AOD' if atom_pos[-1] == 1 else 'SLM'
        else:
            self.atom_type = None
        if atom_idx_to_physical_pos is not None:
            self.position_table = {k: tuple(self.atom_idx_to_physical_pos[k][:2]) for k in self.atom_idx_to_physical_pos.keys()}
        else:
            self.position_table = None
        self.connectivity = build_connectivity_graph(self.args.numchipletsx, self.args.numchipletsy)
        self.tracer = Tracer(self.args)
        self.gate_order = deque()
        self.block_updated = []
        self.blocks_anticipated = {}
        self.blocks_actual = {}
        self.blocks_agg_node = {}
        self.qucomm_block_lookahead_debug = {}
        self.program_weights_over_time = []
        self.BeforeOperationPath = []
        self.AfterOperationPath = []
        self.channel_imbalance = []
        self.per_block_metrics = []
        self.per_block_metric_records = []
        self.num_returns = 0
        self.early_executed_dict = {}
        self.ees_motivation = {}
        self.num_onchip_op_gates = 0
        self.num_state_teleportation_cnot_ops = 0
        self.num_crosschip_op_gates = 0
        self.num_CNOTs = 0
        self.travel_distance = 0
        self.num_transfers = 0
        self.num_interconnect_SWAPs = 0
        self.num_interconnect_CNOTs = 0
        self.num_blocks = 0
        self.num_gate_teleportations = 0
        self.ccop_to_localop = set()
        self.num_gates = 0
        self.num_cops = 0
        self.num_ops_per_comm_block = []
        self.x_ops_per_block = []
        self.IRLayers = []
        self.remote_cnot_info = {}
        self.manhattan_distance = []
        self.count = 0

    def _reset_block_metric_tracking(self):
        self.blocks_actual = {}
        self.blocks_agg_node = {}
        self.qucomm_block_lookahead_debug = {}
        self.x_ops_per_block = []
        self.per_block_metrics = []
        self.per_block_metric_records = []

    def _record_plan_block_metric(self, block_id, per_block_metric):
        metric_copy = copy.deepcopy(per_block_metric)
        self.per_block_metrics.append(metric_copy)
        self.per_block_metric_records.append({'block_id': block_id, 'agg_node': self.blocks_agg_node.get(block_id), 'relocates': metric_copy.relocates, 'recnots': metric_copy.recnots, 'releases': metric_copy.releases, 'evictions': metric_copy.releases})
        self.blocks_actual[block_id] = metric_copy.relocates + metric_copy.recnots * 2 + metric_copy.releases
        self.x_ops_per_block.append((metric_copy.recnots, metric_copy.relocates, metric_copy.releases))

    def _record_qucomm_lookahead_debug(self, plan):
        if not getattr(self.args, 'save_qucomm_block_lookahead_debug', False):
            return
        for record in getattr(plan, 'lookahead_debug', []) or []:
            bid = record.get('block_id')
            if bid is None:
                continue
            self.qucomm_block_lookahead_debug[int(bid)] = copy.deepcopy(record)

    def reset_metrics(self, layers):
        self.num_transfers = 0
        self.num_interconnect_SWAPs = 0
        self.num_CNOTs = 0
        self.num_interconnect_CNOTs = 0
        self.total_execution_time = 0
        self.num_cops = 0
        self.fidelity_total = 1
        self.fidelity_2Q = 1
        self.fidelity_transfer = 1
        self.fidelity_int = 1
        self.fidelity_remote_2Q_total = 1
        self.fidelity_relocation_total = 1
        self.fidelity_deco = 1
        self.latency_penalty = 0
        self.fidelity_penalty = 0
        self.total_cost = 0
        self.num_gates = len([gate for layer in layers for gate in layer])
        Layers = []
        for layer in layers:
            layer_temp = []
            for gate in layer:
                layer_temp.append((gate[0], gate[1]))
            Layers.append(layer_temp)
        self.layers = Layers