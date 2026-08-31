#!/usr/bin/env python3
"""§6.1 Table 5 — Mapper comparison on F120 (2x2 DQC, n=120).

Compares the 3 variants (QuComm, IRIS-opt0, IRIS-opt1) across 4 mappers
(ILP=Min-Cut, GCP-ILP, OEE-ILP, WBCP) for each of the 8 benchmarks.

Reports per (mapper × bench × variant):
    T_eff (num_effective_cnots)
    L     (total_execution_time)

Reads from results/_full/<variant>/F120/<mapper>/<bench>/...

Outputs:
    output/section6/table5_mapper_comparison_2x2.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import BENCH_FAMILIES, VARIANTS_3, compute_teff, load_json, output_dir, result_json, extra_opt_json

MAPPERS = ("ILP", "GCP-ILP", "OEE-ILP", "WBCP")
ARCH = "F120"
N_QUBITS = 120


def _row(variant: str, mapper: str, bench: str) -> dict:
    p = result_json(variant, ARCH, mapper, bench)
    if p is None:
        return {"teff": None, "latency": None}
    d = load_json(p)
    teff = compute_teff(d)
    latency = float(d.get("total_execution_time", 0) or 0)
    if variant == "IRIS-opt1":
        ex = extra_opt_json(ARCH, mapper, bench)
        if ex is not None:
            ed = load_json(ex)
            lat = ed.get("wall_time_ms_extra") or ed.get("l_extra_opt")
            if lat is not None:
                # convert ms → s if it's the wall_time_ms_extra field
                latency = float(lat) / 1000.0 if ed.get("wall_time_ms_extra") else float(lat)
    return {"teff": teff, "latency": latency}


def main() -> None:
    out = output_dir("section6")
    csv_path = out / "table5_mapper_comparison_2x2.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mapper", "bench", "variant", "T_eff", "L_seconds"])
        for mapper in MAPPERS:
            for fam in BENCH_FAMILIES:
                bench = f"{fam}_n{N_QUBITS}"
                for variant in VARIANTS_3:
                    r = _row(variant, mapper, bench)
                    w.writerow([mapper, bench, variant,
                                f"{r['teff']:.2f}" if r["teff"] is not None else "",
                                f"{r['latency']:.6f}" if r["latency"] is not None else ""])
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
