#!/usr/bin/env python3
"""Summarize result JSONs into a per-benchmark per-variant markdown table."""
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict

VARIANTS = ["QuComm", "IRIS-opt0", "IRIS-opt1"]

# results use the IRIS-dataset layout: <Mapping>/<Scheduling>/<bench>-<archdir>/
DS2VARIANT = {"QuComm": "QuComm", "IRIS-noEES": "IRIS-opt0", "IRIS": "IRIS-opt1"}
DS2MAPPER = {"MinCut": "ILP", "GCP-E": "GCP-ILP", "sOEE": "OEE-ILP", "WBCP": "WBCP"}
ARCH_BY_DIR = {"S40C5-2x2": "F120", "S42C5-2x3": "F180", "S40C5-3x3": "F240",
               "S180C18-2x2": "F500", "S180C18-2x3": "F800", "S180C18-3x3": "F1100"}
import re as _re
ARCHDIR_RE = _re.compile(r"^(.*)-(S\d+C\d+-\d+x\d+)$")

# Paper Eq.(4): T_eff = N_RELOCATE + 1.77 * N_Re-CNOT
# N_RELOCATE == num_state_teleportations, N_Re-CNOT == num_gate_teleportations.
ALPHA_RECNOT = 1.77


def teff_eq4(d):
    n_relocate = int(d.get("num_state_teleportations", 0))
    n_recnot = int(d.get("num_gate_teleportations", 0))
    return int(round(n_relocate + ALPHA_RECNOT * n_recnot))


def load_all(root, arch_filter, mapper_filter):
    rows = {}
    for jp in root.rglob("results*.json"):
        parts = jp.relative_to(root).parts
        if len(parts) != 4:
            continue
        m_dir, s_dir, run_dir = parts[0], parts[1], parts[2]
        if m_dir not in DS2MAPPER or s_dir not in DS2VARIANT:
            continue
        m = ARCHDIR_RE.match(run_dir)
        if not m:
            continue
        bench, archdir = m.groups()
        arch = ARCH_BY_DIR.get(archdir, archdir)
        mapper = DS2MAPPER[m_dir]
        if arch_filter and arch != arch_filter:
            continue
        if mapper_filter and mapper != mapper_filter:
            continue
        try:
            data = json.loads(jp.read_text())
        except Exception:
            continue
        rows[(DS2VARIANT[s_dir], arch, mapper, bench)] = data
    return rows


def emit(rows, out_fh):
    groups = defaultdict(dict)
    for (v, a, m, b), d in rows.items():
        groups[(a, m, b)][v] = d
    for (a, m, b), vmap in sorted(groups.items()):
        out_fh.write(f"\n## {b} | {a} | {m}\n\n")
        out_fh.write("| Variant | State Tele | T_eff (Eq.4) | Exec time (s) |\n")
        out_fh.write("|---------|----------:|------------:|--------------:|\n")
        for v in VARIANTS:
            r = vmap.get(v)
            if not r:
                out_fh.write(f"| {v} | - | - | - |\n")
                continue
            st = int(r.get("num_state_teleportations", 0))
            ec = teff_eq4(r)
            et = float(r.get("total_execution_time", 0))
            out_fh.write(f"| {v} | {st} | {ec} | {et:.4f} |\n")
    totals = {v: {"st": 0, "ec": 0, "et": 0.0, "n": 0} for v in VARIANTS}
    for vmap in groups.values():
        for v in VARIANTS:
            if v not in vmap:
                continue
            r = vmap[v]
            totals[v]["st"] += int(r.get("num_state_teleportations", 0))
            totals[v]["ec"] += teff_eq4(r)
            totals[v]["et"] += float(r.get("total_execution_time", 0))
            totals[v]["n"] += 1
    out_fh.write(f"\n## Totals across {len(groups)} (arch, mapper, bench) tuples\n\n")
    out_fh.write("| Variant | N | State Tele | T_eff (Eq.4) | Exec time (s) |\n")
    out_fh.write("|---------|--:|---:|---:|---:|\n")
    for v in VARIANTS:
        t = totals[v]
        out_fh.write(f"| {v} | {t['n']} | {t['st']} | {t['ec']} | {t['et']:.4f} |\n")
    qc, o1 = totals["QuComm"], totals["IRIS-opt1"]
    if qc["et"] > 0 and o1["n"] == qc["n"]:
        ratio = (1 - o1["et"] / qc["et"]) * 100
        out_fh.write(f"\n**IRIS-opt1 vs QuComm execution-time reduction: {ratio:.1f}%**\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="results/_full")
    ap.add_argument("--arch", default=None)
    ap.add_argument("--mapper", default=None)
    ap.add_argument("--out", default=None, help="Output markdown file (default stdout)")
    args = ap.parse_args()
    root = Path(args.root)
    if not root.exists():
        sys.exit(f"Root not found: {root}")
    rows = load_all(root, args.arch, args.mapper)
    if not rows:
        sys.exit("No results found.")
    if args.out:
        with open(args.out, "w") as fh:
            emit(rows, fh)
        sys.stderr.write(f"Wrote {args.out}\n")
    else:
        emit(rows, sys.stdout)


if __name__ == "__main__":
    main()
