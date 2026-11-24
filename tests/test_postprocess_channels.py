"""Strict replay rejects directional errors and historical replay records the same timings."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
A, B = (0, 0), (1, 0)


def run_postprocessor(at_once, with_capacity=True):
    ops = []
    for atom, src, dst, start in [(0, A, B, 0), (1, B, A, 0 if at_once else 1)]:
        ops.append(dict(optype='RELOCATE', atom0=atom, atom1=atom, pos0=src, pos1=dst,
                        layer_id=str(atom), original_start_time=start, original_duration=1,
                        original_end_time=start + 1))
    schedule = {'initial_atom_positions': {'0': A, '1': B}, 'ops': ops}
    if with_capacity:
        schedule['initial_directional_channels'] = [(A, B, 1), (B, A, 3)]
    with TemporaryDirectory() as tmp:
        raw = Path(tmp) / 'schedule.json'
        out = Path(tmp) / 'extra.json'
        raw.write_text(json.dumps(schedule))
        cmd = [sys.executable, str(ROOT / 'scripts/apply_extra_opt.py'), '--schedule', str(raw),
               '--arch', 'S5C2-2x1', '--out', str(out)]
        strict = subprocess.run(cmd, capture_output=True, text=True)
        strict_wrote = out.exists()
        historical = subprocess.run(cmd + ['--historical-replay'], capture_output=True, text=True)
        return strict, strict_wrote, historical, json.loads(out.read_text()) if out.exists() else {}


class PostprocessingChannelTest(unittest.TestCase):
    def test_historical_raw_conflict_is_reported_without_altering_timing(self):
        strict, wrote, historical, result = run_postprocessor(at_once=True)
        self.assertNotEqual(strict.returncode, 0)
        self.assertFalse(wrote)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertEqual((result['wall_time_ms_orig'], result['wall_time_ms_extra']), (1000, 1000))
        self.assertTrue(any(v.startswith('emitted:') and 'directional channel' in v
                            for v in result['violations']))

    def test_valid_raw_conflict_first_appears_after_block_parallelization(self):
        strict, wrote, historical, result = run_postprocessor(at_once=False)
        self.assertNotEqual(strict.returncode, 0)
        self.assertFalse(wrote)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertEqual((result['wall_time_ms_orig'], result['wall_time_ms_extra']), (2000, 1000))
        self.assertEqual(len(result['violations']), 1)
        self.assertTrue(result['violations'][0].startswith('postprocessed:'))
        self.assertIn('directional channel', result['violations'][0])

    def test_missing_capacity_is_reported(self):
        strict, wrote, historical, result = run_postprocessor(at_once=False, with_capacity=False)
        self.assertNotEqual(strict.returncode, 0)
        self.assertFalse(wrote)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertTrue(any('initial directional channel' in v for v in result['violations']))


if __name__ == '__main__':
    unittest.main()
