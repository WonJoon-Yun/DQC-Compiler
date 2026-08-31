#!/usr/bin/env python3
"""Fig 11: cumulative teleportation cost over scheduled gates (UMS effect).
Compares QuComm vs IRIS-opt0 (no EES — isolates routing/UMS).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import find_tracer, load_tracer_ms, setup_rcparams  # noqa: E402

MOVE_OPS = {"RELOCATE", "Transfer"}


def _cumulative_teleports(df):
    moves = df[df["optype"].isin(MOVE_OPS)].copy()
    moves = moves.sort_values("end_time").reset_index(drop=True)
    x = moves["end_time"].to_numpy()
    y = np.arange(1, len(moves) + 1)
    return x, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qucomm", required=True, type=Path)
    ap.add_argument("--iris-opt0", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    setup_rcparams()
    fig, ax = plt.subplots(figsize=(5, 2.8))

    for label, color, root in [
        ("QuComm", "#888888", args.qucomm),
        ("IRIS-opt0", "#1f6fb4", getattr(args, "iris_opt0")),
    ]:
        t = find_tracer(root)
        if t is None:
            print(f"[warn] no tracer in {root}")
            continue
        df = load_tracer_ms(t)
        x, y = _cumulative_teleports(df)
        ax.step(x, y, where="post", linewidth=2.5, color=color, label=label)

    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Cumulative teleportations")
    ax.legend(loc="lower right", framealpha=1.0)
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, bbox_inches="tight", pad_inches=0.05)
    plt.savefig(args.output.with_suffix(".png"), bbox_inches="tight", pad_inches=0.05, dpi=150)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
