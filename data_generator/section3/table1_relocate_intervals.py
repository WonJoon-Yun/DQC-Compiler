#!/usr/bin/env python3
"""§3.1 Table 1 — Average #CNOTs, #blocks, #local-only-blocks, and #EPR
releases between two consecutive RELOCATEs involving a qubit, on a 3x3 DQC
with 240-qubit programs (QAOA-FC, QFT, QV, Shor, VQE).

Reads QuComm Schedule JSONs (which list per-block op rows). For each RELOCATE
on a qubit q, find the next RELOCATE on the same qubit and count the ops
between them.

Output: output/section3/table1_relocate_intervals.csv
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import load_json, output_dir, schedule_json

BENCHMARKS = ["qaoa_fc", "qft", "qv", "shor", "vqe"]
DISPLAY = {"qaoa_fc": "QAOA-FC", "qft": "QFT", "qv": "QV", "shor": "Shor", "vqe": "VQE"}
ARCH = "F240"
N_QUBITS = 240
MAPPER = "ILP"
VARIANT = "QuComm"


def _flatten_schedule(sched: dict) -> List[dict]:
    """Schedule JSONs use combined_schedule list-of-list-of-rows; flatten."""
    rows: List[dict] = []
    cs = sched.get("combined_schedule") or sched.get("schedule") or []
    for entry in cs:
        if isinstance(entry, list):
            rows.extend(entry)
        elif isinstance(entry, dict):
            rows.append(entry)
    return rows


def _analyze(schedule_path: Path) -> dict:
    sched = load_json(schedule_path)
    rows = _flatten_schedule(sched)
    # Sort rows by Time (cycle), then by row order
    rows.sort(key=lambda r: (r.get("Time", 0), r.get("BlockID", 0)))

    # Walk rows. Maintain per-qubit "last RELOCATE row idx". For each new
    # RELOCATE on qubit q, the interval is from previous-RELOCATE-row to this one.
    prev_reloc_row: Dict[int, int] = {}
    intervals: List[dict] = []
    for i, r in enumerate(rows):
        is_cnot = bool(r.get("CNOT") or r.get("Operation") == "CNOT")
        if is_cnot:
            continue
        sidx = r.get("SIdx")
        tidx = r.get("TIdx")
        spos = r.get("SPos")
        sn = r.get("SNextPos")
        tpos = r.get("TPos")
        tn = r.get("TNextPos")
        for (q, p, np_) in ((sidx, spos, sn), (tidx, tpos, tn)):
            if q is None or p == np_:
                continue
            if q in prev_reloc_row:
                intervals.append({"q": q, "start": prev_reloc_row[q], "end": i})
            prev_reloc_row[q] = i

    if not intervals:
        return {"intervals": 0, "mean_cnots": 0.0, "mean_blocks": 0.0,
                "mean_local_only_blocks": 0.0, "mean_releases": 0.0}

    # For each interval, scan rows between (exclusive of endpoints)
    cnots, blocks, local_blocks, releases = [], [], [], []
    for iv in intervals:
        seg = rows[iv["start"] + 1: iv["end"]]
        n_cnot = sum(1 for r in seg if (r.get("CNOT") or r.get("Operation") == "CNOT"))
        seg_blocks = {r.get("BlockID") for r in seg if r.get("BlockID") is not None}
        local_only_blocks = set()
        for b in seg_blocks:
            block_rows = [r for r in seg if r.get("BlockID") == b]
            has_nonlocal = any(r.get("Operation") in ("Re-CNOT", "RELOCATE") for r in block_rows)
            if not has_nonlocal:
                local_only_blocks.add(b)
        cnots.append(n_cnot)
        blocks.append(len(seg_blocks))
        local_blocks.append(len(local_only_blocks))
        releases.append(sum(1 for r in seg if r.get("Operation") == "RELEASE"))

    def _mean(xs): return sum(xs) / len(xs) if xs else 0.0
    return {
        "intervals": len(intervals),
        "mean_cnots": _mean(cnots),
        "mean_blocks": _mean(blocks),
        "mean_local_only_blocks": _mean(local_blocks),
        "mean_releases": _mean(releases),
    }


def main() -> None:
    out = output_dir("section3")
    csv_path = out / "table1_relocate_intervals.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["benchmark", "intervals", "mean_CNOTs", "mean_blocks",
                    "mean_local_only_blocks", "mean_releases"])
        for fam in BENCHMARKS:
            bench = f"{fam}_n{N_QUBITS}"
            sp = schedule_json(VARIANT, ARCH, MAPPER, bench)
            if sp is None:
                w.writerow([DISPLAY[fam], "", "", "", "", ""])
                continue
            r = _analyze(sp)
            w.writerow([
                DISPLAY[fam], r["intervals"],
                f"{r['mean_cnots']:.2f}",
                f"{r['mean_blocks']:.2f}",
                f"{r['mean_local_only_blocks']:.2f}",
                f"{r['mean_releases']:.3f}",
            ])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
