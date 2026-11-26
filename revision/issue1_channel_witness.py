"""Read a raw QuComm run and report its first negative directional channel balance.

    python revision/issue1_channel_witness.py ../IRIS-dataset/MinCut/QuComm/qft_n180-S42C5-2x3

The flat-pool router initializes each direction with C slots (_iris.py).
Buffer design returns its input channel map. Check C against the saved capacity
epoch and replay the +1 forward / -1 reverse deltas in route/channel.py.
Combine all hops with the same completion timestamp before checking balances.
"""

import argparse
from collections import Counter
import gzip
from itertools import groupby
import json
from pathlib import Path


def load(run, stem):
    path = run / f"{stem}.json"
    if path.exists():
        return json.loads(path.read_text())
    with gzip.open(run / f"{stem}.json.gz", "rt") as data:
        return json.load(data)


def witness(run):
    schedule = load(run, "schedule")
    args = schedule["args_snapshot"]
    capacity = args["num_communication_per_link"]
    nx, ny = args["numchipletsx"], args["numchipletsy"]
    epochs = load(run, "resource_capacity_epochs")
    if len(epochs) != 1 or epochs[0]["label"] != "pre_schedule" or epochs[0]["start_time"] != 0:
        raise ValueError("Expected one pre_schedule capacity epoch at time zero")
    links = {tuple(sorted((tuple(e["src"]), tuple(e["dst"])))): e["capacity"]
             for e in epochs[0]["channel_capacity"]}
    grid_edges = {((x, y), (x + dx, y + dy)) for x in range(nx) for y in range(ny)
                  for dx, dy in ((0, 1), (1, 0)) if x + dx < nx and y + dy < ny}
    if set(links) != grid_edges or set(links.values()) != {capacity}:
        raise ValueError("Expected the saved grid links to have uniform configured capacity C")
    counts = Counter()
    ops = schedule["ops"]
    moves = sorted((o for o in ops if o["optype"] == "RELOCATE"),
                   key=lambda o: o["original_end_time"])
    for end, group in groupby(moves, key=lambda o: o["original_end_time"]):
        finished = list(group)
        touched = set()
        for op in finished:
            a, b = tuple(op["pos0"]), tuple(op["pos1"])
            if tuple(sorted((a, b))) not in links:
                raise ValueError(f"Relocation uses an unlisted link {a}, {b}")
            counts[a, b] += 1
            touched.update(((a, b), (b, a)))
        for a, b in sorted(touched):
            balance = capacity + counts[a, b] - counts[b, a]
            if balance < 0:
                edge_ops = [[o["atom0"], o["layer_id"], o["pos0"], o["pos1"]] for o in finished
                            if {tuple(o["pos0"]), tuple(o["pos1"])} == {a, b}]
                return dict(end_seconds=end, edge=[a, b], initial=capacity,
                            completed_forward=counts[a, b], completed_reverse=counts[b, a],
                            balance=balance, finishing_atom_block_src_dst=edge_ops,
                            ops_spanning_boundary=sum(o["original_start_time"] < end < o["original_end_time"]
                                                       for o in ops))
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="+")
    for run_dir in parser.parse_args().run:
        print(json.dumps({"run": str(run_dir), "first_negative": witness(run_dir)}))
