#!/usr/bin/env python3
"""Fig 16: lookahead-window (beam_width w) and depth (|G|) sensitivity.

Reads results/sensitivity/{bw_*,lh_*}/<arch>/<mapper>/<bench>/.../results*.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import setup_rcparams  # noqa: E402


def _read_runtime(result_dir):
    cs = sorted(Path(result_dir).rglob("results*.json"))
    if not cs:
        return None
    d = json.loads(cs[0].read_text())
    return float(d.get("total_execution_time", 0)) * 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path,
                    help="Root of results/sensitivity/")
    ap.add_argument("--bench", required=True)
    ap.add_argument("--arch", required=True)
    ap.add_argument("--mapper", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    setup_rcparams()

    bw_pts, lh_pts = [], []
    for sub in sorted(args.root.iterdir()):
        if not sub.is_dir():
            continue
        m_bw = re.match(r"bw_(\d+)$", sub.name)
        m_lh = re.match(r"lh_(\d+)$", sub.name)
        if not (m_bw or m_lh):
            continue
        d = sub / args.arch / args.mapper / args.bench
        rt = _read_runtime(d)
        if rt is None:
            continue
        (bw_pts if m_bw else lh_pts).append(
            (int((m_bw or m_lh).group(1)), rt))

    fig, axes = plt.subplots(1, 2, figsize=(7.5, 3))
    if bw_pts:
        bw_pts.sort()
        xs, ys = zip(*bw_pts)
        axes[0].plot(xs, ys, marker="o", linewidth=2.0, color="#1C061A")
        axes[0].set_xlabel("Beam width $w$")
        axes[0].set_ylabel("Runtime (ms)")
        axes[0].set_xscale("log", base=2)
    if lh_pts:
        lh_pts.sort()
        xs, ys = zip(*lh_pts)
        axes[1].plot(xs, ys, marker="s", linewidth=2.0, color="#1C061A")
        axes[1].set_xlabel("Lookahead depth $|G|$")
        axes[1].set_ylabel("Runtime (ms)")
    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(args.output, bbox_inches="tight", pad_inches=0.05)
    plt.savefig(args.output.with_suffix(".png"), bbox_inches="tight", pad_inches=0.05, dpi=150)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
