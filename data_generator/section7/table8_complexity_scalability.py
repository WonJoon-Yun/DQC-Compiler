#!/usr/bin/env python3
"""§7 Table 8 — Scalability of compile time, runtime, and memory across
{500q, 800q, 1100q} on {F500 (2x2), F800 (2x3), F1100 (3x3)}.

Reads `results/_full/<variant>/<arch>/ILP/qaoa_3reg_n<N>/...` and reports
compile_time_total, total_execution_time, peak memory (if recorded).

Requires the large-scale sweep (n=500/800/1100). Generate via
`python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset` then
`scripts/table_8.sh`.

Output: output/section7/table8_complexity_scalability.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import VARIANTS_3, load_json, output_dir, result_json

ARCH_CONFIGS = [("F500", 500), ("F800", 800), ("F1100", 1100)]
MAPPER = "ILP"
FAMILY = "qaoa_3reg"


def main() -> None:
    out = output_dir("section7")
    csv_path = out / "table8_complexity_scalability.csv"
    found = 0
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arch", "n_qubits", "variant", "compile_time_total_s",
                    "total_execution_time_s", "peak_memory_mb"])
        for (arch, n) in ARCH_CONFIGS:
            bench = f"{FAMILY}_n{n}"
            for v in VARIANTS_3:
                p = result_json(v, arch, MAPPER, bench)
                if p is None:
                    w.writerow([arch, n, v, "", "", ""])
                    continue
                d = load_json(p)
                found += 1
                compile_total = (
                    float(d.get("compile_time_total", 0) or 0)
                    or sum(float(d.get(k, 0) or 0) for k in (
                        "compile_time_mapper", "compile_time_router",
                        "compile_time_circuit_rewriting",
                        "compile_time_block_updating",
                        "compile_time_communication_fusion",
                        "compile_time_for_block_scheduling",
                        "compile_time_for_early_execution",
                    ))
                )
                mem = d.get("peak_traced_memory_mb") or d.get("peak_memory_mb") or ""
                w.writerow([arch, n, v, f"{compile_total:.3f}",
                            f"{float(d.get('total_execution_time', 0)):.6f}",
                            mem])
    if found == 0:
        print(f"[stub] {csv_path} — no large-scale data; run table_8.sh first")
    else:
        print(f"wrote {csv_path} ({found} rows)")


if __name__ == "__main__":
    main()
