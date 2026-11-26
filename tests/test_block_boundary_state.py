"""Replay a reduced QAOA case where lookahead and the routed block disagree."""
import sys
import unittest
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from route.scheduler import schedule_blocks
from route.types import Gate, RoutingState


class TestBlockBoundaryState(unittest.TestCase):
    def test_committed_state_matches_executed_blocks(self):
        grid = nx.grid_2d_graph(2, 2)
        home = (0, 0)
        positions = {0: home, 1: home, 2: (0, 1), 3: (1, 0), 4: (1, 0)}
        channels = {edge: 5 for edge in grid.to_directed().edges}
        initial = RoutingState(positions, channels, {q: [p] for q, p in positions.items()})
        pairs = [[(2, 4), (0, 1)], [(2, 4)], [(4, 3)]]
        blocks = [
            [Gate(i, q, r, positions[q], positions[r]) for q, r in block]
            for i, block in enumerate(pairs)
        ]
        interactions = {
            q: [gate for block in blocks for gate in block if q in (gate.atom0, gate.atom1)]
            for q in positions
        }

        for count in (1, 2):
            with self.subTest(executed_blocks=count):
                plan = schedule_blocks(
                    blocks, [home] * 3, [1, 2, 3], initial, grid, K=count,
                    block_levels=[1, 2, 3], interact_info=interactions,
                    qucomm_enable_gate_lookahead=True, qucomm_gate_lookahead_depth=4,
                    qucomm_gate_lookahead_option="opt1", qucomm_enable_gate_foresight=True,
                    qucomm_gate_lookahead_prune_mode="selection_sort", enable_teleport_hybrid=True,
                )
                # The first block's two gates have disjoint operands. Each row
                # therefore names a given atom at most once per time step.
                paths = {q: [p] for q, p in positions.items()}
                balance = channels.copy()
                for i, rows in enumerate(plan.combined_schedule):
                    gates = []
                    for row in rows:
                        for side in ("S", "T"):
                            q = row[side + "Idx"]
                            start, end = row[side + "Pos"], row[side + "NextPos"]
                            self.assertEqual(paths[q][-1], start, (i, q))
                            if start != end:
                                paths[q].append(end)
                                balance[start, end] += 1
                                balance[end, start] -= 1
                        if row["CNOT"]:
                            gates.append((row["SIdx"], row["TIdx"]))
                    self.assertEqual(gates, pairs[i])
                    self.assertEqual(plan.per_block_info[i].channel_dict, balance)

                self.assertEqual(plan.state_after.atom_paths, paths)
                self.assertEqual(plan.state_after.position_table, {q: p[-1] for q, p in paths.items()})
                self.assertEqual(plan.state_after.channel_dict, balance)
                self.assertEqual(plan.done_ids, list(range(1, count + 1)))
                expected_pending = {q: [] for q in positions}
                for block in blocks[count:]:
                    for gate in block:
                        expected_pending[gate.atom0].append(gate)
                        expected_pending[gate.atom1].append(gate)
                self.assertEqual(plan.interact_info, expected_pending)


if __name__ == "__main__":
    unittest.main()
