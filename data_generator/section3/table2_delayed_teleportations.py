#!/usr/bin/env python3
"""§3.2 Table 2 — Percentage of delayed teleportations and their average wait
time on a 3x3 DQC with 240-qubit programs (QAOA-FC, QFT, QV, Shor, VQE).

The scheduler computes these metrics at run time and stores them in each
results JSON under `eee_motivation`:
  early_ready_pct            share of RELOCATEs whose data dependencies had
                             resolved before the RELOCATE started (delayed %)
  avg_idle_per_early_relocate  mean wait of those RELOCATEs, in seconds

This script reads the fields from the QuComm runs.

Output: output/section3/table2_delayed_teleportations.csv
"""
from __future__ import annotations

import csv
import gzip
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import load_json, output_dir, result_dir, result_json, tracer_csv

BENCHMARKS = ["qaoa_fc", "qft", "qv", "shor", "vqe"]
DISPLAY = {"qaoa_fc": "QAOA-FC", "qft": "QFT", "qv": "QV", "shor": "Shor", "vqe": "VQE"}
ARCH = "F240"
N_QUBITS = 240
MAPPER = "ILP"
VARIANT = "QuComm"


def _open_csv(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", newline="")
    return path.open(newline="")


def _analyze_tracer(path: Path) -> dict:
    """Rebuild Table-2 metrics from a freshly generated tracer CSV."""
    with _open_csv(path) as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return {}

    all_ops = []
    relocates = []
    for row in rows:
        op = row["optype"]
        item = (
            int(float(row["count"])),
            int(float(row["atom0"])),
            int(float(row["atom1"])),
            float(row["start_time"]),
            float(row["end_time"]),
            op,
        )
        all_ops.append(item)
        if op == "RELOCATE":
            relocates.append(item[:5])
    if not relocates:
        return {}

    qubit_end_times = defaultdict(list)
    for count, atom0, atom1, _start, end, _op in all_ops:
        qubit_end_times[atom0].append((end, count))
        if atom1 != atom0:
            qubit_end_times[atom1].append((end, count))
    for times in qubit_end_times.values():
        times.sort()

    early_count = 0
    idle_sum = 0.0
    for count, atom0, _atom1, start, _end in relocates:
        last_prior_end = None
        for end, other_count in qubit_end_times[atom0]:
            if other_count != count and end <= start + 1e-12:
                if last_prior_end is None or end > last_prior_end:
                    last_prior_end = end
        if last_prior_end is not None and start - last_prior_end > 1e-9:
            early_count += 1
            idle_sum += start - last_prior_end

    total = len(relocates)
    return {
        "total_relocates": total,
        "early_ready_count": early_count,
        "early_ready_pct": early_count / total * 100.0,
        "avg_idle_per_early_relocate": idle_sum / early_count if early_count else 0.0,
    }


def main() -> None:
    out = output_dir("section3")
    csv_path = out / "table2_delayed_teleportations.csv"
    rows = [["benchmark", "total_RELOCATEs", "delayed_RELOCATEs",
             "delayed_pct", "avg_wait_ms"]]
    for fam in BENCHMARKS:
        bench = f"{fam}_n{N_QUBITS}"
        p = result_json(VARIANT, ARCH, MAPPER, bench)
        em = (load_json(p).get("eee_motivation") or {}) if p else {}
        if not em:
            trace = tracer_csv(VARIANT, ARCH, MAPPER, bench)
            if trace:
                em = _analyze_tracer(trace)
        if not em:
            raise SystemExit(
                f"missing Table-2 data for {bench}: expected eee_motivation in "
                f"results JSON or a tracer CSV under "
                f"{result_dir(VARIANT, ARCH, MAPPER, bench)}"
            )
        rows.append([
            DISPLAY[fam],
            em.get("total_relocates", ""),
            em.get("early_ready_count", ""),
            f"{float(em.get('early_ready_pct', 0)):.1f}",
            f"{float(em.get('avg_idle_per_early_relocate', 0)) * 1000.0:.1f}",
        ])
    with csv_path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
