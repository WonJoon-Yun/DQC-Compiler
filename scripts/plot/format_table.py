#!/usr/bin/env python3
"""Render a paper-style results table (markdown) from the summary CSV.

Usage:
    python scripts/plot/format_table.py --csv results/summary.csv \
        --archs F120 --mappers ILP,GCP-ILP,OEE-ILP,WBCP \
        --out figures/table_5.md
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

VARIANTS = ("QuComm", "IRIS-opt0", "IRIS-opt1")


def _f(x, default=None):
    try:
        return float(x)
    except (ValueError, TypeError):
        return default


def _load(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _bench_family(bench):
    # bv_n120 -> bv ; surface -> surface
    if "_n" in bench:
        return bench.split("_n", 1)[0]
    return bench


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--archs", required=True,
                    help="Comma-separated arch list (e.g. F120,F180,F240)")
    ap.add_argument("--mappers", required=True,
                    help="Comma-separated mapper list (e.g. ILP)")
    ap.add_argument("--benches", default=None,
                    help="Optional comma-separated bench-family filter")
    ap.add_argument("--columns", default="teff,runtime,compile",
                    help="Which metrics to show (teff,runtime,compile)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    archs = args.archs.split(",")
    mappers = args.mappers.split(",")
    bench_filter = set(args.benches.split(",")) if args.benches else None
    columns = args.columns.split(",")

    rows = _load(args.csv)

    # Index: (arch, mapper, bench, variant) -> row
    by_key = {}
    for r in rows:
        key = (r["arch"], r["mapper"], r["bench"], r["variant"])
        by_key[key] = r

    # Discover bench list
    benches = sorted({r["bench"] for r in rows
                      if r["arch"] in archs and r["mapper"] in mappers
                      and (not bench_filter or _bench_family(r["bench"]) in bench_filter)})

    lines = []
    lines.append(f"# Results table (archs={','.join(archs)}, mappers={','.join(mappers)})")
    lines.append("")
    for arch in archs:
        for mapper in mappers:
            lines.append(f"## arch={arch}, mapper={mapper}")
            hdr = ["bench"]
            for v in VARIANTS:
                for c in columns:
                    hdr.append(f"{v}.{c}")
            lines.append("| " + " | ".join(hdr) + " |")
            lines.append("|" + "|".join(["---"] * len(hdr)) + "|")
            for bench in benches:
                if not any((arch, mapper, bench, v) in by_key for v in VARIANTS):
                    continue
                cells = [bench]
                for v in VARIANTS:
                    r = by_key.get((arch, mapper, bench, v))
                    for c in columns:
                        if r is None:
                            cells.append("-")
                        elif c == "teff":
                            # T_eff (Eq.4) is invariant across IRIS variants; EES/extra-opt
                            # only reduces latency, not the teleportation count (paper Sec 6.1).
                            val = r.get("teff")
                            cells.append(f"{val}" if val not in (None, "") else "-")
                        elif c == "runtime":
                            if v == "IRIS-opt1" and r.get("wall_time_ms_extra"):
                                val = _f(r["wall_time_ms_extra"])
                                cells.append(f"{val:.2f} ms" if val is not None else "-")
                            else:
                                val = _f(r.get("total_execution_time_s"))
                                cells.append(f"{val * 1000:.2f} ms" if val is not None else "-")
                        elif c == "compile":
                            val = _f(r.get("compile_time_total_s"))
                            cells.append(f"{val:.1f} s" if val is not None else "-")
                        else:
                            cells.append("-")
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
