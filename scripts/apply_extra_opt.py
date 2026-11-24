#!/usr/bin/env python3
"""Apply EES as post-processing (block-level parallelization) to a schedule
JSON written by run.py.

Usage:
    python apply_extra_opt.py --schedule <path>/Schedule-*.json --arch F240 \
        --out <path>/extra_opt.json

Output JSON fields:
    teff_orig            -- legacy field counting original operation rows
    teff_extra_opt       -- operation rows after parallelization
    cycles_orig          -- number of distinct original time slots
    cycles_extra_opt     -- number of cycles after parallelization
    wall_time_ms_orig    -- sum of per-cycle max durations (original)
    wall_time_ms_extra   -- same metric on the extra-opt schedule
    link_epr_capacity    -- per-link EPR cap used for the optimizer
    selection            -- parallelized or original_cycles
    candidate_rejection  -- directional-channel failure that required the original cycles
    violations           -- validation failures on the historical schedule
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = AE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from analysis.schedule_postprocess import parse_link_cap, replay_schedule


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
                    help="Path to schedule.json from run.py")
    ap.add_argument("--arch", required=True,
                    help="Architecture preset (F120/F180/F240/F500/F800/F1100)")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output JSON path")
    ap.add_argument("--historical-replay", action="store_true",
                    help="Reproduce archived timing and record location and channel errors in the output")
    args = ap.parse_args()

    link_cap = parse_link_cap(args.arch)
    pipe, res, metadata = replay_schedule(args.schedule, link_cap, historical_replay=args.historical_replay)
    wall_orig, cycles_orig = _wall_time_ms(pipe)
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
        **metadata,
    }
    if args.historical_replay:
        out["historical_replay"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}: cycles {cycles_orig} -> {cycles_extra}, "
          f"wall {wall_orig:.2f}ms -> {wall_extra:.2f}ms")


if __name__ == "__main__":
    main()
