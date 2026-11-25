"""Report the peak number of inter-chip operations in flight on each link of every main-suite schedule.

A flat-pool link has num_communication_per_link interconnect qubit pairs (src/hardware.py).
Operations that end at a timestamp release their pair before operations that start there.

  python revision/issue1_link_concurrency.py ../IRIS-dataset > archive-links.tsv
  python revision/issue1_link_concurrency.py --reroutes <dir of worker artifacts> > reroute-links.tsv
"""
import argparse
import csv
import gzip
import json
import sys
import tarfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTER_CHIP = ("RELOCATE", "Re-CNOT")


def peak_occupancy(ops, pairs):
    events = []
    for op in ops:
        if op["optype"] in INTER_CHIP and op["pos0"] != op["pos1"]:
            link = tuple(sorted((tuple(op["pos0"]), tuple(op["pos1"]))))
            events.append((op["original_start_time"], 1, link))
            events.append((op["original_end_time"], -1, link))
    live, peak, over = Counter(), 0, 0
    for _, step, link in sorted(events):
        live[link] += step
        peak = max(peak, live[link])
        over += step > 0 and live[link] > pairs
    return len(events) // 2, peak, over


def schedules(args):
    if args.reroutes:
        for artifact in sorted(args.reroutes.glob("*.tar.gz")):
            variant, bench, arch = artifact.name.split(".")[0].split("--")
            with tarfile.open(artifact) as tar:
                yield variant, arch, bench, json.load(tar.extractfile("schedule.json"))
    else:
        with (ROOT / "revision/issue1-archive-audit.tsv").open() as f:
            for row in csv.DictReader(f, delimiter="\t"):
                path = args.dataset / row["dataset_relative_schedule"]
                with gzip.open(path, "rt") as source:
                    yield row["variant"], row["architecture"], row["benchmark"], json.load(source)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dataset", type=Path, nargs="?")
    ap.add_argument("--reroutes", type=Path)
    args = ap.parse_args()
    if bool(args.dataset) == bool(args.reroutes):
        ap.error("give either a dataset root or --reroutes")
    out = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    out.writerow(["variant", "architecture", "benchmark", "interconnect_pairs", "inter_chip_operations",
                  "peak_link_occupancy", "starts_above_pairs"])
    for variant, arch, bench, schedule in schedules(args):
        pairs = int(schedule["args_snapshot"]["num_communication_per_link"])
        count, peak, over = peak_occupancy(schedule["ops"], pairs)
        out.writerow([variant, arch, bench, pairs, count, peak, over])


if __name__ == "__main__":
    main()
