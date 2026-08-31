#!/usr/bin/env python3
"""§6.7 Fig 16 — Sensitivity of T_eff/L to
    w   (qucomm_gate_lookahead_beam_width) ∈ {2, 4, 8, 16, 32}
    |G| (qucomm_gate_lookahead_depth)      ∈ {2, 4, 6, 8, 10}

Collects the sweep runs from the dataset-layout results tree
    results/_full/MinCut/{QuComm,IRIS}-bw<W>/<bench>-<archdir>/
    results/_full/MinCut/{QuComm,IRIS}-lh<G>/<bench>-<archdir>/
(produced by `bash scripts/fig_16.sh`, or read straight from a seeded
IRIS-dataset by pointing RESULTS_BASE at it) and emits one CSV row per run.

Output: output/section6/figure16_w_group_sensitivity.csv
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import RESULTS_BASE, compute_teff, output_dir

SWEEP_RE = re.compile(r"^(QuComm|IRIS)-(bw|lh)(\d+)$")
RUN_RE = re.compile(r"^(.*)-(S\d+C\d+-\d+x\d+)$")


def _load_results(run_dir: Path) -> dict | None:
    for name in ("results.json",):
        p = run_dir / name
        if p.exists():
            return json.loads(p.read_text())
    for p in sorted(run_dir.glob("results*.json")):
        return json.loads(p.read_text())
    for p in sorted(run_dir.glob("results*.json.gz")):
        return json.loads(gzip.decompress(p.read_bytes()))
    return None


def main() -> None:
    out = output_dir("section6")
    csv_path = out / "figure16_w_group_sensitivity.csv"
    rows = []
    mincut = RESULTS_BASE / "MinCut"
    if mincut.exists():
        for sched_dir in sorted(mincut.iterdir()):
            m = SWEEP_RE.match(sched_dir.name)
            if not m or not sched_dir.is_dir():
                continue
            variant, axis, value = m.group(1), m.group(2), int(m.group(3))
            for run_dir in sorted(sched_dir.iterdir()):
                rm = RUN_RE.match(run_dir.name)
                if not rm or not run_dir.is_dir():
                    continue
                d = _load_results(run_dir)
                if d is None:
                    continue
                rows.append({
                    "variant": variant,
                    "axis": "w" if axis == "bw" else "G",
                    "value": value,
                    "bench": rm.group(1),
                    "archdir": rm.group(2),
                    "teff": f"{compute_teff(d):.2f}",
                    "total_execution_time_s": d.get("total_execution_time", ""),
                })
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "axis", "value", "bench",
                                          "archdir", "teff",
                                          "total_execution_time_s"])
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["axis"], r["variant"],
                                             r["value"], r["bench"])):
            w.writerow(r)
    if rows:
        print(f"wrote {csv_path} ({len(rows)} sweep runs)")
    else:
        print(f"[stub] {csv_path} — no sweep runs found under "
              f"{mincut}/(QuComm|IRIS)-(bw|lh)*/. "
              f"Run `bash scripts/fig_16.sh` first (see its runtime warning).")


if __name__ == "__main__":
    main()
