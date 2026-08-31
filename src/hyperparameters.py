from dataclasses import dataclass, fields, is_dataclass
from typing import Optional
from epr_latency import AtomSystem, get_total_epr_generation_seconds
def safe_asdict(obj):
    if is_dataclass(obj):
        result = {}
        for f in fields(obj):
            value = getattr(obj, f.name)
            result[f.name] = safe_asdict(value)
        return result
    elif isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            try:
                key_str = str(k)
            except Exception:
                key_str = repr(k)
            new_dict[key_str] = safe_asdict(v)
        return new_dict
    elif isinstance(obj, (list, tuple)):
        return type(obj)(safe_asdict(v) for v in obj)
    else:
        return obj
@dataclass
class HyperParameters:
    use_all_qubits: Optional[int] = 0
    flat_output: Optional[bool] = False
    save_run_log: Optional[bool] = False
    max_1d: Optional[int] = 10
    K1: Optional[int] = 0
    K2: Optional[int] = 0
    qucomm_candidate_eval_mode: Optional[str] = "active_chip_nodes"
    qucomm_enable_teleport_hybrid: Optional[bool] = False
    qucomm_disable_future_touch: Optional[bool] = True
    qucomm_route_algo: Optional[str] = "our_qucomm"
    qucomm_enable_gate_lookahead: Optional[bool] = False
    qucomm_gate_lookahead_depth: Optional[int] = 0
    qucomm_gate_lookahead_beam_width: Optional[int] = 16
    qucomm_gate_lookahead_option: Optional[str] = "opt1"
    qucomm_gate_lookahead_sort_mode: Optional[str] = "current_then_total"
    qucomm_gate_lookahead_prune_mode: Optional[str] = "selection_sort"
    qucomm_future_block_decay_mode: Optional[str] = "linear"
    qucomm_future_window_mode: Optional[str] = "future_partner_ranked"
    qucomm_enable_gate_foresight: Optional[bool] = False
    use_oee_refine: Optional[bool] = True
    oee_max_passes: Optional[int] = 5
    routing_output_dir: Optional[str] = ''
    oee_tol: Optional[float] = 0.0
    gate_cnt: Optional[int] = 0
    alpha: Optional[float] = 10
    beta: Optional[float] = 1
    compile_time_mapper: Optional[float] = None
    compile_time_router: Optional[float] = None
    compile_time_total: Optional[float] = None
    enable_ees: Optional[bool] = False
    atom_system: AtomSystem = "Rb"
    time_transfer: float = get_total_epr_generation_seconds("Rb")
    time_2Q: float = 360e-9
    time_int_2Q: float =  2.324e-3
    time_int_SWAP: float = 1.324e-3
    time_move: float = 300e-6
    fidelity_transfer: float = 0.999
    fidelity_2Q: float = 0.995
    fidelity_1Q: float = 0.9992
    fidelity_remote_2Q: float = 0.980
    fidelity_relocation: float = 0.985
    coherence_time: float = 1.5
    mapping_cost: float = 0.
    mapping_manhattan_distance: Optional[dict] = None
    numchipletsx: Optional[int] = None
    numchipletsy: Optional[int] = None
    numx: Optional[int] = None
    numy: Optional[int] = None
    num_qubits: Optional[int] = None
    circuit: Optional[str] = None
    name: Optional[str] = None
    mapping_method: Optional[str] = None
    routing_method: Optional[str] = None
    num_communication_qubits: Optional[int] = None
    system_qubits_per_chip: Optional[int] = None
    num_communication_per_link: Optional[int] = None
    per_chip_compute_capacity: Optional[dict] = None
    results_dir: Optional[str] = 'results'
    seed: Optional[int] = 42
    qucomm_one_meet_tiebreak_mode: Optional[int] = None
    save_qucomm_block_lookahead_debug: Optional[bool] = False
    @property
    def is_new_model(self) -> bool:
        return (
            self.system_qubits_per_chip is not None
            and self.num_communication_per_link is not None)
    def _neighbor_count(self, cx: int, cy: int) -> int:
        count = 0
        if cx > 0:
            count += 1
        if cx < self.numchipletsx - 1:
            count += 1
        if cy > 0:
            count += 1
        if cy < self.numchipletsy - 1:
            count += 1
        return count
    def update(self, args):
        for k, v in vars(args).items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.time_transfer = get_total_epr_generation_seconds(self.atom_system)
        if self.is_new_model:
            cap = {}
            for cx in range(self.numchipletsx):
                for cy in range(self.numchipletsy):
                    n = self._neighbor_count(cx, cy)
                    cap[(cx, cy)] = self.system_qubits_per_chip - self.num_communication_per_link * n
            self.per_chip_compute_capacity = cap
            self.num_qubits = sum(cap.values())
        else:
            self.num_qubits = self.numchipletsx * self.numchipletsy * self.numx * self.numy
    def to_dict(self):
        return safe_asdict(self)
args = HyperParameters()