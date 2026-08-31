#!/usr/bin/env python3
"""Walk results/<Mapping>/<Scheduling>/<bench>-<archdir>/ (the IRIS-dataset
layout) and emit one summary CSV row per (variant, bench, arch, mapper).

Usage:
    python scripts/extract_results.py --root results/_full --out results/_full/summary.csv

The script is variant-aware: for IRIS(-opt1) runs it also picks up
extra_opt.json (written by apply_extra_opt.py) and reports the post-hoc
latency.

Columns:
    variant, bench, arch, mapper,
    teff, total_execution_time_s, compile_time_total_s,
    teff_extra_opt, wall_time_ms_extra,
    result_path, schedule_path, extra_opt_path
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

# dataset dir names -> artifact names
DS2VARIANT = {"QuComm": "QuComm", "IRIS-noEES": "IRIS-opt0", "IRIS": "IRIS-opt1"}
DS2MAPPER = {"MinCut": "ILP", "GCP-E": "GCP-ILP", "sOEE": "OEE-ILP", "WBCP": "WBCP"}
ARCH_BY_DIR = {"S40C5-2x2": "F120", "S42C5-2x3": "F180", "S40C5-3x3": "F240",
               "S180C18-2x2": "F500", "S180C18-2x3": "F800", "S180C18-3x3": "F1100"}
ARCHDIR_RE = re.compile(r"^(.*)-(S\d+C\d+-\d+x\d+)$")
VARIANT_ORDER = {"QuComm": 0, "IRIS-opt0": 1, "IRIS-opt1": 2}

# Paper Eq.(4): T_eff = N_RELOCATE + alpha * N_Re-CNOT, with alpha=1.77.
ALPHA_RECNOT = 1.77


def _first(paths):
    return next(iter(paths), None)


def _effective_teleportation_count(d: dict) -> int:
    n_relocate = int(d.get("num_state_teleportations", 0))
    n_recnot = int(d.get("num_gate_teleportations", 0))
    return int(round(n_relocate + ALPHA_RECNOT * n_recnot))


def _read_results_json(p: Path) -> dict:
    d = json.loads(p.read_text())
    compile_total = d.get("compile_time_total")
    if compile_total is None:
        compile_total = sum([
            float(d.get("compile_time_mapper") or 0),
            float(d.get("compile_time_router") or 0),
            float(d.get("compile_time_circuit_rewriting") or 0),
            float(d.get("compile_time_block_updating") or 0),
            float(d.get("compile_time_communication_fusion") or 0),
            float(d.get("compile_time_for_block_scheduling") or 0),
            float(d.get("compile_time_for_early_execution") or 0),
        ])
    return {
        "teff": _effective_teleportation_count(d),
        "total_execution_time_s": float(d.get("total_execution_time", 0.0)),
        "compile_time_total_s": float(compile_total or 0),
    }


def scan(root: Path):
    """Yield (variant, mapper, arch, bench, run_dir, result_path, schedule_path)."""
    if not root.exists():
        return
    for m_dir in sorted(root.iterdir()):
        if not m_dir.is_dir() or m_dir.name not in DS2MAPPER:
            continue
        for s_dir in sorted(m_dir.iterdir()):
            if not s_dir.is_dir() or s_dir.name not in DS2VARIANT:
                continue
            for run_dir in sorted(s_dir.iterdir()):
                if not run_dir.is_dir():
                    continue
                m = ARCHDIR_RE.match(run_dir.name)
                if not m:
                    continue
                bench, archdir = m.groups()
                arch = ARCH_BY_DIR.get(archdir, archdir)
                res = _first(sorted(run_dir.glob("results*.json")))
                sched = _first(sorted(run_dir.glob("[Ss]chedule*.json")))
                yield (DS2VARIANT[s_dir.name], DS2MAPPER[m_dir.name], arch, bench,
                       run_dir, res, sched)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results", type=Path,
                    help="Results root directory (IRIS-dataset layout)")
    ap.add_argument("--out", default="results/summary.csv", type=Path,
                    help="Output CSV path")
    args = ap.parse_args()

    rows = []
    for variant, mapper, arch, bench, run_dir, res, sched in scan(args.root):
        row = {"variant": variant, "bench": bench, "arch": arch,
               "mapper": mapper, "result_path": str(res) if res else "",
               "schedule_path": str(sched) if sched else "",
               "teff": "", "total_execution_time_s": "",
               "compile_time_total_s": "",
               "teff_extra_opt": "", "wall_time_ms_extra": "",
               "extra_opt_path": ""}
        if res:
            row.update(_read_results_json(res))
        eo_path = run_dir / "extra_opt.json"
        if variant == "IRIS-opt1" and eo_path.exists():
            eo = json.loads(eo_path.read_text())
            row["teff_extra_opt"] = eo.get("teff_extra_opt", "")
            row["wall_time_ms_extra"] = eo.get("wall_time_ms_extra", "")
            row["extra_opt_path"] = str(eo_path)
        rows.append(row)
    rows.sort(key=lambda r: (VARIANT_ORDER.get(r["variant"], 9), r["arch"],
                             r["mapper"], r["bench"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["variant", "bench", "arch", "mapper", "teff",
            "total_execution_time_s", "compile_time_total_s",
            "teff_extra_opt", "wall_time_ms_extra",
            "result_path", "schedule_path", "extra_opt_path"]
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {args.out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
