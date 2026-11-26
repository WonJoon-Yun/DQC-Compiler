"""Regression tests for OpenQASM operands and mapped interaction layers."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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
