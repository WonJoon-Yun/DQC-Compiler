#!/usr/bin/env python3
"""Appendix E / Table 9 — Latency impact of EES across 2x2, 2x3, 3x3 DQCs.

For each (arch, bench), compares:
    L_opt0 = IRIS-opt0 total_execution_time (no EES)
    L_opt1 = IRIS-opt1 extra-opt latency (with EES + post-hoc replay)
    speedup = L_opt0 / L_opt1

Reads:
    results/_full/IRIS-opt0/<arch>/ILP/<bench>/.../results*.json
    results/_full/IRIS-opt1/<arch>/ILP/<bench>/extra_opt.json

Output: output/appendix_e/table9_ees_latency_impact.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import BENCH_FAMILIES, extra_opt_json, load_json, output_dir, result_json

MAPPER = "ILP"
ARCH_CONFIGS = [("F120", 120), ("F180", 180), ("F240", 240)]


def main() -> None:
    out = output_dir("appendix_e")
    csv_path = out / "table9_ees_latency_impact.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arch", "bench", "L_opt0_seconds", "L_opt1_seconds", "speedup"])
        for (arch, n) in ARCH_CONFIGS:
            for fam in BENCH_FAMILIES:
                bench = f"{fam}_n{n}"
                opt0_p = result_json("IRIS-opt0", arch, MAPPER, bench)
                opt1_extra = extra_opt_json(arch, MAPPER, bench)
                L0 = float(load_json(opt0_p).get("total_execution_time", 0)) if opt0_p else None
                L1 = None
                if opt1_extra is not None:
                    ed = load_json(opt1_extra)
                    if ed.get("wall_time_ms_extra") is not None:
                        L1 = float(ed["wall_time_ms_extra"]) / 1000.0
                    elif ed.get("l_extra_opt") is not None:
                        L1 = float(ed["l_extra_opt"])
                speedup = (L0 / L1) if (L0 and L1) else None
                w.writerow([
                    arch, bench,
                    f"{L0:.6f}" if L0 is not None else "",
                    f"{L1:.6f}" if L1 is not None else "",
                    f"{speedup:.3f}" if speedup is not None else "",
                ])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
