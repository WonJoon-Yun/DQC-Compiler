"""A channel release moves a real atom before another atom can use the freed slot."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.schedule_locations import pipeline_rows, read_schedule
from hyperparameters import HyperParameters
from route.route.qucomm import our_qucomm
from router._baseline import BaselineRouter
from router.optim.early_execution import pipeline_optimization, qucomm_parallel_schedule
from router.scheduling._lookahead import LookaheadMixin


A, B, C, D = [(0, i) for i in range(4)]
SATURATED = {(A, B): 9, (B, A): 1, (B, C): 1, (C, B): 9}


def route(positions, gates, channels):
    graph = nx.Graph(list(channels))
    paths = {atom: [pos] for atom, pos in positions.items()}
    return our_qucomm(0, gates, positions, graph, B, channels.copy(), paths)


def scheduled_hops(rows):
    router = SimpleNamespace(args=SimpleNamespace(time_int_SWAP=1))
    buckets = LookaheadMixin.GetQuCommLookaheadIR(router, rows)
    return [
        (tick, move["SIdx"], *move["BeforeOperationSourcePath"])
        for tick, bucket in enumerate(buckets)
        for move in bucket.values() if move["NextOperation"]
    ]


class EvictionScheduleTest(unittest.TestCase):
    def test_inactive_victim_precedes_move_using_released_slot(self):
        rows, paths, _, moves, _, releases, _ = route(
            {1: A, 2: C, 3: B}, [(1, 2)], SATURATED)
        self.assertEqual((paths[3], moves, releases), ([B, C], 2, 1))
        self.assertEqual(scheduled_hops(rows), [
            (0, 3, B, C), (1, 2, C, B), (2, 2, B, A)])

    def test_active_evicted_atom_moves_once(self):
        # The victim has already executed its gate in this block.
        rows, _, _, moves, _, releases, _ = route(
            {1: A, 2: C, 3: B, 4: B}, [(3, 4), (1, 2)], SATURATED)
        self.assertEqual((moves, releases), (2, 1))
        self.assertEqual(scheduled_hops(rows), [
            (1, 3, B, C), (2, 2, C, B), (3, 2, B, A)])

    def test_consecutive_evictions_survive_early_execution(self):
        channels = SATURATED.copy()
        channels.update({(C, D): 1, (D, C): 9})
        rows, _, _, moves, _, releases, _ = route(
            {1: A, 2: D, 3: B, 4: C}, [(1, 2)], channels)
        self.assertEqual((moves, releases), (3, 2))
        windows, _ = pipeline_optimization(rows, channels, 0, 10, debug=False)
        hops = scheduled_hops([row for window in windows for row in window])
        self.assertCountEqual([hop[1:] for hop in hops], [
            (4, C, D), (2, D, C), (3, B, C), (2, C, B), (2, B, A)])
        times = {hop[1:]: hop[0] for hop in hops}
        self.assertLess(times[4, C, D], times[2, D, C])
        self.assertLess(times[3, B, C], times[2, C, B])

    def test_saved_and_postprocessed_schedule_wait_for_eviction(self):
        positions = {1: A, 2: C, 3: B}
        rows, _, _, _, _, _, _ = route(positions, [(1, 2)], SATURATED)
        windows, _ = pipeline_optimization(rows, SATURATED, 0, 10, debug=False)
        for barrier in (True, False):
            with self.subTest(barrier=barrier), TemporaryDirectory() as tmp:
                args = HyperParameters(numchipletsx=1, numchipletsy=3,
                                       system_qubits_per_chip=20, num_communication_per_link=5)
                args.schedule_barrier_by_time = barrier
                router = BaselineRouter(args, {q: q for q in positions}, positions)
                router.reset_metrics([[(1, 2)]])
                router.IRLayers = [router.GetQuCommLookaheadIR(window) for window in windows]
                router.get_executable()
                path = router.save_schedule_replay(tmp)
                ops = read_schedule(Path(path))["ops"]
                evict = next(o for o in ops if o["atom0"] == 3)
                hop = next(o for o in ops if o["atom0"] == 2 and tuple(o["pos0"]) == C)
                self.assertGreaterEqual(hop["original_start_time"], evict["original_end_time"])
                self.assertIn(evict["unique_id"], hop["dependency_ids"])
                self.assertEqual(router.num_interconnect_SWAPs, 3)
                pipeline, channels = pipeline_rows(ops)
                placed = qucomm_parallel_schedule(pipeline, channels, -1000, 2000,
                                                  link_epr_capacity=5, debug=False)
                times = {(r["SIdx"], r["SPos"]): r["Time"] for r in placed if not r["CNOT"]}
                self.assertLess(times[3, B], times[2, C])

    def test_open_links_preserve_original_schedule(self):
        rows, _, _, moves, _, releases, _ = route(
            {1: A, 2: C, 3: B}, [(1, 2)], dict.fromkeys(SATURATED, 5))
        self.assertEqual((moves, releases), (2, 0))
        self.assertEqual(scheduled_hops(rows), [(0, 2, C, B), (1, 2, B, A)])


if __name__ == "__main__":
    unittest.main()
