#!/usr/bin/env python3
"""Replay raw atom locations for each requested variant in the IRIS-dataset layout.

Replay directional reservations for all variants at actual start and end times.
For IRIS, also run qucomm_parallel_schedule and check the resulting locations,
per-cycle atom usage, channel bounds, directional capacity and link EPR cap.

Usage:
    python tests/verify_extra_opt.py --root results
    python tests/verify_extra_opt.py --root results --arch F240 --bench shor_n240
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

AE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = AE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from analysis.schedule_postprocess import parse_link_cap, replay_schedule


_DS2MAPPER = {"MinCut": "ILP", "GCP-E": "GCP-ILP", "sOEE": "OEE-ILP", "WBCP": "WBCP"}
_ARCH_BY_DIR = {"S40C5-2x2": "F120", "S42C5-2x3": "F180", "S40C5-3x3": "F240",
                "S180C18-2x2": "F500", "S180C18-2x3": "F800", "S180C18-3x3": "F1100"}
_ARCHDIR_RE = re.compile(r"^(.*)-(S\d+C\d+-\d+x\d+)$")


def discover(root: Path, arch_filter, bench_filter, variant="IRIS"):
    """Find schedules for one compiler variant in the dataset or results layout."""
    if not root.exists():
        return
    for m_dir in sorted(root.iterdir()):
        if not m_dir.is_dir() or m_dir.name not in _DS2MAPPER:
            continue
        variant_root = m_dir / variant
        if not variant_root.exists():
            continue
        for run_dir in sorted(variant_root.iterdir()):
            if not run_dir.is_dir():
                continue
            m = _ARCHDIR_RE.match(run_dir.name)
            if not m:
                continue
            bench, archdir = m.groups()
            arch = _ARCH_BY_DIR.get(archdir, archdir)
            if arch_filter and arch not in arch_filter and archdir not in arch_filter:
                continue
            if bench_filter and bench not in bench_filter:
                continue
            sched = next((p for pattern in ("[Ss]chedule*.json", "[Ss]chedule*.json.gz")
                          for p in sorted(run_dir.glob(pattern))), None)
            if sched is not None:
                yield (arch, _DS2MAPPER[m_dir.name], bench, sched)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=AE_ROOT / "results", type=Path,
                    help="Results or dataset root containing mapping-method directories")
    ap.add_argument("--variant", action="append", choices=("QuComm", "IRIS-noEES", "IRIS"),
                    help="Check the raw schedule for this variant, plus post-processing for IRIS (default)")
    ap.add_argument("--arch", action="append", help="Restrict to archs")
    ap.add_argument("--bench", action="append", help="Restrict to benchmarks")
    ap.add_argument("--min_comm", type=int, default=-1000)
    ap.add_argument("--max_comm", type=int, default=2000)
    ap.add_argument("--stop_on_fail", action="store_true")
    args = ap.parse_args()

    arch_set = set(args.arch) if args.arch else None
    bench_set = set(args.bench) if args.bench else None
    variants = list(dict.fromkeys(args.variant or ["IRIS"]))
    ok = fail = 0
    targets = []
    for variant in variants:
        found = list(discover(args.root, arch_set, bench_set, variant))
        if not found:
            print(f"No schedules for {variant} under {args.root} with the selected filters")
            fail += 1
            if args.stop_on_fail:
                return 1
        targets.extend((variant, *target) for target in found)
    for variant, arch, mapper, bench, sched in targets:
        label = f"{variant}/{arch}/{mapper}/{bench}"
        link_cap = parse_link_cap(arch)
        try:
            _, rows, metadata = replay_schedule(
                sched, link_cap if variant == "IRIS" else None,
                min_comm_value=args.min_comm, max_comm_value=args.max_comm,
            )
        except Exception as exc:
            print(f"  FAIL {label}: {exc}")
            fail += 1
            if args.stop_on_fail:
                return 1
            continue
        print(f"  OK   {label} ({len(rows)} ops, link_cap={link_cap})")
        if metadata["candidate_rejection"]:
            print(f"       retained original cycles: {metadata['candidate_rejection']}")
        ok += 1

    print(f"\nSUMMARY: {ok} OK, {fail} FAIL (out of {ok + fail})")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
