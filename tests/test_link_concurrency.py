"""A flat-pool link never carries more inter-chip operations than its interconnect pairs."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hyperparameters import HyperParameters
from router._iris import IRISRouter


LEFT, RIGHT = (0, 0), (0, 1)


def hop(block, tick, atom, source, destination):
    return dict(BlockID=block, Time=tick, CNOT=False, SIdx=atom, TIdx=atom,
                SPos=source, TPos=source, SNextPos=destination, TNextPos=destination)


def schedule(groups, link_qubits=3):
    positions = {0: RIGHT, 1: RIGHT, 2: LEFT, 3: LEFT}
    args = HyperParameters(numchipletsx=1, numchipletsy=2, system_qubits_per_chip=10,
                           num_communication_per_link=link_qubits)
    router = IRISRouter(args, {atom: atom for atom in positions}, positions)
    router._channel_aware_blocks = True
    router.reset_metrics([])
    router.IRLayers = [router.GetQuCommLookaheadIR(group) for group in groups]
    router.get_executable()
    return router, {op["atom0"]: op for op in router.schedule_replay_records}


def peak_occupancy(moves):
    events = sorted([(m["original_start_time"], 1) for m in moves] +
                    [(m["original_end_time"], -1) for m in moves], key=lambda e: (e[0], e[1]))
    live = peak = 0
    for _, step in events:
        live += step
        peak = max(peak, live)
    return peak


class LinkConcurrencyTest(unittest.TestCase):
    def test_overlapping_blocks_wait_for_a_free_interconnect_pair(self):
        router, moves = schedule([[hop(0, 0, 0, RIGHT, LEFT), hop(0, 0, 2, LEFT, RIGHT),
                                   hop(1, 0, 1, RIGHT, LEFT), hop(1, 0, 3, LEFT, RIGHT)]])
        self.assertEqual(router.schedule_replay_policy["max_parallel_per_link"], 3)
        self.assertTrue(router.schedule_replay_policy["schedule_cap_channels"])
        self.assertEqual(peak_occupancy(moves.values()), 3)
        first_end = min(m["original_end_time"] for m in moves.values())
        late = [m for m in moves.values() if m["original_start_time"] > 0]
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0]["original_start_time"], first_end)

    def test_hops_within_capacity_keep_their_shared_start(self):
        _, moves = schedule([[hop(0, 0, 0, RIGHT, LEFT), hop(0, 0, 2, LEFT, RIGHT),
                              hop(1, 0, 1, RIGHT, LEFT)]])
        self.assertEqual({m["original_start_time"] for m in moves.values()}, {0.0})


if __name__ == "__main__":
    unittest.main()
