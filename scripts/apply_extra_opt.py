#!/usr/bin/env python3
"""Apply the QuComm post-hoc extra-optimization (block-level parallelization)
to an EES schedule JSON written by run.py --enable_ees.

Usage:
    python apply_extra_opt.py --schedule <path>/Schedule-*.json --arch F240 \
        --out <path>/extra_opt.json

Output JSON fields:
    teff_orig            -- original effective teleportation count (= ops)
    teff_extra_opt       -- after parallelization
    cycles_orig          -- number of distinct original time slots
    cycles_extra_opt     -- number of cycles after parallelization
    wall_time_ms_orig    -- sum of per-cycle max durations (original)
    wall_time_ms_extra   -- same metric on the extra-opt schedule
    link_epr_capacity    -- per-link EPR cap used for the optimizer
    violations           -- list of post-condition violations (empty on success)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

AE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = AE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from router.optim.early_execution import qucomm_parallel_schedule  # noqa: E402


_ARCH_LINK_CAP = {
    "F120": 5, "F180": 5, "F240": 5,
    "F500": 18, "F800": 18, "F1100": 18,
}


def parse_link_cap(arch: str) -> int:
    if arch in _ARCH_LINK_CAP:
        return _ARCH_LINK_CAP[arch]
    m = re.search(r"C(\d+)", arch)
    if m:
        return int(m.group(1))
    raise SystemExit(f"Cannot infer link_epr_capacity from arch: {arch}")


def schedule_to_pipeline(schedule_path: Path):
    if str(schedule_path).endswith(".gz"):
        import gzip
        data = json.loads(gzip.decompress(schedule_path.read_bytes()))
    else:
        data = json.loads(schedule_path.read_text())
    ops = data["ops"]
    starts = sorted({o["original_start_time"] for o in ops})
    s2t = {s: i for i, s in enumerate(starts)}
    pipe, chips = [], set()
    for o in ops:
        t = s2t[o["original_start_time"]]
        pos0 = tuple(o["pos0"])
        pos1 = tuple(o["pos1"])
        chips.add(pos0)
        chips.add(pos1)
        bid = int(o["layer_id"])
        dur = float(o.get("original_duration", 0.0))
        if o["optype"] in ("Local CNOT", "Re-CNOT"):
            r = {"Time": t, "CNOT": True,
                 "SIdx": int(o["atom0"]), "TIdx": int(o["atom1"]),
                 "SPos": pos0, "SNextPos": pos0, "TPos": pos1, "TNextPos": pos1,
                 "BlockID": bid, "_dur": dur, "_optype": o["optype"]}
        else:
            r = {"Time": t, "CNOT": False,
                 "SIdx": int(o["atom0"]), "TIdx": int(o["atom0"]),
                 "SPos": pos0, "SNextPos": pos1, "TPos": pos0, "TNextPos": pos0,
                 "BlockID": bid, "_dur": dur, "_optype": o["optype"]}
        pipe.append(r)
    init_ch = {(a, b): 0 for a in chips for b in chips if a != b}
    return pipe, init_ch


def _wall_time_ms(rows):
    by_cycle = {}
    for r in rows:
        by_cycle.setdefault(r["Time"], []).append(r)
    total = 0.0
    for c in sorted(by_cycle):
        total += max((r["_dur"] for r in by_cycle[c]), default=0.0)
    return total * 1000.0, len(by_cycle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", required=True, type=Path,
                    help="Path to a Schedule-*.json from run.py --enable_ees")
    ap.add_argument("--arch", required=True,
                    help="Architecture preset (F120/F180/F240/F500/F800/F1100)")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output JSON path")
    args = ap.parse_args()

    pipe, init_ch = schedule_to_pipeline(args.schedule)
    link_cap = parse_link_cap(args.arch)

    wall_orig, cycles_orig = _wall_time_ms(pipe)

    res = qucomm_parallel_schedule(
        pipe, init_ch,
        min_comm_value=-1000, max_comm_value=2000,
        link_epr_capacity=link_cap,
        debug=False,
        verify_postcondition=True,
    )
    wall_extra, cycles_extra = _wall_time_ms(res)

    out = {
        "schedule": str(args.schedule),
        "arch": args.arch,
        "link_epr_capacity": link_cap,
        "teff_orig": len(pipe),
        "teff_extra_opt": len(res),
        "cycles_orig": cycles_orig,
        "cycles_extra_opt": cycles_extra,
        "wall_time_ms_orig": wall_orig,
        "wall_time_ms_extra": wall_extra,
        "speedup": (wall_orig / wall_extra) if wall_extra > 0 else None,
        "violations": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}: cycles {cycles_orig} -> {cycles_extra}, "
          f"wall {wall_orig:.2f}ms -> {wall_extra:.2f}ms")


if __name__ == "__main__":
    main()
