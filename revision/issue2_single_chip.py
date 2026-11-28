"""Compare the gate audit with actual IRIS4 CLI schedules on one three-qubit chip."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import qiskit

from issue2_gate_audit import INCLUDE_BODY, REJECTIONS, cases, directed
from parser import ProgramParser


HERE = Path(__file__).resolve().parent
SENTINEL = 'CX b[0],a[0];'
FIELDS = ('input_family', 'case', 'reference_cx', 'parser_cx',
          'scheduled_local_cnots', 'num_local_cnots', 'num_gate_teleportations',
          'num_state_teleportations', 'sentinel_plus_gate_local_cnots', 'incremental_local_cnots',
          'standalone_outcome')


def compile_case(root, name, source, expected_error=()):
    run = root / name
    run.mkdir()
    qasm = run / 'input.qasm'
    qasm.write_text(source)
    (run / 'overrides.inc').write_text(INCLUDE_BODY)
    cmd = [sys.executable, str(HERE.parent / 'src' / 'run.py'),
           '--circuit', str(qasm), '--name', name, '--results_dir', str(run), '--flat_output',
           '--mapping_method', 'trivial', '--routing_method', 'IRIS4',
           '--numchipletsx', '1', '--numchipletsy', '1', '--system_qubits_per_chip', '3',
           '--num_communication_per_link', '1', '--K1', '1', '--K2', '6', '--gate_cnt', '0',
           '--save_run_log']
    proc = subprocess.run(cmd, cwd=run, capture_output=True, text=True, timeout=60)
    if proc.returncode or expected_error:
        log = run / 'log-1-6.txt'
        message = proc.stderr + (log.read_text() if log.exists() else '')
        if (expected_error and proc.returncode and all(part in message for part in expected_error)
                and not (run / 'results.json').exists() and not (run / 'schedule.json').exists()):
            return
        raise RuntimeError(f'{name}: unexpected CLI outcome {proc.returncode}\n{message[-1500:]}')
    return (json.loads((run / 'results.json').read_text()),
            json.loads((run / 'schedule.json').read_text())['ops'])


def measure(root, name, source, reference_stream):
    result, operations = compile_case(root, name, source)
    assert (result['numchipletsx'], result['numchipletsy'], result['system_qubits_per_chip']) == (1, 1, 3), name
    parsed = ProgramParser(str(root / name / 'input.qasm'))()
    observed = []
    for op in operations:
        if (op['optype'] != 'Local CNOT' or op['pos0'] != [0, 0] or op['pos1'] != [0, 0]
                or op['original_end_time'] is None):
            raise AssertionError((name, op))
        observed.append((op['atom0'], op['atom1']))
    assert observed == list(parsed) and directed(observed) == reference_stream, (name, observed)
    assert len(observed) == result['num_local_cnots'] == result['total_gate_count'], name
    assert result['num_gate_teleportations'] == result['num_state_teleportations'] == 0, name
    return (len(parsed), len(observed), result['num_local_cnots'],
            result['num_gate_teleportations'], result['num_state_teleportations'])


def audit(root):
    with (HERE / 'issue2-gate-audit.tsv').open() as file:
        references = {row['case']: row for row in csv.DictReader(file, delimiter='\t')}
    inputs = list(cases())
    assert {name for _, name, _, _ in inputs} == set(references)
    # Use the primitive CX fixture as the measured control for all incremental checks.
    inputs.sort(key=lambda case: case[1] != 'CX-primitive')
    rows = []
    for kind, name, source, _ in inputs:
        reference = references[name]
        if name in REJECTIONS:
            compile_case(root, name, source, REJECTIONS[name])
            rows.append((kind, name, '', '', '', '', '', '', '', '', 'parser_rejected'))
            continue
        expected = int(reference['reference_cx'])
        if expected:
            values = measure(root, name, source, reference['directed_cx_global'])
            assert values[0] == expected, name
            if name == 'CX-primitive':
                control = values[2]
                assert control == 1
            rows.append((kind, name, expected, *values, '', '', 'measured'))
            continue
        compile_case(root, name, source, ('[FATAL] Program length is 0',))
        parsed = ProgramParser(str(root / name / 'input.qasm'))()
        assert parsed == [], name
        values = measure(root, name + '-with-cx', source + '\n' + SENTINEL + '\n', '2>0')
        delta = values[2] - control
        assert delta == 0, name
        rows.append((kind, name, expected, len(parsed), '', '', '', '',
                     values[2], delta, 'mapper_rejected_empty'))
    return rows


if __name__ == '__main__':
    if not __debug__ or qiskit.__version__ != '0.46.3':
        raise RuntimeError('Run with Qiskit 0.46.3 and Python assertions enabled')
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--runs', type=Path, help='Keep each CLI invocation in a new directory')
    args = cli.parse_args()
    if args.runs:
        root = args.runs.resolve()
        root.mkdir(parents=True, exist_ok=False)
        rows = audit(root)
    else:
        with tempfile.TemporaryDirectory() as work:
            rows = audit(Path(work))
    writer = csv.writer(sys.stdout, delimiter='\t', lineterminator='\n')
    writer.writerow(FIELDS)
    writer.writerows(rows)
