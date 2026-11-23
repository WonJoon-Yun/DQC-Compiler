"""Recheck the 72 published MinCut schedules against the issue #1 audit manifest."""

import argparse
from collections import Counter
import csv
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis.schedule_locations import initial_locations, pipeline_rows, read_schedule, validate_locations


def check(dataset, row):
    path = dataset / row["dataset_relative_schedule"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != row["gzip_sha256"]:
        raise ValueError(f"{path}: compressed schedule differs from the published input")
    schedule = read_schedule(path)
    ops = schedule["ops"]
    rows, _ = pipeline_rows(ops)
    initial = initial_locations(schedule)
    error = ""
    try:
        validate_locations(rows, initial, original_times=True)
    except ValueError as exc:
        error = str(exc)
    observed = (len(ops), sum(op["optype"] == "RELOCATE" for op in ops),
                "FAIL" if error else "PASS", error)
    expected = (int(row["operation_count"]), int(row["relocation_count"]),
                row["raw_replay"], row["first_failure"])
    if observed != expected:
        raise ValueError(f"{path}: expected {expected!r}, observed {observed!r}")
    return bool(error)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="Extracted IRIS-dataset directory")
    args = parser.parse_args()
    failures, totals = Counter(), Counter()
    with (ROOT / "revision/issue1-archive-audit.tsv").open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            variant = row["variant"]
            failures[variant] += check(args.dataset, row)
            totals[variant] += 1
    for variant, total in sorted(totals.items()):
        print(f"{variant}: {failures[variant]}/{total} schedules with a recorded violation")
