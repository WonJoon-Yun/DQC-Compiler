"""Executable scheduling mixin — extracted from _baseline.py."""
from collections import defaultdict
import os
from pathlib import Path
from .._constants import Executable
from utils import atomic_json_dump, convert_ndarray_to_list
_SCHEDULE_RESULTS_SNAPSHOT_KEYS = ('total_gate_count', 'num_local_cnots', 'num_gate_teleportations', 'num_state_teleportations', 'num_effective_cnots', 'total_execution_time', 'total_cost', 'fidelity_model')

def _compact_results_snapshot(results_snapshot):
    if results_snapshot is None:
        return None
    raw = str(os.environ.get('CHIPLET_FULL_SCHEDULE_RESULTS_SNAPSHOT', '') or '').strip().lower()
    if raw in {'1', 'true', 'yes', 'on'}:
        return convert_ndarray_to_list(results_snapshot)
    if not isinstance(results_snapshot, dict):
        return convert_ndarray_to_list(results_snapshot)
    compact = {key: results_snapshot[key] for key in _SCHEDULE_RESULTS_SNAPSHOT_KEYS if key in results_snapshot}
    return convert_ndarray_to_list(compact)

class ExecutableMixin:
    """Methods for building and running the executable schedule."""

    def get_executable(self):
        return self._build_executable_schedule()

    def _reset_schedule_replay_records(self):
        self.schedule_replay_records = []
        self._schedule_replay_index = {}
        self.schedule_replay_policy = {}

    def _register_schedule_replay_executable(self, exe, schedule_layer_idx, time_bucket_idx):
        if not hasattr(self, 'schedule_replay_records'):
            self._reset_schedule_replay_records()
        record = {'unique_id': exe.unique_id, 'schedule_layer_idx': int(schedule_layer_idx), 'time_bucket_idx': int(time_bucket_idx), 'layer_id': str(exe.layer_idx), 'atom0': exe.atom0, 'atom1': exe.atom1, 'pos0': convert_ndarray_to_list(exe.pos0), 'pos1': convert_ndarray_to_list(exe.pos1), 'optype': exe.operation, 'dependency_ids': [dep.unique_id for dep in exe.dependency], 'is_moveback': bool('after_relocation' in exe.unique_id or '_is_moveback' in exe.unique_id), 'original_duration': float(exe.duration), 'original_start_time': None, 'original_end_time': None}
        self.schedule_replay_records.append(record)
        self._schedule_replay_index[exe.unique_id] = record

    def _record_schedule_replay_timing(self, exe):
        record = getattr(self, '_schedule_replay_index', {}).get(exe.unique_id)
        if record is None:
            return
        record['original_start_time'] = float(exe.start_time)
        record['original_end_time'] = float(exe.end_time)

    def save_schedule_replay(self, output_dir, args_snapshot=None, results_snapshot=None):
        if output_dir is None:
            raise ValueError('output_dir is required for save_schedule_replay()')
        records = getattr(self, 'schedule_replay_records', None)
        if not records:
            return None
        k_suffix = f'{self.args.K1}-{self.args.K2}'
        output_path = Path(output_dir) / f'Schedule-{k_suffix}.json'
        payload = {'format_version': 1, 'k_suffix': k_suffix, 'scheduler_policy': convert_ndarray_to_list(getattr(self, 'schedule_replay_policy', {})), 'args_snapshot': convert_ndarray_to_list(args_snapshot) if args_snapshot is not None else None, 'results_snapshot': _compact_results_snapshot(results_snapshot), 'ops': convert_ndarray_to_list(records)}
        atomic_json_dump(payload, output_path, indent=1)
        return str(output_path)

    def _build_executable_schedule(self):
        """Build and run a latency-friendly scheduler:"""
        MERGE_LAYERS = getattr(self.args, 'schedule_merge_layers', False)
        BARRIER_BY_TIME = getattr(self.args, 'schedule_barrier_by_time', True)
        SERIALIZE_WITHIN_BUCKET = getattr(self.args, 'schedule_serialize_within_bucket', False)
        CAP_CHANNELS = getattr(self.args, 'schedule_cap_channels', False)
        MAX_CHANNEL_PER_EDGE = getattr(self.args, 'max_parallel_per_link', None) or getattr(self.args, 'num_communication_qubits', 1)
        self._reset_schedule_replay_records()
        self.schedule_replay_policy = {'scheduler_variant': 'K3_1', 'schedule_merge_layers': bool(MERGE_LAYERS), 'schedule_barrier_by_time': bool(BARRIER_BY_TIME), 'schedule_serialize_within_bucket': bool(SERIALIZE_WITHIN_BUCKET), 'schedule_cap_channels': bool(CAP_CHANNELS), 'max_parallel_per_link': None if MAX_CHANNEL_PER_EDGE is None else int(MAX_CHANNEL_PER_EDGE)}

        def _parse_time_idx(uid: str) -> int:
            try:
                return int(uid.split('_', 1)[0])
            except Exception:
                return 10 ** 9

        def _op_priority(op: str) -> int:
            if op in ('Local CNOT', 'Re-CNOT'):
                return 1
            if op in ('RELOCATE', 'Transfer', 'MOVE'):
                return 2
            return 3

        def _edge_key(op: str, pos0, pos1):
            """Return an undirected edge key for channel-limited ops."""
            if op in ('RELOCATE', 'Transfer', 'Re-CNOT'):
                return tuple(sorted((tuple(pos0), tuple(pos1))))
            return None
        self.layer_idx = 0
        ir_groups = self.IRLayers
        if MERGE_LAYERS:
            merged = []
            for grp in self.IRLayers:
                merged.extend(grp)
            ir_groups = [merged]
        for (schedule_layer_idx, ir_layers) in enumerate(ir_groups):
            all_ops_layers = []
            for ir_layer in ir_layers:
                gates = self.interpretIRTable(ir_layer)
                if not hasattr(self, 'len_ir'):
                    self.len_ir = 0
                self.len_ir += len(gates)
                all_ops_layers.append(self.xop2localop(gates))
            qubit_dict = defaultdict(list)
            for irl in all_ops_layers:
                for gate in irl:
                    qubit_dict[gate[4][0]].append(gate)
                    qubit_dict[gate[4][1]].append(gate)
            groups_by_time = defaultdict(list)
            seen_ids = set()
            for irl in all_ops_layers:
                for gate in irl:
                    uid = gate[5]
                    t = _parse_time_idx(uid)
                    groups_by_time[t].append(gate)
                    if uid in seen_ids:
                        print(f'[WARN] duplicated unique_id detected: {uid}')
                    seen_ids.add(uid)
            executables = []
            last_by_atom = {}
            last_time_bucket_ops = []
            for time_idx in sorted(groups_by_time.keys()):
                gates_list = groups_by_time[time_idx]
                sorted_gates = sorted(gates_list, key=lambda x: (x[0], -_op_priority(x[2])))
                prev_in_bucket = None
                barrier_deps = list(last_time_bucket_ops) if BARRIER_BY_TIME else []
                current_bucket_ops = []
                for gate in sorted_gates:
                    uid = gate[5]
                    (atom0, atom1) = gate[4]
                    (pos0, pos1) = gate[1]
                    op = gate[2]
                    dur = max(float(gate[3]), 1e-12)
                    deps = []
                    if SERIALIZE_WITHIN_BUCKET and prev_in_bucket is not None:
                        deps.append(prev_in_bucket)
                    if atom0 in last_by_atom:
                        deps.append(last_by_atom[atom0])
                    if atom1 in last_by_atom:
                        deps.append(last_by_atom[atom1])
                    deps.extend(barrier_deps)
                    try:
                        layer_id_for_exe = uid.split('_')[1]
                    except Exception:
                        layer_id_for_exe = '0'
                    exe = Executable(uid, layer_id_for_exe, atom0, atom1, pos0, pos1, op, deps, dur, False)
                    executables.append(exe)
                    current_bucket_ops.append(exe)
                    self._register_schedule_replay_executable(exe, schedule_layer_idx, time_idx)
                    prev_in_bucket = exe
                    last_by_atom[atom0] = exe
                    last_by_atom[atom1] = exe
                last_time_bucket_ops = current_bucket_ops
            not_started = list(executables)
            running = []
            done = []
            current_time = self.total_execution_time
            channel_use = defaultdict(int)
            while len(done) < len(executables):
                ready = [exe for exe in list(not_started) if all((dep.is_done for dep in exe.dependency))]
                ready.sort(key=lambda e: (_op_priority(e.operation), -e.duration), reverse=True)
                started_any = False
                for exe in list(ready):
                    if CAP_CHANNELS:
                        key = _edge_key(exe.operation, exe.pos0, exe.pos1)
                        if key is not None and channel_use[key] >= MAX_CHANNEL_PER_EDGE:
                            continue
                    exe.start_time = current_time
                    exe.remaining_time = exe.duration
                    running.append(exe)
                    not_started.remove(exe)
                    started_any = True
                    if CAP_CHANNELS:
                        key = _edge_key(exe.operation, exe.pos0, exe.pos1)
                        if key is not None:
                            channel_use[key] += 1
                if not running and len(done) < len(executables):
                    if not_started and (not started_any):
                        raise RuntimeError('Scheduler deadlock: no runnable tasks and unfinished dependencies.')
                if running:
                    next_finish_time = min((exe.start_time + exe.remaining_time for exe in running))
                    current_time = next_finish_time
                    finishing = [exe for exe in running if abs(exe.start_time + exe.remaining_time - current_time) < 1e-12]
                    for exe in finishing:
                        exe.is_done = True
                        exe.end_time = current_time
                        running.remove(exe)
                        done.append(exe)
                        self._record_schedule_replay_timing(exe)
                        if CAP_CHANNELS:
                            key = _edge_key(exe.operation, exe.pos0, exe.pos1)
                            if key is not None:
                                channel_use[key] -= 1
                        fidelity = self._build_tracer_fidelity_metadata(exe.operation, exe.end_time)
                        self.tracer.append(layer_idx=self.layer_idx, atom0=exe.atom0, atom1=exe.atom1, pos0=exe.pos0, pos1=exe.pos1, optype=exe.operation, start_time=exe.start_time, end_time=exe.end_time, is_moveback='after_relocation' in exe.unique_id or '_is_moveback' in exe.unique_id, fidelity=fidelity)
                        if exe.operation == 'Transfer':
                            self.num_transfers += 1
                        elif exe.operation == 'Local CNOT':
                            self.num_CNOTs += 1
                        elif exe.operation == 'Re-CNOT':
                            self.num_interconnect_CNOTs += 1
                        elif exe.operation == 'RELOCATE':
                            self.num_interconnect_SWAPs += 1
            if not hasattr(self, 'n_cnot_debug'):
                self.n_cnot_debug = 0
            self.n_cnot_debug += sum((1 for exe in executables if exe.operation in ('Local CNOT', 'Re-CNOT')))
            self.total_execution_time = current_time
            self.layer_idx += 1