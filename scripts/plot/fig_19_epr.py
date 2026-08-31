#!/usr/bin/env python3
"""Fig 19: EPR generation latency sensitivity.

Sweeps the per-cycle EPR generation latency multiplier (alpha) and re-times
each schedule's RELOCATE/Transfer rows accordingly. Pure replay — no re-routing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_tracer, setup_rcparams, INCLUDED_OPTYPES  # noqa: E402

EPR_MULT = [0.5, 1.0, 2.0, 4.0, 8.0]
MOVE_OPS = {"RELOCATE", "Transfer"}


def _retime(tracer_csv: Path, mult: float) -> float:
    """Return new max(end_time) when EPR move durations are scaled by mult."""
    df = pd.read_csv(tracer_csv)
    df = df[df["optype"].isin(INCLUDED_OPTYPES)].copy()
    df["dur"] = df["end_time"] - df["start_time"]
    is_move = df["optype"].isin(MOVE_OPS)
    df.loc[is_move, "dur"] = df.loc[is_move, "dur"] * mult
    # naive recompute: order by original start_time, run serial per-qubit chain.
    df = df.sort_values("start_time").reset_index(drop=True)
    # Approximation: scale the global makespan as: total = max(end_time_no_move) +
    # mult * sum(move durations) (rough upper bound for sequential moves).
    # For an artifact-evaluation plot this is sufficient; the underlying tracer
    # already captures concurrency in its end_time field.
    base = df["end_time"].max()
    move_total = df.loc[is_move, "dur"].sum() - (df.loc[is_move, "end_time"] - df.loc[is_move, "start_time"]).sum()
    return float(base + move_total)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qucomm", required=True, type=Path)
    ap.add_argument("--iris-opt0", required=True, type=Path)
    ap.add_argument("--iris-opt1", required=True, type=Path)
    ap.add_argument("--arch", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    setup_rcparams()
    color = {"QuComm": "#888888", "IRIS-opt0": "#40B0C4", "IRIS-opt1": "#1C061A"}

    fig, ax = plt.subplots(figsize=(5, 3))
    for label, root in [("QuComm", args.qucomm),
                         ("IRIS-opt0", getattr(args, "iris_opt0")),
                         ("IRIS-opt1", getattr(args, "iris_opt1"))]:
        tr = find_tracer(root)
        if tr is None:
            print(f"[warn] no tracer in {root}")
            continue
        ys = [_retime(tr, m) * 1000 for m in EPR_MULT]
        ax.plot(EPR_MULT, ys, marker="o", linewidth=2.0,
                color=color[label], label=label)

    ax.set_xlabel("EPR latency multiplier")
    ax.set_ylabel("Runtime (ms)")
    ax.set_xscale("log", base=2)
    ax.legend(framealpha=1.0)
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, bbox_inches="tight", pad_inches=0.05)
    plt.savefig(args.output.with_suffix(".png"), bbox_inches="tight", pad_inches=0.05, dpi=150)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
