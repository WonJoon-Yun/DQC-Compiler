#!/usr/bin/env python3
"""§6.1 Table 6 — Main results on F180 (2x3 DQC, n=180) and F240 (3x3 DQC,
n=240) with the Min-Cut (ILP) mapper.

For each (arch × bench × variant), reports:
    T_eff (num_effective_cnots)
    L     (total_execution_time)

Reads from results/_full/<variant>/<arch>/ILP/<bench>/...

Outputs:
    output/section6/table6_main_2x3_3x3.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import BENCH_FAMILIES, VARIANTS_3, compute_teff, load_json, output_dir, result_json, extra_opt_json

MAPPER = "ILP"
ARCH_CONFIGS = [("F180", 180), ("F240", 240)]


def _row(variant: str, arch: str, bench: str) -> dict:
    p = result_json(variant, arch, MAPPER, bench)
    if p is None:
        return {"teff": None, "latency": None}
    d = load_json(p)
    teff = compute_teff(d)
    latency = float(d.get("total_execution_time", 0) or 0)
    if variant == "IRIS-opt1":
        ex = extra_opt_json(arch, MAPPER, bench)
        if ex is not None:
            ed = load_json(ex)
            lat = ed.get("wall_time_ms_extra") or ed.get("l_extra_opt")
            if lat is not None:
                latency = float(lat) / 1000.0 if ed.get("wall_time_ms_extra") else float(lat)
    return {"teff": teff, "latency": latency}


def main() -> None:
    out = output_dir("section6")
    csv_path = out / "table6_main_2x3_3x3.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arch", "bench", "variant", "T_eff", "L_seconds"])
        for (arch, n) in ARCH_CONFIGS:
            for fam in BENCH_FAMILIES:
                bench = f"{fam}_n{n}"
                for variant in VARIANTS_3:
                    r = _row(variant, arch, bench)
                    w.writerow([arch, bench, variant,
                                f"{r['teff']:.2f}" if r["teff"] is not None else "",
                                f"{r['latency']:.6f}" if r["latency"] is not None else ""])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
