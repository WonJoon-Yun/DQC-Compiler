#!/usr/bin/env python3
"""§3.1 Table 1 — Average CNOTs, blocks, local-only blocks, and EPR releases
between two consecutive RELOCATEs involving a qubit, on a 3x3 DQC with
240-qubit programs (QAOA-FC, QFT, QV, Shor, VQE).

Runs the paper's interval analyzer (_motivation_relocate_distance.py) on the
QuComm schedules. The run files are staged into the directory layout the
analyzer expects; gzipped dataset files are decompressed on the fly.

Paper columns, from the analyzer's per-benchmark summary row:
  CNOTs        = mean CNOTs strictly between the paired RELOCATEs
  Blocks       = mean local blocks + mean non-local blocks (each rounded to
                 one decimal first, following the paper's derivation)
  Local-Only   = mean local-only blocks (blocks with zero RELOCATEs)
  EPR releases = releases per non-local block (rounded to four decimals)
                 x mean non-local blocks per interval (rounded to one
                 decimal), following the paper's derivation from the
                 displayed intermediate values

Output: output/section3/table1_relocate_intervals.csv
"""
from __future__ import annotations

import csv
import gzip
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import output_dir, python_env, result_json, schedule_json

BENCHMARKS = ["qaoa_fc", "qft", "qv", "shor", "vqe"]
DISPLAY = {"qaoa_fc": "QAOA-FC", "qft": "QFT", "qv": "QV", "shor": "Shor", "vqe": "VQE"}
ARCH = "F240"
ARCH_DIR = "S40C5-3x3"
N_QUBITS = 240
MAPPER = "ILP"
VARIANT = "QuComm"
ANALYZER = Path(__file__).with_name("_motivation_relocate_distance.py")


def _stage(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".gz":
        with gzip.open(src, "rb") as fin, dst.open("wb") as fout:
            shutil.copyfileobj(fin, fout)
    else:
        shutil.copy(src, dst)


def main() -> None:
    out = output_dir("section3")
    csv_path = out / "table1_relocate_intervals.csv"
    rows = [["benchmark", "CNOTs", "Blocks", "Local-Only", "EPR releases"]]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "tree"
        staged = False
        for fam in BENCHMARKS:
            bench = f"{fam}_n{N_QUBITS}"
            sched = schedule_json(VARIANT, ARCH, MAPPER, bench)
            res = result_json(VARIANT, ARCH, MAPPER, bench)
            if sched is None or res is None:
                continue
            leaf = root / VARIANT / "oee_on_p5_t0p0" / bench / MAPPER / "IRIS4" / ARCH_DIR
            _stage(sched, leaf / "Schedule-1.json")
            _stage(res, leaf / "results-1.json")
            staged = True

        summary: dict[str, dict] = {}
        if staged:
            outdir = Path(td) / "out"
            subprocess.run(
                [python_env(), str(ANALYZER),
                 "--results-root", str(root), "--output-dir", str(outdir),
                 "--qubit-counts", str(N_QUBITS)],
                check=True)
            with (outdir / "summary.csv").open() as fh:
                for r in csv.DictReader(fh):
                    summary[r["benchmark"]] = r

        for fam in BENCHMARKS:
            r = summary.get(f"{fam}_n{N_QUBITS}")
            if not r or not r.get("mean"):
                rows.append([DISPLAY[fam], "", "", "", ""])
                continue
            cnots = float(r["mean"])
            local_b = float(r["mean_local_blocks_between"])
            nonlocal_b = float(r["mean_nonlocal_blocks_between"])
            blocks = round(local_b, 1) + round(nonlocal_b, 1)
            releases = float(r["num_channel_releases_total"])
            total_nl = float(r["num_blocks_nonlocal"]) or 1.0
            epr = Decimal(str(round(releases / total_nl, 4))) \
                * Decimal(str(round(nonlocal_b, 1)))
            epr_s = str(epr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            rows.append([DISPLAY[fam], f"{cnots:.1f}", f"{blocks:.1f}",
                         f"{local_b:.1f}", epr_s])

    with csv_path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    print(f"wrote {csv_path}")


if __name__ == "__main__":
    main()
