import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def op(kind, atoms, chips, start, block):
    return dict(optype=kind, atom0=atoms[0], atom1=atoms[1], pos0=chips[0],
                pos1=chips[1], layer_id=str(block), original_start_time=start,
                original_duration=0.5, original_end_time=start + 0.5)


class LocationReplayTest(unittest.TestCase):
    def verify(self, ops, *, compressed=False, variant="IRIS", initial=None, variants=None):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "MinCut" / variant / "fixture_n3-S3C1-2x1"
            directory.mkdir(parents=True)
            schedule = {"ops": ops, "args_snapshot": dict(
                system_qubits_per_chip=3, num_communication_per_link=1,
                numchipletsx=2, numchipletsy=1)}
            if initial is not None:
                schedule["initial_atom_positions"] = initial
            raw = json.dumps(schedule).encode()
            if compressed:
                (directory / "schedule.json.gz").write_bytes(gzip.compress(raw))
            else:
                (directory / "schedule.json").write_bytes(raw)
            args = [sys.executable, str(ROOT / "tests/verify_extra_opt.py"), "--root", tmp]
            for target in variants if variants is not None else [variant]:
                args.extend(["--variant", target])
            return subprocess.run(args, capture_output=True, text=True)

    def test_missing_relocation_at_block_boundary(self):
        left, right = (0, 0), (1, 0)
        run = self.verify([op("Local CNOT", (0, 1), (left, left), 0, 0),
                           op("Local CNOT", (0, 2), (right, right), 1, 1)])
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("atom 0", run.stdout)
        self.assertIn("block 1", run.stdout)

    def test_first_use_matches_archived_flat_pool(self):
        right = (1, 0)
        run = self.verify([op("Local CNOT", (0, 2), (right, right), 0, 0)],
                          compressed=True, variant="QuComm")
        self.assertEqual(run.returncode, 1)
        self.assertIn("atom 0", run.stdout)

    def test_explicit_relocation_and_remote_gate(self):
        left, right = (0, 0), (1, 0)
        run = self.verify([op("Re-CNOT", (1, 2), (left, right), 0, 0),
                           op("RELOCATE", (0, 0), (left, right), 1, 0),
                           op("Local CNOT", (0, 2), (right, right), 2, 1)])
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_use_while_relocation_is_in_flight(self):
        left, right = (0, 0), (1, 0)
        run = self.verify([op("RELOCATE", (0, 0), (left, right), 0, 0),
                           op("Local CNOT", (0, 2), (right, right), 0.25, 1)])
        self.assertEqual(run.returncode, 1)
        self.assertIn("atom 0", run.stdout)

    def test_historical_replay_preserves_published_timing_and_records_error(self):
        left, right = (0, 0), (1, 0)
        data = {"initial_atom_positions": {"0": left, "1": left, "2": right}, "ops": [
            op("Local CNOT", (0, 1), (left, left), 0, 0),
            op("Local CNOT", (0, 2), (right, right), 1, 1),
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            schedule = Path(tmp) / "schedule.json"
            out = Path(tmp) / "extra_opt.json"
            schedule.write_text(json.dumps(data))
            args = [sys.executable, str(ROOT / "scripts/apply_extra_opt.py"),
                    "--schedule", str(schedule), "--arch", "S3C1-2x1", "--out", str(out)]
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
            self.assertFalse(out.exists())
            replay = subprocess.run(args + ["--historical-replay"], capture_output=True, text=True)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["wall_time_ms_extra"], 1000.0)
            self.assertTrue(any("atom 0" in problem for problem in result["violations"]))

    def test_saved_initial_placement_after_buffer_design(self):
        right = (1, 0)
        run = self.verify([op("Local CNOT", (0, 2), (right, right), 0, 0)],
                          initial={"0": right, "2": right})
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_missing_requested_variant_fails_verification(self):
        left = (0, 0)
        run = self.verify([op("Local CNOT", (0, 1), (left, left), 0, 0)],
                          variants=["IRIS", "QuComm"])
        self.assertEqual(run.returncode, 1)
        self.assertIn("No schedules for QuComm", run.stdout)


if __name__ == "__main__":
    unittest.main()
