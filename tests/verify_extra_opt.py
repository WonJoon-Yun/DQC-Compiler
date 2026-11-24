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
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set, Tuple

AE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = AE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from analysis.schedule_locations import initial_locations, pipeline_rows, read_schedule, validate_channels, validate_locations
from router.optim.early_execution import (  # noqa: E402
    apply_deltas, is_move_row, qucomm_parallel_schedule,
    row_channel_deltas, row_used_qubits,
)

Pos = Tuple[int, int]
Edge = Tuple[Pos, Pos]
Row = Dict[str, Any]

_LINK_CAP_BY_ARCH = {
    "F120": 5, "F180": 5, "F240": 5,
    "F500": 18, "F800": 18, "F1100": 18,
}


def parse_link_cap(arch: str) -> int:
    if arch in _LINK_CAP_BY_ARCH:
        return _LINK_CAP_BY_ARCH[arch]
    m = re.search(r"C(\d+)", arch)
    return int(m.group(1)) if m else 5


def verify_pipeline(pipeline, init_ch, min_v, max_v, link_cap):
    violations: List[str] = []
    rows_by_time: Dict[int, List[Row]] = defaultdict(list)
    for r in pipeline:
        rows_by_time[r["Time"]].append(r)

    for t in sorted(rows_by_time):
        seen: Set[int] = set()
        for r in rows_by_time[t]:
            for q in row_used_qubits(r):
                if q in seen:
                    violations.append(f"(a) qubit-collision@{t}: q{q}")
                seen.add(q)

    last_seen: Dict[int, int] = {}
    for r in sorted(pipeline, key=lambda x: x["Time"]):
        t = r["Time"]
        for q in row_used_qubits(r):
            if q in last_seen and last_seen[q] > t:
                violations.append(f"(b) qubit-order: q{q} {last_seen[q]} > {t}")
            last_seen[q] = max(last_seen.get(q, t), t)

    channel = dict(init_ch)
    cap_dir = max_v // 2
    for t in sorted(rows_by_time):
        dir_count: Dict[Edge, int] = defaultdict(int)
        touched: Set[Edge] = set()
        for r in rows_by_time[t]:
            deltas = row_channel_deltas(r)
            for e, dv in deltas:
                if dv > 0:
                    dir_count[e] += 1
                touched.add(e)
            apply_deltas(channel, deltas)
        for e, cnt in dir_count.items():
            if cnt > cap_dir:
                violations.append(f"(d) edge-cap@{t}: {e} {cnt}>{cap_dir}")
        for e in touched:
            v = channel.get(e, 0)
            if v < min_v or v > max_v:
                violations.append(f"(c) cap@{t}: {e}={v} out-of-bounds")

    for t in sorted(rows_by_time):
        link_count: Dict[FrozenSet[Pos], int] = defaultdict(int)
        for r in rows_by_time[t]:
            if r["CNOT"] or not is_move_row(r):
                continue
            if r["SPos"] != r["SNextPos"]:
                link = frozenset({r["SPos"], r["SNextPos"]})
            elif r["TPos"] != r["TNextPos"]:
                link = frozenset({r["TPos"], r["TNextPos"]})
            else:
                continue
            link_count[link] += 1
        for link, cnt in link_count.items():
            if cnt > link_cap:
                violations.append(f"(e) link-cap@{t}: {sorted(link)} {cnt}>{link_cap}")

    return violations


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
        stage = "emitted"
        try:
            schedule = read_schedule(sched)
            initial = initial_locations(schedule)
            pipe, init_ch = pipeline_rows(schedule.pop("ops"))
            validate_locations(pipe, initial, original_times=True)
            validate_channels(pipe, schedule, original_times=True)
            res, viols = pipe, []
            if variant == "IRIS":
                stage = "postprocessed"
                res = qucomm_parallel_schedule(
                    pipe, init_ch, min_comm_value=args.min_comm, max_comm_value=args.max_comm,
                    link_epr_capacity=link_cap, debug=False,
                )
                validate_locations(res, initial)
                validate_channels(res, schedule)
                viols = verify_pipeline(res, init_ch, args.min_comm, args.max_comm, link_cap)
        except Exception as exc:
            print(f"  FAIL {label} ({stage}): {type(exc).__name__}: {exc}")
            fail += 1
            if args.stop_on_fail:
                return 1
            continue
        if viols:
            print(f"  FAIL {label} ({len(res)} ops): {len(viols)} violations")
            for v in viols[:5]:
                print(f"      - {v}")
            fail += 1
            if args.stop_on_fail:
                return 1
        else:
            print(f"  OK   {label} ({len(res)} ops, link_cap={link_cap})")
            ok += 1

    print(f"\nSUMMARY: {ok} OK, {fail} FAIL (out of {ok + fail})")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
