"""Replay directional channels in the 72 raw schedules from the issue #1 manifest.

Usage: python3 revision/issue1_archive_channels.py ../IRIS-dataset > channels.tsv
Compare the output with revision/issue1-archive-channels.tsv. All inputs
use a flat pool and contain only local CNOTs and relocations.
"""
import argparse
import csv
from collections import Counter, defaultdict
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import sys


MANIFEST = Path(__file__).with_name("issue1-archive-audit.tsv")
COLUMNS = (
    "variant", "architecture", "benchmark", "archived_atom_locations", "operations",
    "moves", "initial_per_direction", "minimum_interval_balance", "interval_class",
    "minimum_completed_balance", "completed_class", "first_nonpositive_interval_s",
    "first_negative_interval_s", "first_negative_completed_s",
    "ops_spanning_first_negative_completion", "schedule_sha256",
)


def classify(minimum):
    if minimum < 0:
        return "negative"
    if minimum == 0:
        return "zero"
    return "positive"


def initial_balances(run, config):
    capacity = config["num_communication_per_link"]
    nx, ny = config["numchipletsx"], config["numchipletsy"]
    if config.get("system_qubits_per_chip") is None or capacity < 1:
        raise ValueError(f"{run}: expected a flat pool with a positive link capacity")
    with gzip.open(run / "resource_capacity_epochs.json.gz", "rt") as stream:
        epochs = json.load(stream)
    if len(epochs) != 1 or epochs[0]["start_time"] != 0 or epochs[0]["label"] != "pre_schedule":
        raise ValueError(f"{run}: expected one pre-schedule capacity epoch at time zero")
    grid = {((x, y), (x + dx, y + dy)) for x in range(nx) for y in range(ny)
            for dx, dy in ((1, 0), (0, 1)) if x + dx < nx and y + dy < ny}
    balances = {}
    for row in epochs[0]["channel_capacity"]:
        src, dst = tuple(row["src"]), tuple(row["dst"])
        if (src, dst) in balances or row["capacity"] != capacity:
            raise ValueError(f"{run}: duplicate or unexpected capacity for {src}, {dst}")
        balances[src, dst] = balances[dst, src] = capacity
    if set(balances) != grid | {(b, a) for a, b in grid} or not grid:
        raise ValueError(f"{run}: capacity epoch does not match the configured grid")
    return capacity, balances


def replay(dataset, entry):
    path = dataset / entry["dataset_relative_schedule"]
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["gzip_sha256"]:
        raise ValueError(f"{path}: compressed schedule differs from the archive manifest")
    sched = json.loads(gzip.decompress(data), parse_float=Decimal)
    capacity, balance = initial_balances(path.parent, sched["args_snapshot"])
    ops = sched["ops"]
    if len(ops) != int(entry["operation_count"]):
        raise ValueError(f"{path}: operation count differs from the archive manifest")
    starts, ends = defaultdict(Counter), defaultdict(Counter)
    moves = 0
    for index, op in enumerate(ops):
        if op["optype"] == "Local CNOT" and op["pos0"] == op["pos1"]:
            continue
        src, dst = tuple(op["pos0"]), tuple(op["pos1"])
        start, end = op["original_start_time"], op["original_end_time"]
        if (op["optype"] != "RELOCATE" or (src, dst) not in balance or
                op["atom0"] != op["atom1"] or not 0 <= start < end):
            raise ValueError(f"{path}: unsupported or invalid operation at row {index}")
        starts[start][dst, src] += 1
        ends[end][src, dst] += 1
        moves += 1
    if moves != int(entry["relocation_count"]):
        raise ValueError(f"{path}: relocation count differs from the archive manifest")

    completed = balance.copy()
    lowest = lowest_completed = capacity
    first_nonpositive = first_negative = first_negative_completed = None
    for time in sorted(starts.keys() | ends.keys()):
        # A hop completing now supplies its credit before a new hop starts.
        for (src, dst), count in ends.get(time, {}).items():
            balance[src, dst] += count
            completed[src, dst] += count
            completed[dst, src] -= count
        for edge, count in starts.get(time, {}).items():
            balance[edge] -= count
        current = min(balance.values())
        after_completions = min(completed.values())
        lowest = min(lowest, current)
        lowest_completed = min(lowest_completed, after_completions)
        if current <= 0 and first_nonpositive is None:
            first_nonpositive = time
        if current < 0 and first_negative is None:
            first_negative = time
        if after_completions < 0 and first_negative_completed is None:
            first_negative_completed = time
    if balance != completed:
        raise ValueError(f"{path}: interval and completion-only replays finish differently")
    spanning = None
    if first_negative_completed is not None:
        spanning = sum(op["original_start_time"] < first_negative_completed < op["original_end_time"]
                       for op in ops)
    return (entry["variant"], entry["architecture"], entry["benchmark"], entry["raw_replay"],
            len(ops), moves, capacity, lowest, classify(lowest), lowest_completed,
            classify(lowest_completed), first_nonpositive, first_negative, first_negative_completed,
            spanning, entry["gzip_sha256"])


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("dataset", type=Path, help="Extracted IRIS-dataset directory")
    args = cli.parse_args()
    with MANIFEST.open() as stream:
        entries = list(csv.DictReader(stream, delimiter="\t"))
    if len(entries) != 72 or len({e["dataset_relative_schedule"] for e in entries}) != 72:
        raise ValueError(f"{MANIFEST}: expected 72 distinct main schedules")
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(COLUMNS)
    for entry in entries:
        writer.writerow(replay(args.dataset, entry))


if __name__ == "__main__":
    main()
