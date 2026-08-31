#!/usr/bin/env python3
"""§5.1 Table 3 — CNOT counts in benchmarks for 2x2 (n=120), 2x3 (n=180), and
3x3 (n=240) DQCs across the 8 benchmark families.

Reads `bench/<family>/<family>_n<N>.qasm` directly and counts 2-qubit gates
with the same accounting as the compiler front end (src/parser.py):
cx=1, rzz=2, cp=1, swap=3. The result equals the compiler's
`total_gate_count` for every benchmark.

Outputs:
    output/section5/table3_benchmark_counts.csv
    output/section5/table3_benchmark_counts.tex
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import bench_qasm, output_dir

DQC_COLS = [("2x2", 120), ("2x3", 180), ("3x3", 240)]
PAPER_ORDER = [
    ("BV", "bv"),
    ("QAOA-3reg", "qaoa_3reg"),
    ("QAOA-FC", "qaoa_fc"),
    ("QuGAN", "qugan"),
    ("Shor", "shor"),
    ("QFT", "qft"),
    ("VQE", "vqe"),
    ("QV", "qv"),
]

# Two-qubit gate accounting, identical to the compiler front end
# (src/parser.py): cx=1, rzz=2, cp=1, swap=3.
GATE_COST = {
    "cx": 1,
    "rzz": 2,
    "cp": 1,
    "swap": 3,
}
GATE_RE = re.compile(r"^\s*([a-zA-Z]+[a-zA-Z0-9]*)(?:\(|\s)")


def count_cnots(qasm: Path) -> int:
    total = 0
    for line in qasm.read_text().splitlines():
        m = GATE_RE.match(line)
        if m:
            total += GATE_COST.get(m.group(1).lower(), 0)
    return total


def main() -> None:
    out = output_dir("section5")
    rows = []
    for (display, family) in PAPER_ORDER:
        row = {"benchmark": display}
        for (col_label, n) in DQC_COLS:
            qasm = bench_qasm(family, n)
            row[col_label] = count_cnots(qasm) if qasm.exists() else None
        rows.append(row)

    csv_path = out / "table3_benchmark_counts.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Benchmark"] + [f"{label} ({n}q)" for (label, n) in DQC_COLS])
        for r in rows:
            w.writerow([r["benchmark"]] + [r[label] if r[label] is not None else "" for (label, _) in DQC_COLS])
    print(f"wrote {csv_path}")

    tex_path = out / "table3_benchmark_counts.tex"
    with tex_path.open("w") as f:
        f.write("\\begin{tabular}{l" + "r" * len(DQC_COLS) + "}\n\\hline\n")
        f.write("Benchmark & " + " & ".join(f"{label} ({n}q)" for (label, n) in DQC_COLS) + " \\\\ \\hline\n")
        for r in rows:
            f.write(f"{r['benchmark']} & " + " & ".join(str(r[label]) if r[label] is not None else "--" for (label, _) in DQC_COLS) + " \\\\\n")
        f.write("\\hline\n\\end{tabular}\n")
    print(f"wrote {tex_path}")


if __name__ == "__main__":
    main()
