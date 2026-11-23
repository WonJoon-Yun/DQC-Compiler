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
    violations           -- first location error per replay stage in historical mode
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

from analysis.schedule_locations import initial_locations, pipeline_rows, read_schedule, validate_locations
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
    return pipeline_rows(read_schedule(schedule_path)["ops"])


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
                    help="Reproduce archived timing and record location errors in the output")
    args = ap.parse_args()

    schedule = read_schedule(args.schedule)
    initial = initial_locations(schedule)
    pipe, init_ch = pipeline_rows(schedule["ops"])
    del schedule
    violations = []

    def check_locations(rows, *, original_times=False):
        try:
            validate_locations(rows, initial, original_times=original_times)
        except ValueError as error:
            if not args.historical_replay:
                raise
            stage = "emitted" if original_times else "postprocessed"
            violations.append(f"{stage}: {error}")

    check_locations(pipe, original_times=True)
    link_cap = parse_link_cap(args.arch)

    wall_orig, cycles_orig = _wall_time_ms(pipe)

    res = qucomm_parallel_schedule(
        pipe, init_ch,
        min_comm_value=-1000, max_comm_value=2000,
        link_epr_capacity=link_cap,
        debug=False,
        verify_postcondition=True,
    )
    check_locations(res)
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
        "violations": violations,
    }
    if args.historical_replay:
        out["historical_replay"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}: cycles {cycles_orig} -> {cycles_extra}, "
          f"wall {wall_orig:.2f}ms -> {wall_extra:.2f}ms")


if __name__ == "__main__":
    main()
