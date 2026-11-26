"""Audit the parser's logical CX projection and the complete native circuit.

Run with the pinned Qiskit 0.46.3 environment:
    python revision/issue2_gate_audit.py > revision/issue2-gate-audit.tsv

Two-wire gates act on global wires 2,0; the three-wire controls use 2,0,1.
The independent reference expands explicit QASM definitions before Qiskit's
level-zero u/cx transpilation so a user-defined name keeps its declared meaning.
No mapping, routing, or physical schedule is evaluated.
"""
import csv
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import qiskit
from qiskit import QuantumCircuit, QuantumRegister, qasm2, transpile
from qiskit.circuit.library import RYGate, UGate, UnitaryGate, get_standard_gate_name_mapping
from qiskit.quantum_info import Operator, random_unitary

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from parser import ProgramParser

HEADER = 'OPENQASM 2.0;\ninclude "qelib1.inc";\n'
REGISTERS = 'qreg a[2]; qreg b[1];\n'
WIRES = ' b[0],a[0];'
TOLERANCE = 1e-10
INCLUDE_STATEMENT = 'include "overrides.inc";'
INCLUDE_BODY = 'gate rzz(t) a,b { ry(t) b; CX b,a; }'
REJECTIONS = {'opaque': ('opaque', 'unknown', '[2, 0]'),
              'raw-cswap': ('3-qubit', 'cswap', '[2, 0, 1]'),
              'raw-ccx': ('3-qubit', 'ccx', '[2, 0, 1]')}


def basis_transpile(circuit):
    return transpile(circuit, basis_gates=['u', 'cx'], optimization_level=0, routing_method='none')


def three_wires():
    return QuantumCircuit(QuantumRegister(2, 'a'), QuantumRegister(1, 'b'))


def exported_gate(gate):
    circuit = three_wires()
    circuit.append(gate, [2, 0])
    values = [0.371, -0.829, 1.213, 0.643]
    circuit = circuit.assign_parameters(dict(zip(circuit.parameters, values)))
    # Qiskit 0.46's unitary exporter probes singular candidates internally.
    with np.errstate(divide='ignore', invalid='ignore'):
        return qasm2.dumps(circuit), circuit


def cases():
    native = {g.name for g in qasm2.LEGACY_CUSTOM_INSTRUCTIONS if g.num_qubits == 2}
    standard = {k: g for k, g in get_standard_gate_name_mapping().items() if g.num_qubits == 2}
    assert len(native) == 15 and native <= standard.keys() and len(standard) == 24
    for name in sorted(standard):
        kind = 'qasm-legacy' if name in native else 'standard-definition'
        text, circuit = exported_gate(standard[name])
        yield kind, name, text, circuit
        if name not in native:
            # Use the same numeric call but remove every exported gate definition.
            yield 'bare-standard', f'bare-{name}', HEADER + text[text.index('qreg '):], circuit
    for name, call in [('CX-primitive', 'CX'), ('cp-zero', 'cp(0)'), ('cp-pi', 'cp(pi)'),
                       ('cp-pi4', 'cp(pi/4)'), ('cp-pi8', 'cp(pi/8)'), ('cp-tiny', 'cp(pi/2^239)'),
                       ('rzz-zero', 'rzz(0)')]:
        yield 'spelling-or-angle', name, HEADER + REGISTERS + call + WIRES, None
    custom = [
        ('nested-asymmetric', 'gate flip a,b { CX b,a; } '
         'gate nest(t) a,b { h b; flip a,b; crz(t) a,b; x a; }', 'nest(-pi/7)'),
        ('shadow-ecr-local', 'gate ecr a,b { x a; }', 'ecr'),
        ('shadow-ecr-reversed', 'gate ecr a,b { cx b,a; }', 'ecr'),
        ('identity', 'gate empty a,b { }', 'empty'),
        ('opaque', 'opaque unknown a,b;', 'unknown'),
    ]
    for name, definition, call in custom:
        yield 'user-definition', name, HEADER + definition + '\n' + REGISTERS + call + WIRES, None
    yield 'matrix-definition', 'haar-u4-seed461', *exported_gate(UnitaryGate(random_unitary(4, seed=461)))
    local = np.kron(UGate(0.31, -0.47, 0.82).to_matrix(), RYGate(0.93).to_matrix())
    yield 'matrix-definition', 'tensor-local', *exported_gate(UnitaryGate(local))
    shadow = three_wires()
    shadow.cx(0, 2)
    shadow.ry(np.pi / 15, 2)
    yield ('declared-override', 'declared-cp', HEADER + 'gate cp(t) a,b { CX b,a; U(t/3,0,0) a; }\n'
           + REGISTERS + 'cp(pi/5)' + WIRES, shadow)
    shadow = three_wires()
    shadow.x(0)
    yield ('declared-override', 'declared-cz-no-qelib', 'OPENQASM 2.0;\ngate cz a,b { U(pi,0,pi) b; }\n'
           + REGISTERS + 'cz' + WIRES, shadow)
    shadow = three_wires()
    shadow.ry(np.pi / 7, 0)
    shadow.cx(0, 2)
    yield ('declared-override', 'included-rzz', HEADER + INCLUDE_STATEMENT + '\n'
           + REGISTERS + 'rzz(pi/7)' + WIRES, shadow)
    for op in ('cswap', 'ccx'):
        yield 'three-wire', f'raw-{op}', HEADER + REGISTERS + op + ' b[0],a[0],a[1];', None
    fredkin = three_wires()
    fredkin.cswap(2, 0, 1)
    yield 'three-wire', 'external-cswap', qasm2.dumps(basis_transpile(fredkin)), fredkin



def source_and_reference(source, kind, original):
    if kind == 'bare-standard':
        # These nine bare aliases extend the legacy QASM loader. Read their
        # meaning from the independently instantiated standard gate.
        name = original.data[0].operation.name
        choices = {
            'named': basis_transpile(original),
            'definition': basis_transpile(original.decompose(gates_to_decompose=[name])),
        }
        # Both are independent, unitary-equivalent level-zero translations.
        # Use fewer CX, then fewer one-qubit instructions, as a fixed tiebreak.
        sizes = {key: (len(inventory(c)[1]), inventory(c)[0]) for key, c in choices.items()}
        assert all(matrix_error(original, c) < TOLERANCE for c in choices.values()), name
        selected = min(sizes, key=sizes.get)
        details = ','.join(f'{key}={cx}/{one}' for key, (cx, one) in sizes.items())
        return original, choices[selected], f'{selected} ({details})'
    text = source.replace(INCLUDE_STATEMENT, INCLUDE_BODY)
    declared = set(re.findall(r'\bgate\s+([a-z][A-Za-z0-9_]*)', text))
    # Legacy loader callbacks can replace declared CP/CZ bodies by name.
    # Use fresh identifiers in both declarations and calls to preserve the
    # literal bodies through the independent parser and transpiler.
    if declared:
        token = r'\b(?:' + '|'.join(map(re.escape, sorted(declared))) + r')\b'
        text = re.sub(token, lambda m: 'audit_' + m.group(0), text)
    circuit = QuantumCircuit.from_qasm_str(text)
    expanded = circuit
    names = ['audit_' + name for name in declared]
    while any(inst.operation.name in names for inst in expanded):
        expanded = expanded.decompose(gates_to_decompose=names)
    return circuit, basis_transpile(expanded), 'declared-body' if declared else 'native'


def matrix_error(original, other):
    a, b = Operator(original).data, Operator(other).data
    overlap = np.vdot(a, b)
    phase = overlap / abs(overlap) if abs(overlap) else 1
    return float(np.max(np.abs(b - phase * a)))


def inventory(circuit):
    edges = []
    one_qubit = 0
    for inst in circuit:
        width = len(inst.qubits)
        if width == 1:
            one_qubit += 1
        elif width == 2 and inst.operation.name == 'cx':
            edges.append(tuple(circuit.find_bit(q).index for q in inst.qubits))
        elif width != 0:
            raise AssertionError(f'Outside the 1q/CX basis: {inst.operation.name}')
    return one_qubit, edges


def directed(edges):
    return ','.join(f'{a}>{b}' for a, b in edges) or '-'


def audit(kind, name, source, original, path):
    path.write_text(source)
    if name in REJECTIONS:
        try:
            ProgramParser(str(path))
        except ValueError as error:
            if not all(part in str(error) for part in (str(path), *REJECTIONS[name])):
                raise AssertionError(f'Incomplete rejection diagnostic: {error}') from error
            return [kind, name, 'rejected', '-', '-', '-', '-', '-', '-', '-', '-']
        raise AssertionError(f'{name} silently accepted')
    parsed = ProgramParser(str(path))
    source_circuit, baseline, ref_method = source_and_reference(source, kind, original)
    actual = parsed.to_native_circuit()
    one_qubit, cx = inventory(actual)
    reference_1q, reference_cx = inventory(baseline)
    errors = [matrix_error(source_circuit, actual), matrix_error(source_circuit, baseline)]
    if original is not None:
        errors.extend([matrix_error(original, source_circuit), matrix_error(original, actual)])
    assert all(np.isfinite(e) and e < TOLERANCE for e in errors), (name, errors)
    assert one_qubit == reference_1q, (name, one_qubit, reference_1q)
    assert cx == parsed() == reference_cx, (name, cx, parsed(), reference_cx)
    assert (one_qubit, len(cx)) == (parsed.num_1q_gates, parsed.num_2q_gates), name
    cp_phase_imag = '-'
    if name == 'external-cswap':
        assert len(cx) == 8 and one_qubit == 9, (one_qubit, cx)
    if source_circuit.data[0].operation.name == 'cp':
        matrix = Operator(actual).data
        # Both addressed wires are set in |101>; |000> removes global phase.
        measured = float((matrix[5, 5] / matrix[0, 0]).imag)
        theta = float(source_circuit.data[0].operation.params[0])
        if name == 'cp-tiny':
            assert np.isclose(measured, np.sin(np.pi / 2**239), atol=0, rtol=1e-12), measured
        cp_phase_imag = format(measured, '.17g')
        assert abs(measured - np.sin(theta)) < TOLERANCE, name
    return [kind, name, 'passed', one_qubit, reference_1q, len(cx), len(reference_cx),
            directed(cx), f'{max(errors):.3e}', cp_phase_imag, ref_method]


if __name__ == '__main__':
    if qiskit.__version__ != '0.46.3':
        raise RuntimeError(f'Expected Qiskit 0.46.3, found {qiskit.__version__}')
    with tempfile.TemporaryDirectory() as work:
        (Path(work) / 'overrides.inc').write_text(INCLUDE_BODY)
        rows = [audit(*case, Path(work) / f'{case[1]}.qasm') for case in cases()]
    writer = csv.writer(sys.stdout, delimiter='\t', lineterminator='\n')
    writer.writerow(['input_family', 'case', 'result', 'parser_1q', 'reference_1q',
                     'parser_cx', 'reference_cx', 'directed_cx_global', 'max_matrix_error', 'cp_phase_ratio_imag',
                     'reference_method_alternatives_cx_1q'])
    writer.writerows(rows)
