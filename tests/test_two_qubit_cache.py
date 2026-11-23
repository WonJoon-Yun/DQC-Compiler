"""Parser-to-mapping-cache tests. No mapper or router execution is required."""
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
from mapping_cache import can_reuse_cached_layers
from parser import ProgramParser


class TwoQubitCacheTests(unittest.TestCase):
    def parse(self, body):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / 'input.qasm'
            source.write_text('OPENQASM 2.0;\ninclude "qelib1.inc";\n' + body)
            return ProgramParser(str(source))

    def test_rejects_old_single_register_cp_cache(self):
        parser = self.parse('qreg q[2]; cp(pi/4) q[0],q[1];')
        mapping = {'0': 4, '1': 0}
        self.assertEqual(len(parser()), 2)
        self.assertFalse(can_reuse_cached_layers(mapping, [[[4, 0]]], parser))
        self.assertTrue(can_reuse_cached_layers(mapping, [[[4, 0]], [[4, 0]]], parser))

    def test_rejects_reversed_direction_on_a_single_register(self):
        parser = self.parse('qreg q[2]; cx q[1],q[0];')
        self.assertFalse(can_reuse_cached_layers({'0': 0, '1': 1}, [[[0, 1]]], parser))

    def test_independent_gates_can_reorder_but_shared_wire_order_must_match(self):
        parser = self.parse('qreg q[4]; cx q[0],q[1]; cx q[2],q[3]; cx q[1],q[2];')
        mapping = {str(i): i for i in range(4)}
        allowed = [[[2, 3], [0, 1]], [[1, 2]]]
        reordered_on_wire_1 = [[[2, 3]], [[1, 2]], [[0, 1]]]
        self.assertTrue(can_reuse_cached_layers(mapping, allowed, parser))
        self.assertFalse(can_reuse_cached_layers(mapping, reordered_on_wire_1, parser))

    def test_real_zero_cx_sources_cannot_inherit_cached_interactions(self):
        one_cx = [[[0, 1]]]
        mapping = {'0': 0, '1': 1}
        for body in ('qreg q[2]; h q[0];',
                     'gate separate a,b { x a; h b; } qreg q[2]; separate q[0],q[1];',
                     'gate noop a,b { x a; x a; } qreg q[2]; noop q[0],q[1];'):
            with self.subTest(body=body):
                parser = self.parse(body)
                self.assertEqual(parser(), [])
                self.assertFalse(can_reuse_cached_layers(mapping, one_cx, parser))
                self.assertTrue(can_reuse_cached_layers(mapping, [], parser))

    def test_declaration_only_single_register_stub_keeps_its_cached_layers(self):
        mapping = {'0': 0, '1': 1}
        one_cx = [[[0, 1]]]
        self.assertTrue(can_reuse_cached_layers(mapping, one_cx, self.parse('qreg q[2];')))
        self.assertFalse(can_reuse_cached_layers(mapping, one_cx, self.parse('qreg a[1]; qreg b[1];')))


if __name__ == '__main__':
    unittest.main()
