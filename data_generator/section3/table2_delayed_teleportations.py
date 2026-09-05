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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import load_json, output_dir, result_json

BENCHMARKS = ["qaoa_fc", "qft", "qv", "shor", "vqe"]
DISPLAY = {"qaoa_fc": "QAOA-FC", "qft": "QFT", "qv": "QV", "shor": "Shor", "vqe": "VQE"}
ARCH = "F240"
N_QUBITS = 240
MAPPER = "ILP"
VARIANT = "QuComm"


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
            rows.append([DISPLAY[fam], "", "", "", ""])
            continue
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
