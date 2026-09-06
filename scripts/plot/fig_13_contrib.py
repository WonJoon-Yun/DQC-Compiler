#!/usr/bin/env python3
"""Contribution-breakdown bar chart (fig_contrib): teleportation count per
ablation configuration, read from results/<...>/ablation/<tag>/<bench>-<archdir>/.

Produced by scripts/fig_13.sh. T_eff = #state_teleportations +
1.77 * #gate_teleportations (paper Eq. 4).
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ALPHA_RECNOT = 1.77

# (dir tag, figure label, bar color) — order defines the figure
CONFIGS = [
    ("QuComm-default",        "QuComm\n(default)",                     "#fafafa"),
    ("QuComm-next-k",         "QuComm with\nNext-K Blocks\nfor Lookahead", "#dcf5d6"),
    ("IRIS-single-candidate", "IRIS with\nSingle\nCandidate",          "#bddeb3"),
    ("IRIS-next-k",           "IRIS with\nNext-K Blocks\nfor Lookahead", "#80c783"),
    ("IRIS-default",          "IRIS\n(default)",                       "#42ab49"),
]


# fig_13.sh ablation tag -> dataset scheduling directory
DATASET_DIRS = {
    "QuComm-default": "QuComm",
    "QuComm-next-k": "QuComm-nextk",
    "IRIS-single-candidate": "IRIS-single",
    "IRIS-next-k": "IRIS-nextk",
    "IRIS-default": "IRIS",
}


def teff(run_dir: Path) -> float:
    matches = sorted(run_dir.glob("results*.json"))
    if matches:
        d = json.loads(matches[0].read_text())
    else:
        matches = sorted(run_dir.glob("results*.json.gz"))
        if not matches:
            raise SystemExit(f"no results*.json in {run_dir} "
                             "(run scripts/fig_13.sh first)")
        d = json.loads(gzip.decompress(matches[0].read_bytes()))
    return (d.get("num_state_teleportations", 0)
            + ALPHA_RECNOT * d.get("num_gate_teleportations", 0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path,
                    help="Ablation root (results/<...>/ablation), or the "
                         "IRIS-dataset root with --layout dataset")
    ap.add_argument("--layout", choices=["ablation", "dataset"],
                    default="ablation",
                    help="dataset: read MinCut/<scheduling>/ run dirs")
    ap.add_argument("--bench", required=True, help="e.g. qaoa_3reg_n120")
    ap.add_argument("--archdir", required=True, help="e.g. S40C5-2x2")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    if args.layout == "dataset":
        run_dirs = [args.root / "MinCut" / DATASET_DIRS[tag]
                    / f"{args.bench}-{args.archdir}" for (tag, _, _) in CONFIGS]
    else:
        run_dirs = [args.root / tag / f"{args.bench}-{args.archdir}"
                    for (tag, _, _) in CONFIGS]
    values = [teff(d) for d in run_dirs]

    plt.rcParams.update({"font.size": 15, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, ax = plt.subplots(figsize=(7.4, 2.9))
    xs = list(range(len(CONFIGS)))
    for x, ((_, label, color), v) in zip(xs, zip(CONFIGS, values)):
        ax.bar(x, v, width=0.62, facecolor=color, edgecolor="black",
               linewidth=0.8, zorder=3)
        ax.text(x, v + max(values) * 0.02, f"{v:.0f}", ha="center", va="bottom",
                fontsize=14)
    ax.set_ylabel("Teleportation count")
    ax.set_xticks(xs)
    ax.set_xticklabels([c[1] for c in CONFIGS], fontsize=12.5)
    ax.set_ylim(0, max(values) * 1.18)

    plt.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, bbox_inches="tight", pad_inches=0.05)
    fig.savefig(args.output.with_suffix(".png"), bbox_inches="tight",
                pad_inches=0.05, dpi=300)
    plt.close(fig)

    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w") as fh:
        fh.write("config,teff\n")
        for (tag, _, _), v in zip(CONFIGS, values):
            fh.write(f"{tag},{v:.2f}\n")

    print(f"{'config':<24s} T_eff")
    for (tag, _, _), v in zip(CONFIGS, values):
        print(f"{tag:<24s} {v:.0f}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
