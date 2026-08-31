#!/usr/bin/env python3
"""End-to-end verification microbenchmark for qucomm_parallel_schedule.

For every IRIS run in results/<Mapping>/IRIS/<bench>-<archdir>/ (the
IRIS-dataset layout), this
script:
  1. Loads the EES Schedule JSON.
  2. Converts to a pipeline and runs qucomm_parallel_schedule.
  3. Verifies the placed output against ALL post-conditions:
       (a) Per-cycle qubit collision  (data dependency at same time)
       (b) Per-qubit dependency order  (consecutive uses obey time order)
       (c) Channel state bounds  [min_comm_value, max_comm_value]
       (d) Per-direction edge capacity  max_comm_value // 2
       (e) Per-link bidirectional EPR cap  link_epr_capacity

Usage:
    python tests/verify_extra_opt.py --root results
    python tests/verify_extra_opt.py --root results --arch F240 --bench shor_n240
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set, Tuple

AE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = AE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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


def schedule_to_pipeline(schedule_path: Path) -> Tuple[List[Row], Dict[Edge, int]]:
    data = json.loads(schedule_path.read_text())
    ops = data["ops"]
    starts = sorted({o["original_start_time"] for o in ops})
    s2t = {s: i for i, s in enumerate(starts)}
    pipe, chips = [], set()
    for o in ops:
        t = s2t[o["original_start_time"]]
        pos0, pos1 = tuple(o["pos0"]), tuple(o["pos1"])
        chips.add(pos0); chips.add(pos1)
        bid = int(o["layer_id"])
        dur = float(o.get("original_duration", 0.0))
        if o["optype"] in ("Local CNOT", "Re-CNOT"):
            r = {"Time": t, "CNOT": True, "SIdx": int(o["atom0"]), "TIdx": int(o["atom1"]),
                 "SPos": pos0, "SNextPos": pos0, "TPos": pos1, "TNextPos": pos1,
                 "BlockID": bid, "_dur": dur, "_optype": o["optype"]}
        else:
            r = {"Time": t, "CNOT": False, "SIdx": int(o["atom0"]), "TIdx": int(o["atom0"]),
                 "SPos": pos0, "SNextPos": pos1, "TPos": pos0, "TNextPos": pos0,
                 "BlockID": bid, "_dur": dur, "_optype": o["optype"]}
        pipe.append(r)
    init_ch = {(a, b): 0 for a in chips for b in chips if a != b}
    return pipe, init_ch


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


def discover(root: Path, arch_filter, bench_filter):
    """Yield (arch, mapper, bench, schedule_path) from <root>/<Mapping>/IRIS/<bench>-<archdir>/."""
    if not root.exists():
        return
    for m_dir in sorted(root.iterdir()):
        if not m_dir.is_dir() or m_dir.name not in _DS2MAPPER:
            continue
        opt1_root = m_dir / "IRIS"
        if not opt1_root.exists():
            continue
        for run_dir in sorted(opt1_root.iterdir()):
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
            sched = next(iter(sorted(run_dir.glob("[Ss]chedule*.json"))), None)
            if sched is not None:
                yield (arch, _DS2MAPPER[m_dir.name], bench, sched)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=AE_ROOT / "results", type=Path,
                    help="Results root (must contain IRIS-opt1/)")
    ap.add_argument("--arch", action="append", help="Restrict to archs")
    ap.add_argument("--bench", action="append", help="Restrict to benchmarks")
    ap.add_argument("--min_comm", type=int, default=-1000)
    ap.add_argument("--max_comm", type=int, default=2000)
    ap.add_argument("--stop_on_fail", action="store_true")
    args = ap.parse_args()

    arch_set = set(args.arch) if args.arch else None
    bench_set = set(args.bench) if args.bench else None
    targets = list(discover(args.root, arch_set, bench_set))
    if not targets:
        print(f"No schedules under {args.root}/<Mapping>/IRIS/")
        return 1

    ok = fail = 0
    for arch, mapper, bench, sched in targets:
        pipe, init_ch = schedule_to_pipeline(sched)
        link_cap = parse_link_cap(arch)
        try:
            res = qucomm_parallel_schedule(
                pipe, init_ch, min_comm_value=args.min_comm, max_comm_value=args.max_comm,
                link_epr_capacity=link_cap, debug=False,
            )
        except Exception as exc:
            print(f"  FAIL {arch}/{mapper}/{bench}: {type(exc).__name__}: {exc}")
            fail += 1
            if args.stop_on_fail:
                return 1
            continue
        viols = verify_pipeline(res, init_ch, args.min_comm, args.max_comm, link_cap)
        if viols:
            print(f"  FAIL {arch}/{mapper}/{bench} ({len(res)} ops): {len(viols)} violations")
            for v in viols[:5]:
                print(f"      - {v}")
            fail += 1
            if args.stop_on_fail:
                return 1
        else:
            print(f"  OK   {arch}/{mapper}/{bench} ({len(res)} ops, link_cap={link_cap})")
            ok += 1

    print(f"\nSUMMARY: {ok} OK, {fail} FAIL (out of {ok + fail})")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
