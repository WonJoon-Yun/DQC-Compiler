#!/usr/bin/env python3
"""§6.2 Figure 11 — cumulative effective teleportations per block
(Shor, 240 qubits, 3x3 DQC), QuComm vs IRIS.

Reads the per-block profile (`operation_info_on_large_block`,
`blocks_agg_node`) from `results.json` of the two runs in the dataset-layout
tree (<Mapping>/<Scheduling>/<bench>-<arch>/). Plotting code unchanged from
the paper's script.

Output: output/section6/figure11_ums_cumulative_teleportation.{pdf,png,csv}
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import RESULTS_BASE, output_dir


def _load_json(path: Path):
    if str(path).endswith(".gz"):
        return json.loads(gzip.decompress(path.read_bytes()))
    return json.loads(path.read_text())


def _results_path(mapping: str, scheduling: str, bench: str, arch: str) -> Path:
    run_dir = RESULTS_BASE / mapping / scheduling / f"{bench}-{arch}"
    for name in ("results.json", "results.json.gz"):
        p = run_dir / name
        if p.exists():
            return p
    for p in sorted(run_dir.glob("results-*.json")):
        return p
    raise SystemExit(f"Result JSON not found under {run_dir}")


def _load_block_profile(path: Path):
    import numpy as np
    data = _load_json(path)
    agg_mapping: dict[tuple[int, int], int] = {}
    agg_nodes: list[int] = []
    for value in (data.get("blocks_agg_node") or {}).values():
        key = tuple(int(item) for item in value)
        if key not in agg_mapping:
            agg_mapping[key] = len(agg_mapping)
        agg_nodes.append(agg_mapping[key])

    op_needed: list[float] = []
    for op_info in data.get("operation_info_on_large_block", []):
        for op in op_info:
            if isinstance(op, (list, tuple)):
                op_needed.append(float(sum(op)))
            else:
                op_needed.append(float(op))
    return np.asarray(op_needed, dtype=float), np.asarray(agg_nodes, dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Figure 11: cumulative effective teleportations per block (QuComm vs IRIS)."
    )
    parser.add_argument("--mapping", default="MinCut")
    parser.add_argument("--benchmark", default="shor_n240")
    parser.add_argument("--arch", default="S40C5-3x3")
    parser.add_argument("--baseline", default="QuComm")
    parser.add_argument("--stage", default="IRIS")
    parser.add_argument("--baseline_display", default="QuComm")
    parser.add_argument("--stage_display", default="IRIS")
    parser.add_argument("--start_block", type=int, default=0)
    parser.add_argument("--num_blocks", type=int, default=51)
    parser.add_argument("--ymax", type=float, default=33)
    parser.add_argument("--label_a_blocks", default="10,12,14")
    parser.add_argument("--label_b_block", type=int, default=18)
    parser.add_argument("--label_c_block", type=int, default=22)
    parser.add_argument("--png_dpi", type=int, default=200)
    args = parser.parse_args()

    out = output_dir("section6")
    baseline_path = _results_path(args.mapping, args.baseline, args.benchmark, args.arch)
    stage_path = _results_path(args.mapping, args.stage, args.benchmark, args.arch)

    import numpy as np
    baseline_op_needed, baseline_agg_node = _load_block_profile(baseline_path)
    stage_op_needed, stage_agg_node = _load_block_profile(stage_path)
    if len(baseline_op_needed) == 0 or len(stage_op_needed) == 0:
        note = out / "figure11_ums_cumulative_teleportation.MISSING.txt"
        note.write_text("results.json lacks the per-block profile fields\n")
        print(f"[stub] {note}")
        return

    min_len = min(len(baseline_op_needed), len(stage_op_needed),
                  len(baseline_agg_node), len(stage_agg_node))
    start = max(args.start_block, 0)
    end = min(start + max(args.num_blocks, 0), min_len)
    baseline_op_needed = baseline_op_needed[start:end]
    stage_op_needed = stage_op_needed[start:end]
    baseline_agg_node = baseline_agg_node[start:end]
    stage_agg_node = stage_agg_node[start:end]

    block_indices = np.arange(len(baseline_op_needed))
    baseline_cum = np.cumsum(baseline_op_needed) if len(baseline_op_needed) else np.array([])
    stage_cum = np.cumsum(stage_op_needed) if len(stage_op_needed) else np.array([])

    csv_path = out / "figure11_ums_cumulative_teleportation.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["block_idx", "baseline_block_teff", "stage_block_teff",
                         "baseline_cumulative_teff", "stage_cumulative_teff",
                         "baseline_agg_node", "stage_agg_node"])
        for idx in range(len(block_indices)):
            writer.writerow([
                int(block_indices[idx]),
                f"{float(baseline_op_needed[idx]):.6f}",
                f"{float(stage_op_needed[idx]):.6f}",
                f"{float(baseline_cum[idx]):.6f}",
                f"{float(stage_cum[idx]):.6f}",
                int(baseline_agg_node[idx]) if len(baseline_agg_node) > idx else "",
                int(stage_agg_node[idx]) if len(stage_agg_node) > idx else "",
            ])
    print(f"wrote {csv_path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patheffects as path_effects
    except Exception:
        print("[note] matplotlib unavailable; CSV only")
        return

    plt.rcParams["font.family"] = "Times New Roman"
    plt.rcParams["font.size"] = 13
    plt.rcParams["axes.titlesize"] = 13
    plt.rcParams["axes.labelsize"] = 13
    plt.rcParams["xtick.labelsize"] = 13
    plt.rcParams["ytick.labelsize"] = 13
    plt.rcParams["legend.fontsize"] = 13

    fig, ax = plt.subplots(1, 1, figsize=(5, 2.38))
    ax.plot(block_indices, baseline_cum, marker="o", markersize=6,
            linestyle="-", linewidth=2.0, color="#F27393",
            label=args.baseline_display, zorder=3)
    ax.plot(block_indices, stage_cum, marker="*", markersize=5.5,
            markeredgewidth=1., linestyle="-", linewidth=1.5, color="#2F2FE4",
            label=args.stage_display, zorder=4)

    ymax = args.ymax
    if ymax is None:
        ymax = max(float(baseline_cum[-1]) if len(baseline_cum) else 1.0,
                   float(stage_cum[-1]) if len(stage_cum) else 1.0)
    label_y = 28

    _label_style = dict(
        ha="center", va="center", fontsize=14, fontweight="black", color="white",
        bbox=dict(boxstyle="circle,pad=0.25", facecolor="black",
                  edgecolor="black", linewidth=1.),
        zorder=8,
        path_effects=[path_effects.withStroke(linewidth=0.75, foreground="white")],
    )

    _label_entries = []
    if args.label_a_blocks:
        a_blocks = [int(x.strip()) for x in args.label_a_blocks.split(",") if x.strip()]
        mid_block = (a_blocks[0] + a_blocks[-1]) / 2
        targets = [(idx, stage_cum[idx]) for idx in a_blocks if idx < len(stage_cum)]
        _label_entries.append(("A", mid_block, targets))
    if args.label_b_block is not None and args.label_b_block < len(stage_cum):
        idx = args.label_b_block
        _label_entries.append(("B", idx, [(idx, 15.5 - ymax * 0.01)]))
    if args.label_c_block is not None and args.label_c_block < len(stage_cum):
        idx = args.label_c_block
        y_mid = (baseline_cum[idx] + stage_cum[idx]) / 2
        _label_entries.append(("C", idx, [(idx, y_mid)]))

    for (name, lx, targets) in _label_entries:
        for (tx, ty) in targets:
            ax.annotate("", xy=(tx, ty + ymax * 0.01), xytext=(lx, label_y),
                        arrowprops=dict(arrowstyle="-|>", color="black",
                                        lw=1.8, mutation_scale=18), zorder=6)
        ax.text(lx, label_y, name, **_label_style)

    ax.set_xlabel("Block ID")
    ax.set_ylabel("Cumulative $T_{eff}$")
    if len(block_indices) > 0:
        ax.set_xlim(0, 40)
    ax.set_ylim(0, ymax)
    ax.grid(axis="y", linestyle="--", alpha=0.4, zorder=0)
    ax.set_xticks([0, 10, 20, 30, 40])
    ax.set_yticks([0, 10, 20, 30])
    ax.legend(loc="lower right", fontsize=13, frameon=True)

    pdf_path = out / "figure11_ums_cumulative_teleportation.pdf"
    png_path = out / "figure11_ums_cumulative_teleportation.png"
    plt.tight_layout()
    plt.savefig(pdf_path, dpi=600, format="pdf", bbox_inches="tight")
    plt.savefig(png_path, dpi=args.png_dpi, format="png", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {pdf_path}")
    print(f"wrote {png_path}")


if __name__ == "__main__":
    main()
