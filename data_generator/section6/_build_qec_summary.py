#!/usr/bin/env python3
"""Build qec_codes_2x2_vs_mono_summary.md from per-(code, arch) result JSONs.

This is a re-creation of the original summary writer (which has been removed
from the repo). It scans the `qec_codes_2x2_vs_mono_<code>_<arch>` result
directories, extracts the latest IRIS-opt0-EEE/IRIS-opt0/QuComm result JSON
for each (code, arch), and renders the comparison markdown.

Latency model used to compute "LCT (ms)" — Logical Cycle Time for a full
d-round memory experiment:

    LCT = total_execution_time × 1000      (ms; already includes scheduler-
                                            level RELOCATE/CNOT durations)

This omits the per-round measurement+reset overhead (M+R) and the final
readout time, which the original writer added on top. Pass
`--t_meas_reset_ms_per_round` and `--t_final_meas_ms` to fold them back in.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

# (display_name, bench, dqc_arch_substr, mono_arch_substr, rounds_per_d, n, k, d)
CODES = [
    # display_name, bench_name, dqc_subdir_substr, mono_subdir_substr, n, k, d, rounds
    ("Surface d=7", "surface_code_n97", "surface_code_s33c4_2x2", "surface_code_mono_s100_1x1",
     97, 1, 7, 7),
    ("BB [[72,12,6]]", "bb_72_12_6_n144", "bb_72_12_6_s46c5_2x2", "bb_72_12_6_mono_s144_1x1",
     72, 12, 6, 6),
    ("HGP [[225,9,6]]", "hgp_225_9_6_n441", "hgp_225_9_6_s141c15_2x2", "hgp_225_9_6_mono_s444_1x1",
     225, 9, 6, 6),
    ("Color [[61,1,9]]", "color_61_1_9_n121", "color_61_1_9_s42c5_2x2", "color_61_1_9_mono_s128_1x1",
     61, 1, 9, 9),
]
STAGES = ["QuComm", "IRIS-opt0", "IRIS-opt0-EEE"]


def _find_result(results_base: Path, subdir_substr: str, stage: str) -> dict | None:
    pattern = str(results_base / f"*{subdir_substr}*/*/{stage}/oee_on_p5_t0p0/*/ILP/IRIS4/*/results*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None
    return json.loads(Path(matches[-1]).read_text())


def _row(res: dict | None, rounds: int, t_meas_reset_ms: float, t_final_meas_ms: float) -> dict:
    if res is None:
        return {}
    local_cz = int(res.get("num_local_cnots", 0))
    teleports = int(res.get("num_state_teleportations", res.get("num_relocations", 0)))
    lat_s = float(res.get("total_execution_time", 0.0))
    lct_ms = lat_s * 1000.0 + rounds * t_meas_reset_ms + t_final_meas_ms
    teff_ms = lct_ms / rounds if rounds > 0 else lct_ms
    # depth fields aren't directly in result JSON; use placeholders
    return {
        "local_cz": local_cz,
        "teleports": teleports,
        "lct_ms": lct_ms,
        "teff_ms": teff_ms,
    }


def _emit_code_section(fh, display: str, n: int, k: int, d: int, rounds: int, rows: dict):
    fh.write(f"\n## {display} (n={n}, k={k}, d={d}; {rounds} rounds)\n\n")
    fh.write("| Architecture | Method | Local CZ | Teleports | LCT (ms) | T_eff (ms) |\n")
    fh.write("|---|---|---:|---:|---:|---:|\n")
    for arch_label, stage in rows:
        r = rows[(arch_label, stage)]
        if not r:
            continue
        fh.write(f"| {arch_label} | {stage} | {r['local_cz']} | {r['teleports']} | "
                 f"{r['lct_ms']:.2f} | {r['teff_ms']:.2f} |\n")


def _emit_headline(fh, all_rows: dict):
    fh.write("\n## Headline: QuComm vs IRIS-opt0-EEE on 2x2 DQC\n\n")
    fh.write("| Code | Method | Teleports | LCT (ms) | T_eff (ms) "
             "| LCT (rel. to QuComm) | T_eff (rel. to QuComm) |\n")
    fh.write("|---|---|---:|---:|---:|---:|---:|\n")
    for display, rows in all_rows.items():
        qc = rows.get(("2x2 DQC", "QuComm"))
        ir = rows.get(("2x2 DQC", "IRIS-opt0-EEE"))
        if not qc or not ir:
            continue
        rel_lct = ir["lct_ms"] / qc["lct_ms"] if qc["lct_ms"] > 0 else float("nan")
        rel_teff = ir["teff_ms"] / qc["teff_ms"] if qc["teff_ms"] > 0 else float("nan")
        fh.write(f"| {display} | QuComm | {qc['teleports']} | {qc['lct_ms']:.2f} | "
                 f"{qc['teff_ms']:.2f} | 1.000× | 1.000× |\n")
        fh.write(f"| {display} | IRIS-opt0-EEE | {ir['teleports']} | {ir['lct_ms']:.2f} | "
                 f"{ir['teff_ms']:.2f} | {rel_lct:.3f}× | {rel_teff:.3f}× |\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--results-base", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--t_meas_reset_ms_per_round", type=float, default=0.0,
                   help="Per-round M+R overhead added to LCT (default 0).")
    p.add_argument("--t_final_meas_ms", type=float, default=0.0,
                   help="Final readout overhead added once (default 0).")
    args = p.parse_args()

    results_base = Path(args.results_base)
    if not results_base.exists():
        raise SystemExit(f"results-base not found: {results_base}")

    all_rows = {}
    for display, _, dqc_substr, mono_substr, n, k, d, rounds in CODES:
        rows = {}
        for arch_label, subdir in [("Mono", mono_substr), ("2x2 DQC", dqc_substr)]:
            for stage in STAGES:
                res = _find_result(results_base, subdir, stage)
                rows[(arch_label, stage)] = _row(
                    res, rounds, args.t_meas_reset_ms_per_round, args.t_final_meas_ms,
                )
        all_rows[display] = rows

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("# QEC code-family generalization on 2x2 DQC\n\n")
        fh.write("Generated by data_generator/section6/_build_qec_summary.py from "
                 "result JSONs in `qec_codes_2x2_vs_mono_*` directories.\n")
        for display, _, _, _, n, k, d, rounds in CODES:
            _emit_code_section(fh, display, n, k, d, rounds, all_rows[display])
        _emit_headline(fh, all_rows)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
