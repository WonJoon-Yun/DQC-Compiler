"""Exercise the QuComm block merger through the timed executable schedule."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hyperparameters import HyperParameters
from router._iris import IRISRouter
from router.scheduling.channel_merge import ChannelAwareBlockMerger


LEFT, RIGHT = (0, 0), (0, 1)


def hop(block, tick, atom, source, destination):
    return dict(BlockID=block, Time=tick, CNOT=False, SIdx=atom, TIdx=atom,
                SPos=source, TPos=source, SNextPos=destination, TNextPos=destination)


def gate(block, tick, a, b, src, dst):
    return dict(BlockID=block, Time=tick, CNOT=True, SIdx=a, TIdx=b,
                SPos=src, TPos=dst, SNextPos=src, TNextPos=dst)


def placements(merger, block):
    return [(group_no, row["Time"]) for group_no, group in enumerate(merger.groups)
            for row in group if row["BlockID"] == block]


class ChannelAdmissionTest(unittest.TestCase):
    def test_remote_holds_and_move_reservations_on_the_same_link(self):
        merger = ChannelAwareBlockMerger({(LEFT, RIGHT): 2, (RIGHT, LEFT): 2})
        merger.append([gate(0, 0, 0, 1, LEFT, RIGHT)])
        merger.append([hop(1, 0, 2, RIGHT, LEFT)])
        self.assertGreater(placements(merger, 1)[0], placements(merger, 0)[0])

        # Two remote gates can hold both slots when no move needs the reserve.
        merger = ChannelAwareBlockMerger({(LEFT, RIGHT): 2, (RIGHT, LEFT): 2})
        merger.append([gate(0, 0, 0, 1, LEFT, RIGHT)])
        merger.append([gate(1, 0, 2, 3, RIGHT, LEFT)])
        self.assertEqual(placements(merger, 0), placements(merger, 1))

    def test_two_gate_rows_describing_one_hop_consume_one_slot(self):
        merger = ChannelAwareBlockMerger({(LEFT, RIGHT): 3, (RIGHT, LEFT): 3})
        shared_hop = hop(0, 0, 0, RIGHT, LEFT)
        rows = [dict(shared_hop, TIdx=partner, TPos=LEFT, TNextPos=LEFT)
                for partner in (1, 2)]
        merger.append(rows)
        merger.append([hop(1, 0, 3, RIGHT, LEFT)])
        self.assertEqual(placements(merger, 1), [(0, 0)])
        self.assertEqual(len(merger.groups[0]), 3)

    def test_short_insert_cannot_spend_a_credit_needed_later_in_the_group(self):
        merger = ChannelAwareBlockMerger({(LEFT, RIGHT): 2, (RIGHT, LEFT): 2})
        merger.append([gate(0, 0, 0, 1, LEFT, LEFT), hop(0, 1, 2, RIGHT, LEFT),
                       hop(0, 2, 2, LEFT, RIGHT), gate(0, 3, 0, 1, LEFT, LEFT)])
        merger.append([hop(1, 0, 3, RIGHT, LEFT)])
        # The inserted move would fit at tick 0 by itself, then starve tick 1.
        self.assertEqual(placements(merger, 1), [(0, 3)])


class QuCommChannelMergeTest(unittest.TestCase):
    def schedule(self, gates, barrier_by_time=True, merge_layers=False):
        positions = {atom: LEFT if atom < 4 else RIGHT for atom in range(8)}
        with TemporaryDirectory() as output:
            args = HyperParameters(
                numchipletsx=1, numchipletsy=2, system_qubits_per_chip=10,
                num_communication_per_link=2, num_qubits=8, mapping_method="trivial",
                routing_method="IRIS4", K1=1, K2=6, name="channel_merge",
                routing_output_dir=output, qucomm_one_meet_tiebreak_mode="legacy_direct")
            args.schedule_barrier_by_time = barrier_by_time
            args.schedule_merge_layers = merge_layers
            router = IRISRouter(args, {atom: atom for atom in positions}, positions)
            router.schedule_qucomm([[gate] for gate in gates])
            ops = router.schedule_replay_records

        self.assertCountEqual([(op["atom0"], op["atom1"]) for op in ops
                               if op["optype"] == "Local CNOT"], gates)
        moves = [op for op in ops if op["optype"] == "RELOCATE"]
        self.assertEqual(len(moves), len(gates))
        self.assertEqual(len(ops), 2 * len(gates))
        return {op["atom0"]: op for op in moves}

    def test_two_inbound_moves_wait_for_reverse_credit(self):
        for barrier in (True, False):
            for merge in (False, True):
                with self.subTest(barrier=barrier, merge=merge):
                    moves = self.schedule([(2, 6), (4, 1), (3, 7)], barrier, merge)
                    self.assertEqual(set(moves), {6, 1, 7})
                    for atom in (6, 7):
                        self.assertEqual((tuple(moves[atom]["pos0"]), tuple(moves[atom]["pos1"])),
                                         (RIGHT, LEFT))
                    self.assertEqual((tuple(moves[1]["pos0"]), tuple(moves[1]["pos1"])),
                                     (LEFT, RIGHT))
                    # One of the two initial units must remain. The second inbound
                    # hop can use the restored unit only once atom 1 finishes.
                    start = max(moves[atom]["original_start_time"] for atom in (6, 7))
                    self.assertGreaterEqual(start, moves[1]["original_end_time"])

    def test_opposite_moves_keep_their_legal_overlap(self):
        moves = self.schedule([(2, 6), (4, 1)])
        self.assertEqual(set(moves), {6, 1})
        self.assertEqual(moves[6]["pos0"], moves[1]["pos1"])
        self.assertEqual(moves[6]["pos1"], moves[1]["pos0"])
        self.assertEqual(moves[6]["original_start_time"], moves[1]["original_start_time"])

    def test_flattened_groups_keep_link_dependencies_without_global_barriers(self):
        far = (0, 2)
        positions = {0: RIGHT, 1: LEFT, 2: RIGHT, 3: far}
        args = HyperParameters(numchipletsx=1, numchipletsy=3, system_qubits_per_chip=10,
                               num_communication_per_link=2)
        args.schedule_barrier_by_time = False
        args.schedule_merge_layers = True
        router = IRISRouter(args, {atom: atom for atom in positions}, positions)
        router._channel_aware_blocks = True
        router.reset_metrics([])

        # Both independent IR groups have a single, locally numbered tick zero.
        groups = [[hop(0, 0, 0, RIGHT, LEFT), hop(0, 0, 1, LEFT, RIGHT)],
                  [hop(1, 0, 2, RIGHT, LEFT), hop(1, 0, 3, far, RIGHT)]]
        router.IRLayers = [router.GetQuCommLookaheadIR(group) for group in groups]
        router.get_executable()
        moves = {op["atom0"]: op for op in router.schedule_replay_records}
        self.assertLess(moves[1]["time_bucket_idx"], moves[2]["time_bucket_idx"])
        self.assertGreaterEqual(moves[2]["original_start_time"], moves[1]["original_end_time"])
        self.assertIn(moves[1]["unique_id"], moves[2]["dependency_ids"])
        self.assertEqual(moves[3]["original_start_time"], moves[1]["original_start_time"])


if __name__ == "__main__":
    unittest.main()
