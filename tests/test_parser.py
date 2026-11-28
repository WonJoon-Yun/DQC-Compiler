"""Regression tests for OpenQASM operands and mapped interaction layers."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from qiskit import QuantumCircuit, qasm2
from qiskit.circuit.library import ECRGate, get_standard_gate_name_mapping
from qiskit.quantum_info import Operator

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
from parser import ProgramParser

HEADER = 'OPENQASM 2.0;\ninclude "qelib1.inc";\n'
SPLIT_GHZ = '''qreg a[2]; qreg b[2]; creg c[4];
h a[0]; cx a[0],a[1]; cx a[1],b[0]; cx b[0],b[1];
measure a[0] -> c[0]; measure a[1] -> c[1];
measure b[0] -> c[2]; measure b[1] -> c[3];'''
FLAT_GHZ = '''qreg q[4]; creg c[4];
h q[0]; cx q[0],q[1]; cx q[1],q[2]; cx q[2],q[3]; measure q -> c;'''
GHZ_LAYERS = [[[0, 1]], [[1, 2]], [[2, 3]]]
ALIASED_LAYERS = [[[0, 1]], [[1, 0]], [[0, 1]]]


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.qasm = self.root / 'ghz.qasm'
        self.output = self.root / 'out'
        self.output.mkdir()

    def parse(self, body):
        self.qasm.write_text(HEADER + body)
        return ProgramParser(str(self.qasm))

    def test_ghz_register_layout(self):
        for circuit in (FLAT_GHZ, SPLIT_GHZ):
            with self.subTest(circuit=circuit):
                parsed = self.parse(circuit)
                self.assertEqual(parsed(), [(0, 1), (1, 2), (2, 3)])
                self.assertEqual((parsed.num_qubits, parsed.num_2q_gates), (4, 3))

    def test_register_offsets_include_unused_qubits(self):
        parsed = self.parse('qreg a[3]; qreg b[2]; cx b[0],a[0]; cx a[0],b[1];')
        self.assertEqual(parsed(), [(3, 0), (0, 4)])

    def test_unsupported_operations_identify_the_file_name_and_global_operands(self):
        for op, operands in [('ccx', 'a[0],a[1],b[0]'),
                             ('cswap', 'a[0],a[1],b[0]')]:
            with self.subTest(op=op):
                with self.assertRaises(ValueError) as ctx:
                    self.parse(f'qreg a[2]; qreg b[1]; {op} {operands};')
                error = str(ctx.exception)
                self.assertIn(str(self.qasm), error)
                self.assertIn(op, error)
                self.assertIn('[0, 1, 2]', error)

    def test_declared_gate_from_an_include(self):
        (self.root / 'custom.inc').write_text('gate twist a,b { h b; cx b,a; h b; }')
        parsed = self.parse('include "custom.inc"; qreg a[2]; qreg b[2]; twist a[0],b[1];')
        self.assertEqual(parsed(), [(3, 0)])
        self.assertEqual(parsed.num_1q_gates, 2)
        self.assertEqual(list(parsed.to_native_circuit().count_ops().items()), [('h', 2), ('cx', 1)])

    def test_nested_included_gate_parameters_and_source_diagnostics(self):
        inner = self.root / 'inner.inc'
        outer = self.root / 'outer.inc'
        outer.write_text("// include 'nonexistent.inc';\ninclude // comment\n 'inner.inc';")
        call = 'qreg q[2]; twist(pi/3) q[1],q[0];'
        for newline in ('', '\n'):
            with self.subTest(newline=newline):
                body = 'gate twist(t) a,b { ry(t) b; CX b,a; }' + newline
                inner.write_text(body)
                reference = QuantumCircuit.from_qasm_str(HEADER + body + '\n' + call)
                for include in ('inner.inc', 'outer.inc'):
                    parsed = self.parse(f'include "{include}"; ' + call)
                    self.assertEqual(parsed(), [(0, 1)])
                    np.testing.assert_allclose(Operator(parsed.to_native_circuit()).data, Operator(reference).data,
                                               rtol=1e-14, atol=1e-14)
        inner.write_text('gate twist(t) a,b {\n  ry(t) b;\n  bogus b;\n}')
        with self.assertRaisesRegex(qasm2.QASM2ParseError, r"inner\.inc:3,2:.*bogus"):
            self.parse('include "outer.inc"; ' + call)

    def test_cycles_and_invalid_includes_report_the_origin(self):
        lib = self.root / 'loop.inc'
        lib.write_text('include "loop.inc";')
        with self.assertRaisesRegex(qasm2.QASM2ParseError, r'loop\.inc:1: recursive include'):
            self.parse('include "loop.inc";')
        lib.write_text('x q[0];')
        with self.assertRaisesRegex(qasm2.QASM2ParseError, r'ghz\.qasm:3: include must be a top-level statement'):
            self.parse('qreg q[1]; creg c[1]; if(c==1) include "loop.inc";')
        lib.write_text('include "missing.inc";')
        with self.assertRaisesRegex(qasm2.QASM2ParseError, r"loop\.inc:1: cannot find include 'missing.inc'"):
            self.parse('include "loop.inc";')

    def test_reported_cz_between_two_cx_gates(self):
        body = ('qreg q[4]; creg c[4]; h q[0]; cx q[0],q[1]; h q[2]; '
                'cz q[1],q[2]; h q[2]; cx q[2],q[3]; measure q -> c;')
        for op, hadamards in [('cz', 5), ('cx', 3)]:
            with self.subTest(middle=op):
                parsed = self.parse(body.replace('cz q[1]', f'{op} q[1]'))
                self.assertEqual(parsed(), [(0, 1), (1, 2), (2, 3)])
                self.assertEqual(parsed.num_2q_gates, 3)
                self.assertEqual(dict(parsed.to_native_circuit().count_ops()),
                                 {'h': hadamards, 'cx': 3, 'measure': 4})

    def test_native_counts_and_directives(self):
        for op, expected, one_q in [('cx', [(0, 1)], 0), ('rzz(pi/8)', [(0, 1)] * 2, 1),
                                   ('cp(pi/8)', [(0, 1)] * 2, 3), ('cz', [(0, 1)], 2),
                                   ('swap', [(0, 1), (1, 0), (0, 1)], 0)]:
            with self.subTest(op=op):
                parsed = self.parse(f'qreg q[2]; creg c[2]; h q[0]; barrier q; {op} q[0],q[1]; '
                                    'barrier q[0]; reset q[1]; measure q -> c;')
                self.assertEqual(parsed(), expected)
                self.assertEqual((parsed.num_1q_gates, parsed.num_2q_gates), (5 + one_q, len(expected)))
                native = parsed.to_native_circuit()
                self.assertEqual([x.operation.name for x in native.data[:2]], ['h', 'barrier'])
                self.assertEqual([x.operation.name for x in native.data[-4:]], ['barrier', 'reset', 'measure', 'measure'])
                self.assertEqual([native.find_bit(x.clbits[0]).index for x in native.data[-2:]], [0, 1])

    def test_direct_two_qubit_library_names(self):
        for name, template in get_standard_gate_name_mapping().items():
            if template.num_qubits != 2:
                continue
            with self.subTest(name=name):
                params = [0.41 + i / 7 for i in range(len(template.params))]
                arguments = '(' + ','.join(map(str, params)) + ')' if params else ''
                parsed = self.parse(f'qreg q[2]; {name}{arguments} q[1],q[0];')
                reference = QuantumCircuit(2)
                reference.append(template.base_class(*params), [1, 0])
                np.testing.assert_allclose(Operator(parsed.to_native_circuit()).data, Operator(reference).data,
                                           rtol=1e-13, atol=1e-13)
                if name == 'ecr':
                    self.assertEqual(len(parsed()), 1)

    def test_gate_declarations_take_precedence_over_legacy_constructors(self):
        for source in ('OPENQASM 2.0; gate cz a,b { U(pi,0,pi) a; } qreg q[2]; cz q[1],q[0];',
                       HEADER + 'gate cp(t) a,b { x a; } qreg q[2]; cp(0.2) q[1],q[0];'):
            with self.subTest(source=source):
                self.qasm.write_text(source)
                parsed = ProgramParser(str(self.qasm))
                self.assertEqual((parsed(), parsed.num_1q_gates), ([], 1))
                reference = QuantumCircuit(2)
                reference.x(1)
                np.testing.assert_allclose(Operator(parsed.to_native_circuit()).data, Operator(reference).data, atol=1e-14)
        (self.root / 'defs.inc').write_text('gate cp(t) a,b { x b; }')
        parsed = self.parse('include "defs.inc"; qreg q[2]; ecr q[0],q[1]; cp(0.2) q[0],q[1];')
        reference = QuantumCircuit(2)
        reference.append(ECRGate(), [0, 1])
        reference.x(1)
        self.assertEqual(parsed.num_2q_gates, 1)
        np.testing.assert_allclose(Operator(parsed.to_native_circuit()).data, Operator(reference).data, atol=1e-14)

    def test_duplicate_and_forward_declarations_fail(self):
        (self.root / 'later.inc').write_text('gate ecr a,b { x a; }')
        for body in ('gate ecr a,b { x a; } gate ecr a,b { x b; }',
                     'qreg q[2]; ecr q[0],q[1]; include "later.inc";'):
            with self.subTest(body=body):
                with self.assertRaises(qasm2.QASM2ParseError):
                    self.parse(body)

    def test_tiny_controlled_phase_survives_lowering(self):
        theta = 2.0 ** -239
        for name in ('cp', 'cu1'):
            with self.subTest(name=name):
                parsed = self.parse(f'qreg q[2]; {name}({theta!r}) q[1],q[0];')
                self.assertEqual(parsed(), [(1, 0), (1, 0)])
                matrix = Operator(parsed.to_native_circuit()).data
                self.assertAlmostEqual(matrix[3, 3].imag / theta, 1.0, places=13)
                np.testing.assert_allclose(matrix, np.diag([1, 1, 1, np.exp(1j*theta)]), atol=0, rtol=1e-14)

    def test_same_name_different_source_definitions(self):
        for body, edges, singles in [('x a; x b;', [], 2), ('cx b,a;', [(1, 0)], 0), ('', [], 0)]:
            with self.subTest(body=body):
                parsed = self.parse(f'gate ecr a,b {{ {body} }} qreg q[2]; ecr q[0],q[1];')
                self.assertTrue(parsed.has_source_operations)
                self.assertEqual((parsed(), parsed.num_1q_gates), (edges, singles))
                expected = QuantumCircuit.from_qasm_file(str(self.qasm))
                np.testing.assert_allclose(Operator(parsed.to_native_circuit()).data, Operator(expected).data, atol=1e-14)

    def test_opaque_and_classically_controlled_two_qubit_inputs(self):
        for code, detail in [('opaque mystery a,b; mystery q[0],q[1];', 'mystery'),
                             ('opaque mystery a; gate pair a,b { mystery a; cx a,b; } pair q[0],q[1];', 'mystery'),
                             ('creg c[1]; if(c==1) cp(pi/8) q[0],q[1];', 'condition')]:
            with self.subTest(code=code):
                with self.assertRaises(ValueError) as ctx:
                    self.parse('qreg q[2]; ' + code)
                self.assertIn(detail, str(ctx.exception).lower())
                self.assertIn('[0, 1]', str(ctx.exception))
                self.assertIn(str(self.qasm), str(ctx.exception))

    def test_run_rejects_cswap_even_with_a_valid_mapping_cache(self):
        self.seed_cache({i: i for i in range(4)}, GHZ_LAYERS)
        run = self.run_compiler(FLAT_GHZ.replace('cx q[1],q[2]', 'cswap q[0],q[1],q[2]'))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('cswap', run.stderr)
        self.assertFalse((self.output / 'results.json').exists())

    def seed_cache(self, mapping, layers):
        metadata = dict(cost=123, use_oee_refine=True, oee_max_passes=5, oee_tol=0.,
                        preprocessing_time=0., k_partitioning_time=0.,
                        chip_selection_time=0., remap_time=0.)
        for name, data in [('mapping', mapping), ('layers', layers), ('compile_time', metadata)]:
            (self.output / f'{name}.json').write_text(json.dumps(data))

    def run_compiler(self, body):
        self.qasm.write_text(HEADER + body)
        return subprocess.run(
            [sys.executable, str(SRC / 'run.py'), '--circuit', str(self.qasm),
             '--name', 'ghz', '--results_dir', str(self.output), '--flat_output',
             '--mapping_method', 'trivial', '--routing_method', 'IRIS4',
             '--numchipletsx', '2', '--numchipletsy', '1', '--system_qubits_per_chip', '4',
             '--num_communication_per_link', '2', '--K1', '1', '--K2', '6', '--gate_cnt', '0'],
            cwd=self.root, capture_output=True, text=True, timeout=60,
        )

    def test_rebuilds_aliased_cache_even_when_all_keys_exist(self):
        self.seed_cache({i: i for i in range(4)}, ALIASED_LAYERS)
        run = self.run_compiler(SPLIT_GHZ)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads((self.output / 'layers.json').read_text()), GHZ_LAYERS)
        nested = self.output / 'ghz' / 'trivial' / 'S4C2-2x1'
        self.assertEqual(json.loads((nested / 'layers.json').read_text()), GHZ_LAYERS)
        self.assertNotEqual(json.loads((self.output / 'results.json').read_text())['mapping_cost'], 123)
        repaired = {p: p.stat().st_mtime_ns for p in self.output.glob('*.json')
                    if p.stem in {'mapping', 'layers', 'compile_time'}}
        self.assertEqual(self.run_compiler(SPLIT_GHZ).returncode, 0)
        self.assertEqual({p: p.stat().st_mtime_ns for p in repaired}, repaired)

    def test_rebuilds_an_incomplete_flat_cache(self):
        self.seed_cache({0: 0, 1: 1}, ALIASED_LAYERS)
        (self.output / 'compile_time.json').unlink()
        run = self.run_compiler(SPLIT_GHZ)
        self.assertEqual(run.returncode, 0, run.stderr)
        nested = self.output / 'ghz' / 'trivial' / 'S4C2-2x1'
        for name in ('mapping', 'layers', 'compile_time'):
            self.assertEqual((self.output / f'{name}.json').read_bytes(),
                             (nested / f'{name}.json').read_bytes())
        self.assertEqual(json.loads((self.output / 'layers.json').read_text()), GHZ_LAYERS)

    def test_reuses_valid_multiregister_and_single_register_stub_caches(self):
        independent = 'qreg a[2]; qreg b[2]; cx a[0],a[1]; cx b[0],b[1]; cx a[1],b[0];'
        cases = [(SPLIT_GHZ, GHZ_LAYERS), ('qreg q[4];', GHZ_LAYERS),
                 (independent, [[[2, 3], [0, 1]], [[1, 2]]])]
        for circuit, layers in cases:
            with self.subTest(circuit=circuit):
                self.seed_cache({i: i for i in range(4)}, layers)
                run = self.run_compiler(circuit)
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads((self.output / 'results.json').read_text())
                self.assertEqual((result['total_gate_count'], result['mapping_cost']), (3, 123))


if __name__ == '__main__':
    unittest.main()
