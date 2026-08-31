"""Some additional info:"""
import argparse
import json
import os
import random
import sys
import tracemalloc
import traceback
from parser import ProgramParser
import numpy as np
from hardware import Hardware
from hyperparameters import HyperParameters
from utils import atomic_json_dump, convert_ndarray_to_list
random.seed(42)
np.random.seed(42)
VALID_MAPPING_METHODS = {'ILP', 'BruteForce', 'Evolutionary', 'MQC', 'OEE', 'GCP', 'GCP-E', 'GCP-S', 'WBCP', 'OEE-ILP', 'GCP-ILP', 'WBCP-noILP', 'naive', 'trivial'}
MAPPING_METHOD_ALIASES = {'ilp': 'ILP', 'bruteforce': 'BruteForce', 'evolutionary': 'Evolutionary', 'mqc': 'MQC', 'oee': 'OEE', 'gcp': 'GCP', 'gcp-s': 'GCP-S', 'gcps': 'GCP-S', 'gcp-e': 'GCP-E', 'gcpe': 'GCP-E', 'naive': 'naive', 'trivial': 'trivial', 'identity': 'trivial', 'wbcp': 'WBCP', 'oee-ilp': 'OEE-ILP', 'oee_ilp': 'OEE-ILP', 'oeeilp': 'OEE-ILP', 'gcp-ilp': 'GCP-ILP', 'gcp_ilp': 'GCP-ILP', 'gcpilp': 'GCP-ILP', 'wbcp-noilp': 'WBCP-noILP', 'wbcp_noilp': 'WBCP-noILP', 'wbcpnoilp': 'WBCP-noILP'}

def parse_mapping_method_spec(mapping_method):
    if mapping_method is None:
        return ('ILP', None)
    raw = mapping_method.strip()
    lowered = raw.lower()
    use_oee_override = None
    for (suffix, use_oee) in (('_no_oee', False), ('_nooee', False), ('_oee', True)):
        if lowered.endswith(suffix):
            lowered = lowered[:-len(suffix)]
            use_oee_override = use_oee
            break
    normalized = MAPPING_METHOD_ALIASES.get(lowered, raw)
    if normalized == 'naive' and use_oee_override is True:
        return ('OEE', True)
    if normalized not in VALID_MAPPING_METHODS:
        valid_methods = ', '.join(sorted(VALID_MAPPING_METHODS))
        raise ValueError(f"Unsupported mapping_method '{mapping_method}'. Use one of: {valid_methods}")
    return (normalized, use_oee_override)

def _is_new_model(args):
    return getattr(args, 'system_qubits_per_chip', None) is not None and getattr(args, 'num_communication_per_link', None) is not None

def _arch_dir_fragment(args):
    if _is_new_model(args):
        return f'S{args.system_qubits_per_chip}C{args.num_communication_per_link}-{args.numchipletsx}x{args.numchipletsy}'
    return f'{args.numx}x{args.numy}-{args.numchipletsx}x{args.numchipletsy}'

def get_mapping_cache_dir(args):
    if getattr(args, 'flat_output', False):
        return f'{args.results_dir}'
    return f'{args.results_dir}/{args.name}/{args.mapping_method}/{_arch_dir_fragment(args)}'

def get_routing_output_dir(args):
    if getattr(args, 'flat_output', False):
        return f'{args.results_dir}'
    if _is_new_model(args):
        return f'{args.results_dir}/{args.name}/{args.mapping_method}/{args.routing_method}/{_arch_dir_fragment(args)}'
    return f'{args.results_dir}/{args.name}/{args.mapping_method}/{args.routing_method}/{args.numx}x{args.numy}-{args.numchipletsx}x{args.numchipletsy}-{args.num_communication_qubits}'

def mapping_cache_matches_config(cache_data, args):
    if bool(cache_data.get('use_oee_refine')) != bool(args.use_oee_refine):
        return False
    if int(cache_data.get('oee_max_passes', -1)) != int(args.oee_max_passes):
        return False
    cached_tol = cache_data.get('oee_tol')
    if cached_tol is None:
        return False
    return abs(float(cached_tol) - float(args.oee_tol)) < 1e-12

def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on'}

def _env_int(name, default):
    raw = str(os.environ.get(name, '') or '').strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)

def _results_log_summary(results):
    summary = {}
    for key in ('total_gate_count', 'num_local_cnots', 'num_gate_teleportations', 'num_state_teleportations', 'num_effective_cnots', 'total_execution_time', 'total_cost', 'compile_time_total'):
        if key in results:
            summary[key] = results[key]
    fidelity_model = results.get('fidelity_model')
    if fidelity_model is not None:
        summary['fidelity_model'] = fidelity_model
    return summary

def _emit_results_log(results_json_path, results_payload):
    print('===============results================')
    print(f'file path: {results_json_path}')
    force_full = _env_flag('IRIS_LOG_FULL_RESULTS', default=False)
    inline_limit_bytes = max(0, _env_int('IRIS_INLINE_RESULTS_LOG_MAX_BYTES', 1000000))
    file_size = os.path.getsize(results_json_path) if os.path.exists(results_json_path) else None
    if force_full or (file_size is not None and file_size <= inline_limit_bytes):
        print(f'results: {results_payload}')
        return
    print(f'results_summary: {_results_log_summary(results_payload)}')
    if file_size is not None:
        print(f'results_inline_payload: skipped (payload_size_bytes={file_size}, limit={inline_limit_bytes}; set IRIS_LOG_FULL_RESULTS=1 to restore)')
    else:
        print('results_inline_payload: skipped')
parser = argparse.ArgumentParser()
parser.add_argument('--max_1d', type=int, help='Max 1D dimension of the chiplet grid')
parser.add_argument('--K1', type=int, help='Horizon size (Block-Routing Lookahead)')
parser.add_argument('--K2', type=int, help='Horizon size (RestorePath Lookahead)')
parser.add_argument('--atom_system', type=str, default='Rb', choices=['Rb', 'Yb'], help='Atom system species for paper-consistent EPR-generation latency model.')
parser.add_argument('--qucomm_candidate_eval_mode', type=str, default='active_chip_nodes', choices=['all_nodes', 'active_chip_nodes'], help="Candidate-node evaluation mode for our_qucomm: 'all_nodes' (full search) or 'active_chip_nodes' (chips currently hosting block qubits only)")
parser.add_argument('--qucomm_one_meet_tiebreak_mode', type=str, default='legacy_direct', choices=['original', 'legacy_direct'], help="Tie-break mode for our_qucomm one-meet selection: 'original' (legacy our_qucomm ordering) or 'legacy_direct' (default; only applies legacy-compatible ordering when direct A/B-style endpoint candidates are tied on legacy cost)")
parser.add_argument('--qucomm_enable_teleport_hybrid', action='store_true', help='Enable hybrid mode: evaluate both ONE-MEET and teleport options (A/B/D/E including displacement) each round, picking whichever has lower unified cost (hops-to-colocate + legacy lookahead).')
parser.add_argument('--qucomm_disable_future_touch', dest='qucomm_disable_future_touch', action='store_true', default=True, help='QuComm baseline cost variant (DEFAULT ON; matches the reference QuComm implementation): zero the convergence lookahead when every remaining future gate is already chip-local.')
parser.add_argument('--qucomm_enable_future_touch', dest='qucomm_disable_future_touch', action='store_false', help='Opt out of the QuComm future-touch short-circuit (used by the IRIS variants to preserve the original foresight cost function).')
parser.add_argument('--qucomm_enable_gate_lookahead', action='store_true', help='Enable gate-level QuComm lookahead. A beam-search planner evaluates future gate execution states and can override per-gate one-meet targets for the current block.')
parser.add_argument('--qucomm_gate_lookahead_depth', type=int, default=0, help='Number of future blocks to include in QuComm gate-level rollout lookahead. The planner evaluates the remaining gates of the current block plus all gates in the next N future blocks; 0 disables the feature.')
parser.add_argument('--qucomm_gate_lookahead_beam_width', type=int, default=16, help='Beam width used by QuComm gate-level rollout planning. Larger values retain more candidate gate-action trajectories.')
parser.add_argument('--qucomm_gate_lookahead_option', choices=('opt1',), default='opt1', help='Planning mode used by QuComm gate lookahead and foresight (opt1 only).')
parser.add_argument('--qucomm_gate_lookahead_sort_mode', choices=('current_then_total',), default='current_then_total', help='Beam ordering mode for QuComm gate lookahead / foresight (current_then_total only).')
parser.add_argument('--qucomm_gate_lookahead_prune_mode', choices=('selection_sort',), default='selection_sort', help='Beam pruning mode for QuComm gate lookahead / ForeSight (selection_sort only).')
parser.add_argument('--qucomm_future_block_decay_mode', choices=('linear',), default='linear', help='Future-block discounting used inside QuComm gate-lookahead and ForeSight tree evaluation (linear only).')
parser.add_argument('--qucomm_future_window_mode', choices=('serial', 'next_layer', 'next_layer_active_first', 'future_partner', 'future_partner_ranked', 'serial_plus_future_partner'), default='future_partner_ranked', help="Future-block window selection mode for QuComm / ForeSight. 'future_partner_ranked' (default) is IRIS's utility-driven window; 'serial' is the naive next-K instruction-order window; 'future_partner' keeps qubit-sharing future blocks without ranking. Used by the contribution-breakdown ablation (scripts/fig_13.sh).")
parser.add_argument('--qucomm_enable_gate_foresight', action='store_true', help='Enable ForeSight-style gate-lookahead expansion and pruning. When on, each surviving beam branch generates its own next-step candidates and pruning keeps mapping diversity before truncation.')
parser.add_argument('--numx', type=int, help='X-Dimension of AOD/SLM grids')
parser.add_argument('--numy', type=int, help='Y-Dimension of AOD/SLM grids')
parser.add_argument('--numchipletsx', type=int, help='X-Dimension of chiplet grid')
parser.add_argument('--numchipletsy', type=int, help='Y-Dimension of chiplet grid')
parser.add_argument('--num_communication_qubits', type=int, help='Number of communication qubits')
parser.add_argument('--system_qubits_per_chip', type=int, default=None, help='Total system qubits per chip (new flat-pool model)')
parser.add_argument('--num_communication_per_link', type=int, default=None, help='Communication qubits per inter-chip link (new flat-pool model)')
parser.add_argument('--circuit', type=str, help='Filepath to .qasm file you wish to run')
parser.add_argument('--mapping_method', type=str, default='ILP', help='Mapping method (ILP, BruteForce, Evolutionary, MQC, OEE, WBCP, naive, trivial, plus *_OEE/*_NOOEE aliases)')
parser.add_argument('--routing_method', type=str, default='baseline', help='Routing method (baseline, proposed)')
parser.add_argument('--name', type=str, help='What to name the circuit in outputs')
parser.add_argument('--gate_cnt', type=int, help='Gate count to load from cls')
parser.add_argument('--results_dir', type=str, default='results', help='Base directory for storing results')
parser.add_argument('--save_run_log', default=False, action='store_true', help='Also write the full run log (log-<K1>-<K2>.txt) into the run directory. Disabled by default: the logs usually dominate disk usage.')
parser.add_argument('--flat_output', default=False, action='store_true', help='Read the mapping cache from and write all outputs directly into --results_dir (IRIS-dataset run-dir layout) instead of nested <name>/<mapper>/<routing>/<arch> subdirs')
parser.add_argument('--save_cls', type=bool, default=False, help='Save cls')
parser.add_argument('--save_pipeline_json', default=False, action='store_true', help='Save intermediate no-opt/opt pipeline JSON dumps under results')
parser.add_argument('--wbcp_window_length', type=int, default=None, help='WBCP window length (gates per window). None = auto (max(50, T//10))')
parser.add_argument('--disable_oee_refine', default=False, action='store_true', help='Disable OEE refinement after METIS partitioning')
parser.add_argument('--oee_max_passes', type=int, default=5, help='Maximum OEE refinement passes')
parser.add_argument('--oee_tol', type=float, default=0.0, help='Minimum cumulative OEE gain required to accept a pass')
parser.add_argument('--enable_ees', default=False, action='store_true', help='Enable Early Execution Engine (EES) pipeline optimization')
parser.add_argument('--capture_branch_alternatives', type=str, default=None, help='Path to dump JSON of QuComm beam-search branch-alternative replays. When set, instruments schedule_blocks to record, at every block boundary, every discarded beam candidate and replay each one as a full counterfactual continuation. Adds runtime overhead proportional to (n_blocks * (beam_width-1) * suffix_length). Off by default.')
execution_args = parser.parse_args()
(execution_args.mapping_method, use_oee_override) = parse_mapping_method_spec(execution_args.mapping_method)
execution_args.use_oee_refine = not execution_args.disable_oee_refine
if use_oee_override is not None:
    execution_args.use_oee_refine = use_oee_override
program_parser = ProgramParser(execution_args.circuit)
hardware = Hardware(execution_args)
args = HyperParameters()
args.update(execution_args)
args.num_qubits = program_parser.num_qubits
routing_output_dir = get_routing_output_dir(args)
args.routing_output_dir = routing_output_dir
mapping_cache_dir = get_mapping_cache_dir(args)
log_path = f'{routing_output_dir}/log-{args.K1}-{args.K2}.txt'
args.log_path = log_path
os.makedirs(os.path.dirname(log_path), exist_ok=True)
if getattr(args, 'save_run_log', False):
    sys.stdout = open(log_path, 'w')
else:
    sys.stdout = open(os.devnull, 'w')
sys.stderr = sys.stdout
os.makedirs(mapping_cache_dir, exist_ok=True)
os.makedirs(routing_output_dir, exist_ok=True)
_routing_peak_traced_bytes = None
from mapper import Mapper
if os.path.exists(f'{mapping_cache_dir}/mapping.json') and os.path.exists(f'{mapping_cache_dir}/layers.json') and os.path.exists(f'{mapping_cache_dir}/compile_time.json'):
    with open(f'{mapping_cache_dir}/compile_time.json', 'r') as f:
        data = json.load(f)
    if mapping_cache_matches_config(data, args):
        with open(f'{mapping_cache_dir}/mapping.json', 'r') as f:
            qubit_mapping = json.load(f)
        with open(f'{mapping_cache_dir}/layers.json', 'r') as f:
            layers = json.load(f)
        args.compile_time_mapper = data['preprocessing_time'] + data['k_partitioning_time'] + data['chip_selection_time'] + data['remap_time']
        args.mapping_cost = data['cost']
    else:
        print('[INFO] Mapping cache exists but OEE config differs. Recompiling mapping.')
        mapper = Mapper(args, hardware, program_parser())
        (qubit_mapping, layers) = mapper.compile()
        args.mapping_cost = mapper.cost
else:
    mapper = Mapper(args, hardware, program_parser())
    (qubit_mapping, layers) = mapper.compile()
    args.mapping_cost = mapper.cost
from router import IRISRouter
router = IRISRouter(args, qubit_mapping, hardware.qubit_idx_to_physical_idx)
router.num_1q_gates = program_parser.num_1q_gates
tracemalloc.start()
try:
    results = router.schedule(layers)
except Exception as e:
    print(f'Error: {e}')
    traceback.print_exc()
    with open('error.txt', 'a') as f:
        f.write(f'{args.circuit} {args.routing_method} {e}\n')
    raise Exception(f'Error in router.schedule {args.circuit}') from None
finally:
    (_current_traced, _peak_traced) = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    _routing_peak_traced_bytes = int(_peak_traced)
if _routing_peak_traced_bytes is not None:
    results['routing_peak_traced_bytes'] = int(_routing_peak_traced_bytes)
    results['routing_peak_traced_kb'] = int(_routing_peak_traced_bytes / 1024)
for (k, v) in results.items():
    print(f'{k}: {v}')
results.update(args.to_dict())
k_suffix = f'{args.K1}-{args.K2}'
results_serializable = convert_ndarray_to_list(results)
try:
    from analysis.resource_utilization import apply_utilization_outputs
    utilization_artifacts = apply_utilization_outputs(router.tracer, results_serializable, routing_output_dir, k_suffix)
    print(f"Network utilization saved to: {utilization_artifacts['saved_paths']['network_csv']}")
    print(f"Compute utilization saved to: {utilization_artifacts['saved_paths']['compute_csv']}")
    print(f"Utilization summary saved to: {utilization_artifacts['saved_paths']['summary_md']}")
except Exception as _util_err:
    print(f'[warn] utilization outputs failed: {_util_err}')
try:
    from router.optim.ees_motivation_analysis import analyze_ees_opportunity_from_tracer
    from tracer._core import TRACER_COLUMNS
    ees_tracer = analyze_ees_opportunity_from_tracer(router.tracer.tracer, TRACER_COLUMNS)
    ees_tracer_summary = {k: v for (k, v) in ees_tracer.items() if k != 'details'}
    results_serializable['ees_motivation'] = ees_tracer_summary
    print(f"[EES_MOTIVATION] from tracer: early_ready={ees_tracer_summary['early_ready_pct']:.1f}% idle={ees_tracer_summary['idle_pct']:.1f}% ({ees_tracer_summary['early_ready_count']}/{ees_tracer_summary['total_relocates']} RELOCATEs)")
except Exception as _ees_err:
    print(f'[EES_MOTIVATION] tracer analysis failed: {_ees_err}')
results_json_path = f'{routing_output_dir}/results-{args.K1}-{args.K2}-{args.gate_cnt}.json'
atomic_json_dump(results_serializable, results_json_path, indent=1)
try:
    _emit_results_log(results_json_path, results_serializable)
except Exception as _err:
    print(f'[warn] _emit_results_log failed: {_err}')
print(f'Results saved to: {results_json_path}')
try:
    router.tracer.save(output_dir=routing_output_dir)
    print(f'Tracer saved to: {routing_output_dir}/Tracer-{k_suffix}.csv')
except Exception as _err:
    print(f'[warn] tracer.save failed: {_err}')
try:
    schedule_replay_path = router.save_schedule_replay(output_dir=routing_output_dir, args_snapshot=args.to_dict(), results_snapshot=results_serializable)
    if schedule_replay_path:
        print(f'Schedule replay saved to: {schedule_replay_path}')
except Exception as _err:
    print(f'[warn] save_schedule_replay failed: {_err}')
if getattr(args, 'flat_output', False):
    import glob as _glob
    for (_pat, _dst) in (('results-*.json', 'results.json'), ('Schedule-*.json', 'schedule.json'), ('Tracer-*.csv', 'tracer.csv'), ('Tracer-*.json', 'tracer.json'), ('ResourceCapacityEpochs-*.json', 'resource_capacity_epochs.json'), ('UtilizationSummary-*.md', 'utilization_summary.md'), ('NetworkUtilization-*.csv', 'network_utilization.csv'), ('NetworkUtilization-*.json', 'network_utilization.json'), ('ComputeUtilization-*.csv', 'compute_utilization.csv'), ('ComputeUtilization-*.json', 'compute_utilization.json'), ('log-*.txt', 'run.log')):
        for _src in _glob.glob(f'{routing_output_dir}/{_pat}'):
            os.replace(_src, f'{routing_output_dir}/{_dst}')
    _parts = os.path.normpath(routing_output_dir).split(os.sep)
    _run_name, _sched_dir, _mapping_dir = (_parts[-1], _parts[-2], _parts[-3]) if len(_parts) >= 3 else (os.path.basename(routing_output_dir), '', '')
    _arch_dir = f"S{args.system_qubits_per_chip}C{args.num_communication_per_link}-{args.numchipletsx}x{args.numchipletsy}"
    _presets = {'S40C5-2x2': 'F120', 'S42C5-2x3': 'F180', 'S40C5-3x3': 'F240', 'S180C18-2x2': 'F500', 'S180C18-2x3': 'F800', 'S180C18-3x3': 'F1100'}
    _stage_by_sched = {'QuComm': 'QuComm', 'IRIS-noEES': 'IRIS-opt0', 'IRIS': 'IRIS-opt0-EEE'}
    _meta = {
        'mapping': _mapping_dir,
        'mapping_code': args.mapping_method,
        'scheduling': _sched_dir,
        'stage_label': _stage_by_sched.get(_sched_dir, _sched_dir),
        'variant': '',
        'bench': args.name,
        'family': str(args.name).rsplit('_n', 1)[0],
        'n_qubits': args.num_qubits,
        'arch_dir': _arch_dir,
        'arch_label': f"{_presets.get(_arch_dir, _arch_dir)} (flat-pool {args.numchipletsx}x{args.numchipletsy} S{args.system_qubits_per_chip}C{args.num_communication_per_link})",
        'beam_width': args.qucomm_gate_lookahead_beam_width,
        'lookahead_depth': args.qucomm_gate_lookahead_depth,
        'source': {'experiment': 'artifact-rerun', 'result_path': f'{_mapping_dir}/{_sched_dir}/{_run_name}'},
        'files': {'results.json': 'results.json', 'schedule.json': 'schedule.json', 'tracer.csv': 'tracer.csv', 'mapping.json': 'mapping.json', 'layers.json': 'layers.json', 'compile_time.json': 'compile_time.json'},
    }
    with open(f'{routing_output_dir}/meta.json', 'w') as _mf:
        json.dump(_meta, _mf, indent=1)