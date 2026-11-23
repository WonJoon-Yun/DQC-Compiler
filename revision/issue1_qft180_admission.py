"""Offline admission test for two recorded QuComm QFT180 block pairs.

Usage: python issue1_qft180_admission.py path/to/MinCut/QuComm/qft_n180-S42C5-2x3
A relocation debits the reverse direction at the start of its logical tick
and credits the forward direction at the end. Keep each direction positive.
"""
import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path


from issue1_channel_witness import load


def evaluate(ops, opening, closing, delay):
    by_tick = defaultdict(list)
    active = []
    for block, offset in zip(ops, (0, delay)):
        origin = min(op["time_bucket_idx"] for op in block)
        ticks = set()
        for op in block:
            tick = op["time_bucket_idx"] - origin + offset
            by_tick[tick].append(op)
            ticks.add(tick)
        active.append(ticks)
    assert Counter(op["unique_id"] for group in by_tick.values() for op in group) == Counter(
        op["unique_id"] for block in ops for op in block
    )
    balances = dict(opening)
    minimum_after_debits = min(balances.values())
    minimum_at_close = min(balances.values())
    edge = ((1, 1), (1, 2))
    shared_edge_moves = []
    for tick, group in sorted(by_tick.items()):
        credits = Counter()
        for op in group:
            if op["optype"] == "Local CNOT":
                continue
            assert op["optype"] == "RELOCATE", op["optype"]
            src, dst = tuple(op["pos0"]), tuple(op["pos1"])
            balances[dst, src] -= 1
            credits[src, dst] += 1
            if (src, dst) == edge or (dst, src) == edge:
                shared_edge_moves.append([tick, int(op["layer_id"]), op["atom0"],
                                          1 if (src, dst) == edge else -1])
        minimum_after_debits = min(minimum_after_debits, min(balances.values()))
        for direction, count in credits.items():
            balances[direction] += count
        minimum_at_close = min(minimum_at_close, min(balances.values()))
    assert balances == closing
    return dict(delay=delay, overlap_ticks=len(active[0] & active[1]),
                span_ticks=max(by_tick) + 1, min_after_debits=minimum_after_debits,
                min_at_close=minimum_at_close, shared_edge_moves=shared_edge_moves)


def pair(schedule, results, ids):
    rows = [[op for op in schedule["ops"] if int(op["layer_id"]) == i] for i in ids]
    atoms = [{q for op in block for q in (op["atom0"], op["atom1"])} for block in rows]
    assert not (atoms[0] & atoms[1])
    assert all(len({r["schedule_layer_idx"] for r in block}) == 1 for block in rows)
    assert rows[0][0]["schedule_layer_idx"] == rows[1][0]["schedule_layer_idx"]
    assert min(r["time_bucket_idx"] for r in rows[0]) == min(r["time_bucket_idx"] for r in rows[1])
    lengths = []
    for block in rows:
        ticks = {r["time_bucket_idx"] for r in block}
        assert len(ticks) == max(ticks) - min(ticks) + 1
        lengths.append(len(ticks))
    snapshots = results["distribution_of_channels_on_large_block"]
    opening, closing = [{ast.literal_eval(k): v for k, v in snapshots[i].items()}
                        for i in (ids[0] - 1, ids[-1])]
    assert len(opening) == len(closing) == 14
    offsets = [evaluate(rows, opening, closing, delay) for delay in range(lengths[0] + 1)]
    earliest = next(v for v in offsets if v["min_after_debits"] >= 1)
    ops = Counter(op["optype"] for block in rows for op in block)
    return dict(blocks=ids, group=rows[0][0]["schedule_layer_idx"], lengths=lengths,
                directional_links=len(opening), opening_shared_edge=opening[(1, 1), (1, 2)],
                preserved_ops=dict(sorted(ops.items())), original=offsets[0],
                earliest_admitted=earliest, serial=offsets[-1],
                candidate_minima=[[v["delay"], v["min_after_debits"], v["min_at_close"]]
                                  for v in offsets[:earliest["delay"] + 1]])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    run = parser.parse_args().run
    schedule, results = load(run, "schedule"), load(run, "results")
    assert schedule["args_snapshot"]["K1"] == 1
    print(json.dumps([pair(schedule, results, ids) for ids in ((115, 116), (187, 188))], indent=2))
