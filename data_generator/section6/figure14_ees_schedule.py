#!/usr/bin/env python3
"""§6.5 Figure 14 — schedules of a 240-qubit QAOA-3reg program: cumulative
operation count over time for QuComm / IRIS without EES / IRIS.

Data sources (dataset-layout tree, gz-aware):
  * QuComm and IRIS-noEES lines: per-op `original_end_time` from
    `schedule.json`.
  * IRIS line: `schedule.json` replayed through `qucomm_parallel_schedule`
    (post-hoc EES block-level concurrency), then per-op end times are rebuilt
    by scaling cycle indices back to wall-time (each cycle's wall length =
    max op duration in that cycle).

Output: output/section6/figure14_ees_schedule.{pdf,png,csv}
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import RESULTS_BASE, output_dir
from _early_execution import qucomm_parallel_schedule

STAGE_ORDER = ["QuComm", "IRIS-noEES", "IRIS"]
STAGE_DISPLAY = {
    "QuComm": "QuComm",
    "IRIS-noEES": "IRIS without EES",
    "IRIS": "IRIS with EES",
}
STAGE_COLORS = {
    "QuComm": "#E7EED0",
    "IRIS-noEES": "#40B0C4",
    "IRIS": "#1C061A",
}
STAGE_LINEWIDTH = {"QuComm": 3.2, "IRIS-noEES": 3.2, "IRIS": 3.2}
INCLUDED_OPTYPES = {"Local CNOT", "RELOCATE", "Transfer", "Re-CNOT"}
REPLAY_SCHEDULING = "IRIS"


def _load_json(path: Path):
    if str(path).endswith(".gz"):
        return json.loads(gzip.decompress(path.read_bytes()))
    return json.loads(path.read_text())


def _schedule_path(mapping: str, scheduling: str, bench: str, arch: str) -> Path | None:
    run_dir = RESULTS_BASE / mapping / scheduling / f"{bench}-{arch}"
    for name in ("schedule.json", "schedule.json.gz"):
        p = run_dir / name
        if p.exists():
            return p
    for p in sorted(run_dir.glob("[Ss]chedule*.json")):
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


def _load_schedule_ops(schedule_path: Path):
    import pandas as pd
    ops = _load_json(schedule_path)["ops"]
    df = pd.DataFrame({
        "optype": [o["optype"] for o in ops],
        "start_time": [float(o["original_start_time"]) for o in ops],
        "end_time": [float(o["original_end_time"]) for o in ops],
    })
    df = df[df["optype"].isin(INCLUDED_OPTYPES)].copy()
    df = df.sort_values("end_time").reset_index(drop=True)
    df["start_time"] = df["start_time"] * 1000
    df["end_time"] = df["end_time"] * 1000
    return df


def _replay_extra_opt(schedule_path: Path, link_cap: int, target_optypes: set):
    import pandas as pd
    pipe, init_ch = schedule_to_pipeline(schedule_path)
    res = qucomm_parallel_schedule(
        pipe, init_ch, min_comm_value=-1000, max_comm_value=2000,
        link_epr_capacity=link_cap, debug=False,
    )
    by_cycle: dict[int, list[dict]] = {}
    for r in res:
        by_cycle.setdefault(r["Time"], []).append(r)
    cycles_sorted = sorted(by_cycle.keys())
    cycle_wall_start: dict[int, float] = {}
    cum = 0.0
    for c in cycles_sorted:
        cycle_wall_start[c] = cum
        max_d = max((r["_dur"] for r in by_cycle[c]), default=0.0)
        cum += max_d
    rows_out = []
    for r in res:
        if r["_optype"] not in target_optypes:
            continue
        end_s = cycle_wall_start[r["Time"]] + r["_dur"]
        rows_out.append({"end_time": end_s * 1000.0, "optype": r["_optype"]})
    df = pd.DataFrame(rows_out)
    if not df.empty:
        df = df.sort_values("end_time").reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", default="MinCut")
    parser.add_argument("--benchmark", default="qaoa_3reg_n240")
    parser.add_argument("--arch", default="S40C5-3x3")
    parser.add_argument("--stages", default=",".join(STAGE_ORDER))
    parser.add_argument("--xlim", type=float, default=None)
    args = parser.parse_args()

    import numpy as np
    out = output_dir("section6")

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    link_cap = link_epr_capacity(args.arch)

    datasets = []
    for stage in stages:
        sched_path = _schedule_path(args.mapping, stage, args.benchmark, args.arch)
        if sched_path is None:
            print(f"WARNING: No schedule for {stage}")
            continue
        if stage == REPLAY_SCHEDULING:
            df = _replay_extra_opt(sched_path, link_cap, INCLUDED_OPTYPES)
            print(f"  {stage}: {len(df)} ops, max time: {df['end_time'].max():.3f} ms (extra-opt applied)")
        else:
            df = _load_schedule_ops(sched_path)
            print(f"  {stage}: {len(df)} ops, max time: {df['end_time'].max():.3f} ms")
        datasets.append({
            "stage": stage,
            "df": df,
            "label": STAGE_DISPLAY.get(stage, stage),
            "color": STAGE_COLORS.get(stage, "#888"),
            "linewidth": STAGE_LINEWIDTH.get(stage, 2.0),
            "max_time": float(df["end_time"].max()) if len(df) else 0.0,
            "num_ops": len(df),
        })

    if not datasets:
        note = out / "figure14_ees_schedule.MISSING.txt"
        note.write_text("no schedule.json found for the three variants\n")
        print(f"[stub] {note}")
        return

    csv_path = out / "figure14_ees_schedule.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stage", "num_ops", "max_time_ms"])
        for d in datasets:
            w.writerow([d["stage"], d["num_ops"], f"{d['max_time']:.3f}"])
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

    xlim_max = args.xlim or max(d["max_time"] for d in datasets) * 1.02
    fig, ax = plt.subplots(1, 1, figsize=(5, 2.67))

    max_y = 0
    for d in datasets:
        df = d["df"]
        if df.empty:
            continue
        x = df["end_time"].to_numpy()
        y = np.arange(1, len(df) + 1)
        ax.step(x, y, where="post", linestyle="-", linewidth=d["linewidth"],
                color=d["color"], alpha=0.95, label=d["label"], antialiased=True)
        max_y = max(max_y, len(df))

    ax.set_xlabel("Time (milliseconds)", fontsize=13)
    ax.set_ylabel("Operation Count", fontsize=13)
    ax.set_xlim(0, xlim_max)

    if xlim_max <= 500:
        tick = 100
    elif xlim_max <= 2000:
        tick = 500
    elif xlim_max <= 5000:
        tick = 1000
    else:
        tick = 2000
    xtick = np.arange(0, xlim_max + 1, tick)
    ax.set_xticks(xtick)
    ax.set_xticklabels([f"{int(t)}" for t in xtick], fontsize=13)

    if max_y > 0:
        ax.set_ylim(-0.5, max_y * 1.02)
        if max_y > 1000:
            yticks = [0, 500, 1000]
            step = 1000
            n_extra = max(0, int(max_y / 1000))
            for k in range(2, n_extra + 1):
                yticks.append(k * step)
            yticks = [y for y in yticks if y <= max_y]
            ax.set_yticks(yticks)

            def _fmt(y):
                if y == 0:
                    return "0"
                if y == 500:
                    return "0.5K"
                return f"{int(y/1000)}K"

            ax.set_yticklabels([_fmt(y) for y in yticks])
    ax.legend(loc="lower right", fontsize=11,
              labelspacing=0.2, borderpad=0.3,
              handlelength=1.4, handletextpad=0.4,
              borderaxespad=0.2,
              framealpha=1.0).set_zorder(20)

    _VLINE_COLOR = {"QuComm": "#888888", "IRIS-noEES": "blue", "IRIS": "blue"}
    for d in datasets:
        ax.axvline(x=d["max_time"], linestyle=":", linewidth=2.0,
                   color=_VLINE_COLOR.get(d["stage"], d["color"]), alpha=0.95,
                   zorder=5)

    plt.tight_layout()
    out_pdf = out / "figure14_ees_schedule.pdf"
    plt.savefig(out_pdf, bbox_inches="tight", pad_inches=0.05)
    plt.savefig(out_pdf.with_suffix(".png"), bbox_inches="tight",
                pad_inches=0.05, dpi=150)
    plt.close()
    print(f"wrote {out_pdf}")
    print(f"wrote {out_pdf.with_suffix('.png')}")


if __name__ == "__main__":
    main()
