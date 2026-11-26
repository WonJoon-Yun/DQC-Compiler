"""Check strict schedule selection and the timing-preserving historical replay."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
A, B = (0, 0), (1, 0)


def schedule_pair(at_once=False, with_capacity=True, opening=1):
    ops = []
    for atom, src, dst, start in [(0, A, B, 0), (1, B, A, 0 if at_once else 1)]:
        ops.append(dict(optype='RELOCATE', atom0=atom, atom1=atom, pos0=src, pos1=dst,
                        layer_id=str(atom), original_start_time=start, original_duration=1,
                        original_end_time=start + 1))
    schedule = {'initial_atom_positions': {'0': A, '1': B}, 'ops': ops}
    if with_capacity:
        schedule['initial_directional_channels'] = [(A, B, opening), (B, A, 3)]
    return schedule


def run_postprocessor(schedule):
    with TemporaryDirectory() as tmp:
        raw = Path(tmp) / 'schedule.json'
        out = Path(tmp) / 'extra.json'
        raw.write_text(json.dumps(schedule))
        cmd = [sys.executable, str(ROOT / 'scripts/apply_extra_opt.py'), '--schedule', str(raw),
               '--arch', 'S5C2-2x1', '--out', str(out)]
        strict = subprocess.run(cmd, capture_output=True, text=True)
        strict_result = json.loads(out.read_text()) if out.exists() else None
        historical = subprocess.run(cmd + ['--historical-replay'], capture_output=True, text=True)
        return strict, strict_result, historical, json.loads(out.read_text()) if out.exists() else {}


class PostprocessingChannelTest(unittest.TestCase):
    def test_historical_raw_conflict_is_reported_without_altering_timing(self):
        strict, wrote, historical, result = run_postprocessor(schedule_pair(at_once=True))
        self.assertNotEqual(strict.returncode, 0)
        self.assertFalse(wrote)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertEqual((result['wall_time_ms_orig'], result['wall_time_ms_extra']), (1000, 1000))
        self.assertTrue(any(v.startswith('emitted:') and 'directional channel' in v
                            for v in result['violations']))

    def test_valid_raw_conflict_first_appears_after_block_parallelization(self):
        strict, chosen, historical, result = run_postprocessor(schedule_pair())
        self.assertEqual(strict.returncode, 0, strict.stderr)
        self.assertEqual(chosen['selection'], 'original_cycles')
        self.assertIn('directional channel', chosen['candidate_rejection'])
        self.assertEqual(chosen['violations'], [])
        self.assertEqual((chosen['cycles_orig'], chosen['cycles_extra_opt']), (2, 2))
        self.assertEqual((chosen['wall_time_ms_orig'], chosen['wall_time_ms_extra']), (2000, 2000))
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertEqual((result['wall_time_ms_orig'], result['wall_time_ms_extra']), (2000, 1000))
        self.assertEqual(len(result['violations']), 1)
        self.assertTrue(result['violations'][0].startswith('postprocessed:'))
        self.assertIn('directional channel', result['violations'][0])

    def test_legal_compaction_uses_parallelized_candidate(self):
        strict, chosen, _, _ = run_postprocessor(schedule_pair(opening=3))
        self.assertEqual(strict.returncode, 0, strict.stderr)
        self.assertEqual(chosen['selection'], 'parallelized')
        self.assertIsNone(chosen['candidate_rejection'])
        self.assertEqual((chosen['cycles_orig'], chosen['cycles_extra_opt']), (2, 1))
        self.assertEqual(chosen['wall_time_ms_extra'], 1000)

    def test_fallback_rechecks_the_original_cycles_link_cap(self):
        schedule = schedule_pair()
        c, d = (0, 1), (1, 1)
        schedule['initial_directional_channels'].extend([(c, d, 5), (d, c, 5)])
        for atom in (2, 3, 4):
            schedule['initial_atom_positions'][str(atom)] = c
            schedule['ops'].append(dict(optype='RELOCATE', atom0=atom, atom1=atom, pos0=c, pos1=d,
                                        layer_id=str(atom), original_start_time=0,
                                        original_duration=1, original_end_time=1))
        strict, chosen, _, _ = run_postprocessor(schedule)
        self.assertNotEqual(strict.returncode, 0)
        self.assertIsNone(chosen)
        self.assertIn('original_cycles', strict.stderr)
        self.assertIn('link-cap', strict.stderr)

    def test_reordered_gates_on_one_atom_fail_validation(self):
        # The earlier-starting block has a later gate on atom 0 than the competing block.
        ops = [dict(optype='Local CNOT', atom0=q, atom1=r, pos0=A, pos1=A, layer_id=str(block),
                    original_start_time=t, original_end_time=t + 1, original_duration=1)
               for q, r, block, t in [(3, 4, 0, 0), (0, 1, 1, 1), (0, 2, 0, 2)]]
        schedule = {'ops': ops, 'initial_atom_positions': {str(q): A for q in range(5)}}
        strict, chosen, historical, result = run_postprocessor(schedule)
        self.assertNotEqual(strict.returncode, 0)
        self.assertIsNone(chosen)
        self.assertIn('atom 0 order', strict.stderr)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertTrue(any('atom 0 order' in v for v in result['violations']))

    def test_missing_capacity_is_reported(self):
        strict, wrote, historical, result = run_postprocessor(schedule_pair(with_capacity=False))
        self.assertNotEqual(strict.returncode, 0)
        self.assertFalse(wrote)
        self.assertEqual(historical.returncode, 0, historical.stderr)
        self.assertTrue(any('initial directional channel' in v for v in result['violations']))


if __name__ == '__main__':
    unittest.main()
