#!/usr/bin/env python3
"""Fig 14: EES schedule overlay.
QuComm + IRIS-opt0 use raw tracer end_times. IRIS-opt1 replays its EES schedule
through the same validated extra-opt selection as the timing sidecar.

"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (find_schedule, find_tracer, load_tracer_ms,  # noqa: E402
                     setup_rcparams, INCLUDED_OPTYPES)
from analysis.schedule_postprocess import parse_link_cap, replay_schedule


def _replay(schedule_path, link_cap):
    _, res, metadata = replay_schedule(schedule_path, link_cap)
    if metadata["candidate_rejection"]:
        print(f"Retained original cycles: {metadata['candidate_rejection']}")
    by_cycle = {}
    for r in res:
        by_cycle.setdefault(r["Time"], []).append(r)
    cum, wall_starts = 0.0, {}
    for c in sorted(by_cycle):
        wall_starts[c] = cum
        cum += max((r["_dur"] for r in by_cycle[c]), default=0.0)
    rows = []
    for r in res:
        if r["_optype"] in INCLUDED_OPTYPES:
            rows.append({"end_time": (wall_starts[r["Time"]] + r["_dur"]) * 1000.0,
                         "optype": r["_optype"]})
    df = pd.DataFrame(rows).sort_values("end_time").reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qucomm", required=True, type=Path)
    ap.add_argument("--iris-opt0", required=True, type=Path)
    ap.add_argument("--iris-opt1", required=True, type=Path)
    ap.add_argument("--arch", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    setup_rcparams()
    link_cap = parse_link_cap(args.arch)

    datasets = []
    for stage, color, root, replay in [
        ("QuComm", "#888888", args.qucomm, False),
        ("IRIS without EES", "#40B0C4", getattr(args, "iris_opt0"), False),
        ("IRIS with EES", "#1C061A", getattr(args, "iris_opt1"), True),
    ]:
        if replay:
            sched = find_schedule(root)
            if sched is None:
                print(f"[warn] no [Ss]chedule*.json in {root}")
                continue
            df = _replay(sched, link_cap)
        else:
            tr = find_tracer(root)
            if tr is None:
                print(f"[warn] no tracer in {root}")
                continue
            df = load_tracer_ms(tr)
        if df.empty:
            continue
        datasets.append({"stage": stage, "color": color, "df": df,
                         "max_time": float(df["end_time"].max())})

    if not datasets:
        raise SystemExit("no data")

    xlim = max(d["max_time"] for d in datasets) * 1.02
    fig, ax = plt.subplots(figsize=(5, 2.67))
    max_y = 0
    for d in datasets:
        x = d["df"]["end_time"].to_numpy()
        y = np.arange(1, len(d["df"]) + 1)
        ax.step(x, y, where="post", linewidth=3.2, color=d["color"],
                alpha=0.95, label=d["stage"], antialiased=True)
        max_y = max(max_y, len(d["df"]))

    ax.set_xlabel("Time (milliseconds)")
    ax.set_ylabel("Operation Count")
    ax.set_xlim(0, xlim)
    if max_y > 0:
        ax.set_ylim(-0.5, max_y * 1.02)

    _VL = {"QuComm": "#888888", "IRIS without EES": "blue", "IRIS with EES": "blue"}
    for d in datasets:
        ax.axvline(x=d["max_time"], linestyle=":", linewidth=2.0,
                   color=_VL.get(d["stage"], d["color"]), alpha=0.95, zorder=5)

    ax.legend(loc="lower right", fontsize=11, labelspacing=0.2, borderpad=0.3,
              handlelength=1.4, handletextpad=0.4, borderaxespad=0.2,
              framealpha=1.0).set_zorder(20)
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, bbox_inches="tight", pad_inches=0.05)
    plt.savefig(args.output.with_suffix(".png"), bbox_inches="tight", pad_inches=0.05, dpi=150)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
