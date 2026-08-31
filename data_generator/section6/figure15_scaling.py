#!/usr/bin/env python3
"""§6.6 Figure 15 — scaling study, single figure with two subplots.

Left  (a): scaling chip size (System Qubits Per Chip) on a 2x2 DQC.
Right (b): scaling number of chips (DQC Architecture).

Each subplot draws IRIS Teff and Latency relative to QuComm (baseline = 1.0
shown as a dashed reference line). IRIS latency is the post-hoc EES replay of
the saved schedule (qucomm_parallel_schedule), as in the paper.

Data (dataset-layout tree, gz-aware):
    <RESULTS_BASE>/MinCut/{QuComm,IRIS}/<bench>-<arch>/{results,schedule}.json

Output: output/section6/figure15_scaling.{pdf,png,csv}
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import RESULTS_BASE, output_dir
from _early_execution import qucomm_parallel_schedule

# panel (a): (arch_dir, bench_name, system_qubits_per_chip)
CHIP_SIZE_CONFIGS = [
    ("S40C4-2x2", "qaoa_3reg_n120", 40),
    ("S80C8-2x2", "qaoa_3reg_n250", 80),
    ("S120C12-2x2", "qaoa_3reg_n370", 120),
    ("S160C16-2x2", "qaoa_3reg_n500", 160),
]

# panel (b): (arch_dir, bench_name, grid_label)
NUM_CHIP_CONFIGS = [
    ("S40C3-2x2", "qaoa_3reg_n120", "2x2"),
    ("S40C3-2x3", "qaoa_3reg_n180", "2x3"),
    ("S40C3-3x3", "qaoa_3reg_n240", "3x3"),
    ("S40C3-3x4", "qaoa_3reg_n350", "3x4"),
]

MAPPING = "MinCut"
SCHEDULINGS = ["QuComm", "IRIS"]

TEFF_COLOR = "#52057B"
LAT_COLOR = "#FEA82F"
BASELINE_COLOR = "#12372A"


def _load_json(path: Path):
    if str(path).endswith(".gz"):
        return json.loads(gzip.decompress(path.read_bytes()))
    return json.loads(path.read_text())


def _run_file(run_dir: Path, name: str) -> Path | None:
    for cand in (run_dir / name, run_dir / (name + ".gz")):
        if cand.exists():
            return cand
    stem = name.split(".")[0]
    for p in sorted(run_dir.glob(f"[{stem[0].upper()}{stem[0]}]{stem[1:]}*.json")):
        return p
    return None


def link_epr_capacity(arch_dir: str, default: int = 5) -> int:
    m = re.search(r"C(\d+)", arch_dir or "")
    return int(m.group(1)) if m else default


def schedule_to_pipeline(schedule_path: Path):
    data = _load_json(schedule_path)
    ops = data["ops"]
    starts = sorted({o["original_start_time"] for o in ops})
    s2t = {s: i for i, s in enumerate(starts)}
    pipe, chips = [], set()
    for o in ops:
        t = s2t[o["original_start_time"]]
        pos0, pos1 = tuple(o["pos0"]), tuple(o["pos1"])
        chips.add(pos0)
        chips.add(pos1)
        dur = float(o.get("original_duration", 0.0))
        if o["optype"] in ("Local CNOT", "Re-CNOT"):
            r = {"Time": t, "CNOT": True, "SIdx": int(o["atom0"]), "TIdx": int(o["atom1"]),
                 "SPos": pos0, "SNextPos": pos0, "TPos": pos1, "TNextPos": pos1,
                 "BlockID": int(o["layer_id"]), "_dur": dur, "_optype": o["optype"]}
        else:
            r = {"Time": t, "CNOT": False, "SIdx": int(o["atom0"]), "TIdx": int(o["atom0"]),
                 "SPos": pos0, "SNextPos": pos1, "TPos": pos0, "TNextPos": pos0,
                 "BlockID": int(o["layer_id"]), "_dur": dur, "_optype": o["optype"]}
        pipe.append(r)
    init_ch = {(a, b): 0 for a in chips for b in chips if a != b}
    return pipe, init_ch


def _extra_opt_latency(schedule_path: Path, arch_dir: str) -> float:
    pipe, init_ch = schedule_to_pipeline(schedule_path)
    res = qucomm_parallel_schedule(
        pipe, init_ch, min_comm_value=-1000, max_comm_value=2000,
        link_epr_capacity=link_epr_capacity(arch_dir, default=5), debug=False)
    by_cycle: dict[int, list] = {}
    for r in res:
        by_cycle.setdefault(r["Time"], []).append(r)
    cum = 0.0
    for c in sorted(by_cycle.keys()):
        max_d = max((r["_dur"] for r in by_cycle[c]), default=0.0)
        cum += max_d
    return cum


def collect(configs):
    """Return (label_list, qucomm_teff, qucomm_lat, iris_teff, iris_lat)."""
    data: dict[str, list] = {s: [] for s in SCHEDULINGS}
    for arch_dir, bench, label in configs:
        for sched in SCHEDULINGS:
            run_dir = RESULTS_BASE / MAPPING / sched / f"{bench}-{arch_dir}"
            res_path = _run_file(run_dir, "results.json")
            if res_path is None:
                print(f"WARNING: missing {sched} {bench} {arch_dir}")
                continue
            d = _load_json(res_path)
            teff = float(d.get("effective_teleportations",
                               d.get("num_effective_cnots", 0)))
            lat = float(d.get("total_execution_time", 0))
            if sched == "IRIS":
                sched_path = _run_file(run_dir, "schedule.json")
                if sched_path is not None:
                    try:
                        lat = _extra_opt_latency(sched_path, arch_dir)
                    except Exception as exc:
                        print(f"  extra-opt failed for {bench}/{arch_dir}: {exc}")
            data[sched].append((label, teff, lat))

    labels = [lbl for lbl, _, _ in data["QuComm"]]
    q_teff = [t for _, t, _ in data["QuComm"]]
    q_lat = [l for _, _, l in data["QuComm"]]
    i_teff = [t for _, t, _ in data["IRIS"]]
    i_lat = [l for _, _, l in data["IRIS"]]
    return labels, q_teff, q_lat, i_teff, i_lat


def norm(iris_vals, qucomm_vals):
    return [iv / qv if qv > 0 else 1.0 for iv, qv in zip(iris_vals, qucomm_vals)]


def draw_panel(ax, x_labels, nteff, nlat, xlabel, yticks, yticklabels, ylim,
               show_ylabel: bool):
    import numpy as np
    x_pos = np.arange(len(x_labels))

    ax.axhline(1.0, color=BASELINE_COLOR, linestyle="--", linewidth=1.8,
               alpha=0.9, zorder=2)
    ax.plot(x_pos, nteff, marker="P", markersize=8.5, markeredgewidth=0.8,
            linestyle="-", linewidth=1.5, color=TEFF_COLOR,
            label=r"$T_{eff}$", zorder=4)
    ax.plot(x_pos, nlat, marker="H", markersize=8.5, markeredgewidth=0.8,
            linestyle="-", linewidth=1.5, color=LAT_COLOR,
            label="Latency", zorder=4)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(x_labels, fontsize=13)
    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels, fontsize=13)
    ax.set_ylim(ylim)
    ax.set_xlabel(xlabel)
    if show_ylabel:
        ax.set_ylabel("Rel. Performance", labelpad=0)
    ax.grid(axis="y", linestyle="--", alpha=0.3)


def main() -> None:
    out = output_dir("section6")

    sq_list, q65_teff, q65_lat, i65_teff, i65_lat = collect(CHIP_SIZE_CONFIGS)
    grid_list, q66_teff, q66_lat, i66_teff, i66_lat = collect(NUM_CHIP_CONFIGS)
    if not sq_list or not grid_list:
        note = out / "figure15_scaling.MISSING.txt"
        note.write_text("missing scaling-sweep runs "
                        "(MinCut S40C4/S80C8/S120C12/S160C16-2x2 and "
                        "S40C3-{2x2,2x3,3x3,3x4})\n")
        print(f"[stub] {note}")
        return

    nteff_65 = norm(i65_teff, q65_teff)
    nlat_65 = norm(i65_lat, q65_lat)
    nteff_66 = norm(i66_teff, q66_teff)
    nlat_66 = norm(i66_lat, q66_lat)

    csv_path = out / "figure15_scaling.csv"
    with csv_path.open("w") as fh:
        fh.write("panel,label,qucomm_teff,qucomm_latency,iris_teff,iris_latency,rel_teff,rel_latency\n")
        for lbl, qt, ql, it, il, nt, nl in zip(sq_list, q65_teff, q65_lat, i65_teff, i65_lat, nteff_65, nlat_65):
            fh.write(f"a_chip_size,{lbl},{qt:.6f},{ql:.9f},{it:.6f},{il:.9f},{nt:.6f},{nl:.6f}\n")
        for lbl, qt, ql, it, il, nt, nl in zip(grid_list, q66_teff, q66_lat, i66_teff, i66_lat, nteff_66, nlat_66):
            fh.write(f"b_num_chips,{lbl},{qt:.6f},{ql:.9f},{it:.6f},{il:.9f},{nt:.6f},{nl:.6f}\n")
    print(f"wrote {csv_path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("[note] matplotlib unavailable; CSV only")
        return

    plt.rcParams["font.family"] = "Times New Roman"
    plt.rcParams["font.size"] = 13
    for k in ("axes.titlesize", "axes.labelsize", "xtick.labelsize",
              "ytick.labelsize", "legend.fontsize"):
        plt.rcParams[k] = 13
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(5.4, 1.95))
    sq_labels = [str(sq) for sq in sq_list]
    grid_labels = [g.replace("x", r"$\times$") for g in grid_list]
    common_yticks = [0.0, 0.5, 1.0]
    common_yticklabels = ["0", "0.5", "1"]
    common_ylim = (0.0, 1.3)

    draw_panel(ax_a, sq_labels, nteff_65, nlat_65,
               "(a) System Qubits Per Chip",
               yticks=common_yticks, yticklabels=common_yticklabels,
               ylim=common_ylim, show_ylabel=True)
    draw_panel(ax_b, grid_labels, nteff_66, nlat_66,
               "(b) DQC Architecture",
               yticks=common_yticks, yticklabels=common_yticklabels,
               ylim=common_ylim, show_ylabel=True)

    for ax in (ax_a, ax_b):
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles, labels, loc="upper center", ncol=2,
                  bbox_to_anchor=(0.5, 1.02), frameon=False,
                  fontsize=12, handlelength=1.0, handletextpad=0.3,
                  columnspacing=0.8, borderaxespad=0.0)

    plt.tight_layout()
    fig.subplots_adjust(wspace=0.5)
    pdf_path = out / "figure15_scaling.pdf"
    fig.savefig(pdf_path, dpi=600, format="pdf", bbox_inches="tight")
    fig.savefig(pdf_path.with_suffix(".png"), dpi=150, format="png",
                bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {pdf_path}")

    print("(a) chip size:")
    for lbl, qt, it, ql, il in zip(sq_list, q65_teff, i65_teff, q65_lat, i65_lat):
        print(f"  SQ={lbl}: QuComm Teff={qt:.0f} Lat={ql:.4f}s "
              f"| IRIS Teff={it:.0f} Lat={il:.4f}s")
    print("(b) num chips:")
    for lbl, qt, it, ql, il in zip(grid_list, q66_teff, i66_teff, q66_lat, i66_lat):
        print(f"  {lbl}: QuComm Teff={qt:.0f} Lat={ql:.4f}s "
              f"| IRIS Teff={it:.0f} Lat={il:.4f}s")


if __name__ == "__main__":
    main()
