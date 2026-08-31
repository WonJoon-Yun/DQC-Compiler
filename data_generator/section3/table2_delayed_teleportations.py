#!/usr/bin/env python3
"""§3.2 Table 2 — Percentage of delayed teleportations and average wait time
on a 3x3 DQC with 240-qubit programs (QAOA-FC, QFT, QV, Shor, VQE).

Reads each QuComm Tracer CSV and computes:
  - early_ready_pct: fraction of RELOCATEs whose data-dependency resolved
                     before their start (i.e. delayed)
  - avg_idle_per_early_relocate: mean idle time per such RELOCATE (seconds)

Output: output/section3/table2_delayed_teleportations.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import output_dir, tracer_csv

BENCHMARKS = ["qaoa_fc", "qft", "qv", "shor", "vqe"]
DISPLAY = {"qaoa_fc": "QAOA-FC", "qft": "QFT", "qv": "QV", "shor": "Shor", "vqe": "VQE"}
ARCH = "F240"
N_QUBITS = 240
MAPPER = "ILP"
VARIANT = "QuComm"


def _analyze_tracer(csv_path: Path) -> dict:
    """Compute % delayed RELOCATEs and average idle time."""
    rows: List[dict] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    # Per-atom: when does each "data-dep" complete? We use the last preceding
    # op (Local CNOT, Re-CNOT, RELOCATE) on the same atom as the dep timestamp.
    atom_last_end: dict = {}
    total = 0
    delayed = 0
    total_idle = 0.0
    for r in rows:
        optype = r.get("optype") or r.get("OpType") or ""
        try:
            start = float(r.get("start_time") or r.get("StartTime") or 0)
            end = float(r.get("end_time") or r.get("EndTime") or 0)
        except (ValueError, TypeError):
            continue
        if optype == "RELOCATE":
            # Identify the qubit being moved (atom)
            atom = r.get("atom") or r.get("Atom") or r.get("SIdx")
            if atom is None:
                continue
            dep_end = atom_last_end.get(atom, 0.0)
            total += 1
            idle = start - dep_end
            # delayed = dependency completed strictly before scheduled start
            if dep_end < start and idle > 0:
                delayed += 1
                total_idle += idle
            atom_last_end[atom] = end
        else:
            for k in ("atom", "SIdx", "TIdx"):
                a = r.get(k)
                if a:
                    atom_last_end[a] = max(atom_last_end.get(a, 0.0), end)
    early_pct = 100.0 * delayed / total if total else 0.0
    avg_idle = total_idle / delayed if delayed else 0.0
    return {
        "total_relocates": total,
        "delayed": delayed,
        "early_ready_pct": early_pct,
        "avg_idle_seconds": avg_idle,
    }


def main() -> None:
    out = output_dir("section3")
    csv_path = out / "table2_delayed_teleportations.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["benchmark", "total_RELOCATEs", "delayed_RELOCATEs",
                    "delayed_pct", "avg_wait_seconds"])
        for fam in BENCHMARKS:
            bench = f"{fam}_n{N_QUBITS}"
            tp = tracer_csv(VARIANT, ARCH, MAPPER, bench)
            if tp is None:
                w.writerow([DISPLAY[fam], "", "", "", ""])
                continue
            r = _analyze_tracer(tp)
            w.writerow([
                DISPLAY[fam],
                r["total_relocates"],
                r["delayed"],
                f"{r['early_ready_pct']:.1f}",
                f"{r['avg_idle_seconds']:.4f}",
            ])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
