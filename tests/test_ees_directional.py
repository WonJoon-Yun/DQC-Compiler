"""Native EES must have a channel slot at the start of every moved hop."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from hyperparameters import HyperParameters
from router._iris import IRISRouter


A, B, C = (0, 0), (0, 1), (0, 2)


def move(tick, atom, src, dst):
    return dict(Time=tick, BlockID=0, CNOT=False, SIdx=atom, TIdx=atom, SPos=src,
                SNextPos=dst, TPos=src, TNextPos=src)


def local(tick, first, second, chip):
    return dict(Time=tick, BlockID=0, CNOT=True, SIdx=first, TIdx=second, SPos=chip,
                SNextPos=chip, TPos=chip, TNextPos=chip)


class EesDirectionalTest(unittest.TestCase):
    def optimize(self, rows, opening, maximum):
        args = HyperParameters(numchipletsx=1, numchipletsy=3, system_qubits_per_chip=12,
                               num_communication_per_link=maximum // 2, enable_ees=True)
        router = IRISRouter(args, {}, {})
        windows, _ = router._run_pipeline_optimization(rows, opening, 0, maximum)
        scheduled = [r for window in windows for r in window]
        identity = lambda r: (r['CNOT'], r['SIdx'], r['TIdx'], r['SPos'], r['SNextPos'])
        self.assertCountEqual(map(identity, rows), map(identity, scheduled))
        return {r['SIdx']: r['Time'] for r in scheduled if not r['CNOT']}

    def test_opposite_move_can_use_only_a_completed_credit(self):
        rows = [move(0, 0, A, B), move(1, 1, B, A)]
        for slots, second_tick in ((1, 1), (3, 0)):
            with self.subTest(initial_forward_slots=slots):
                ticks = self.optimize(rows, {(A, B): slots, (B, A): 3}, 6)
                self.assertEqual(ticks, {0: 0, 1: second_tick})

    def test_two_block_epoch_checks_the_shared_link_before_flattening(self):
        blocks = [[move(0, 0, A, B)], [dict(move(0, 1, B, A), BlockID=1)]]
        for slots, second_tick in ((1, 1), (3, 0)):
            with self.subTest(initial_forward_slots=slots):
                opening = {(A, B): slots, (B, A): 3}
                rows = IRISRouter._build_ees_flat_pipeline(blocks, opening)
                self.assertEqual(self.optimize(rows, opening, 6), {0: 0, 1: second_tick})

    def test_native_postcondition_rejects_an_already_overdrawn_tick(self):
        rows = [move(0, 0, A, B), move(0, 1, B, A)]
        with self.assertRaisesRegex(AssertionError, "directional-reserve"):
            self.optimize(rows, {(A, B): 1, (B, A): 3}, 6)

    def test_advance_must_preserve_move_reservations_in_intermediate_ticks(self):
        rows = [move(0, 3, B, C), local(0, 0, 4, B), local(0, 1, 5, A),
                move(1, 0, B, A), move(1, 1, A, B), move(2, 2, B, A)]
        for slots, advance_tick in ((2, 2), (3, 0)):
            with self.subTest(initial_forward_slots=slots):
                opening = {(A, B): slots, (B, A): 4, (B, C): 3, (C, B): 3}
                ticks = self.optimize(rows, opening, 8)
                # Moving atom 2 early must leave a consumable slot for atom 0 at tick 1.
                self.assertEqual(ticks, {0: 1, 1: 1, 2: advance_tick, 3: 0})


if __name__ == '__main__':
    unittest.main()
