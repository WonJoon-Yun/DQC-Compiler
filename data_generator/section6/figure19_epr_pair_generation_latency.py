#!/usr/bin/env python3
"""§6.9 Figure 19 — latency of a 240-qubit QAOA-FC program on a 3x3 DQC while
sweeping the fraction of EPR-generation latency that is hidden behind atom
movement.

The saved schedules (dataset-layout tree, gz-aware) are replayed operation by
operation with modified hardware latencies (`analysis.schedule_rescore` from
the compiler source); the IRIS line additionally goes through the post-hoc
EES replay (`qucomm_parallel_schedule`). Exposed EPR = fraction * EPR_GEN_US;
atom movement stays at DEFAULT_TIME_MOVE_US.

Output: output/section6/figure19_epr_pair_generation_latency.{pdf,png,csv}
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

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from analysis.schedule_rescore import (  # noqa: E402
    build_hyperparameters_from_snapshot,
    replay_saved_schedule,
)

BASE_TIME_INT_2Q = 2.324e-3
BASE_TIME_INT_SWAP = 1.324e-3
EPR_GEN_US_DEFAULT = 259.0
DEFAULT_TIME_MOVE_US = 300.0
DEFAULT_FRACTION_GRID = "0,10,20,30,40,50,60,70,80,90,100"

STAGE_COLORS = {
    "QuComm": "#F27393",
    "IRIS-noEES": "#de5a79",
    "IRIS": "#2F2FE4",
}
STAGE_DISPLAY = {
    "QuComm": "QuComm",
    "IRIS-noEES": "IRIS w/o EEE",
    "IRIS": "IRIS",
}
STAGE_MARKERS = {
    "QuComm": "o",
    "IRIS-noEES": "s",
    "IRIS": "*",
}


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


def _schedule_to_pipeline_from_payload(payload):
    ops = payload["ops"]
    starts = sorted({o["original_start_time"] for o in ops})
    s2t = {s: i for i, s in enumerate(starts)}
    pipe, chips = [], set()
    for o in ops:
        t = s2t[o["original_start_time"]]
        pos0, pos1 = tuple(o["pos0"]), tuple(o["pos1"])
        chips.add(pos0)
        chips.add(pos1)
        bid = int(o["layer_id"])
        dur = float(o.get("original_duration", 0.0))
        if o["optype"] in ("Local CNOT", "Re-CNOT"):
            r = {"Time": t, "CNOT": True, "SIdx": int(o["atom0"]), "TIdx": int(o["atom1"]),
                 "SPos": pos0, "SNextPos": pos0, "TPos": pos1, "TNextPos": pos1,
                 "BlockID": bid, "_dur": dur, "_optype": o["optype"]}
        else:
            r = {"Time": t, "CNOT": False, "SIdx": int(o["atom0"]), "TIdx": int(o["atom0"]),
                 "SPos": pos0, "SNextPos": pos1, "TPos": pos0, "TNextPos": pos0,
                 "BlockID": bid, "_dur": dur, "_optype": o["optype"]}
        pipe.append(r)
    init_ch = {(a, b): 0 for a in chips for b in chips if a != b}
    return pipe, init_ch


def _op_duration_under_hp(optype: str, hp) -> float:
    if optype in {"Local CNOT", "Local SWAP"}:
        return float(hp.time_2Q) + float(hp.time_move)
    if optype == "Transfer":
        return float(hp.time_transfer) + float(hp.time_move)
    if optype == "Re-CNOT":
        return float(hp.time_int_2Q)
    if optype == "RELOCATE":
        return float(hp.time_int_SWAP)
    if optype == "MOVE":
        return float(hp.time_move)
    return 1e-12


def _extra_opt_cycles(payload, arch_dir: str):
    pipe, init_ch = _schedule_to_pipeline_from_payload(payload)
    res = qucomm_parallel_schedule(
        pipe, init_ch, min_comm_value=-1000, max_comm_value=2000,
        link_epr_capacity=link_epr_capacity(arch_dir), debug=False,
    )
    by_cycle: dict[int, list[str]] = {}
    for r in res:
        by_cycle.setdefault(r["Time"], []).append(r["_optype"])
    return [by_cycle[c] for c in sorted(by_cycle)]


def _extra_opt_latency_under_hp(cycles, hp) -> float:
    cum = 0.0
    for cycle in cycles:
        cum += max((_op_duration_under_hp(t, hp) for t in cycle), default=0.0)
    return cum


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep EPR serialization fraction and plot program latency (Figure 19)."
    )
    parser.add_argument("--mapping", default="MinCut")
    parser.add_argument("--benchmark", default="qaoa_fc_n240")
    parser.add_argument("--arch", default="S40C5-3x3")
    parser.add_argument("--stages", default="QuComm,IRIS")
    parser.add_argument("--serialization_pct", default=DEFAULT_FRACTION_GRID)
    parser.add_argument("--epr_gen_us", type=float, default=EPR_GEN_US_DEFAULT)
    parser.add_argument("--time_move_us", type=float, default=DEFAULT_TIME_MOVE_US)
    args = parser.parse_args()

    out = output_dir("section6")
    stage_labels = [s.strip() for s in args.stages.split(",") if s.strip()]
    fractions_pct = [float(x) for x in args.serialization_pct.split(",")]
    epr_gen_us = float(args.epr_gen_us)
    time_move_s = float(args.time_move_us) * 1e-6

    payloads: dict[str, dict] = {}
    extra_cycles: dict[str, list] = {}
    for stage in stage_labels:
        sched_path = _schedule_path(args.mapping, stage, args.benchmark, args.arch)
        if sched_path is None:
            note = out / "figure19_epr_pair_generation_latency.MISSING.txt"
            note.write_text(f"missing schedule.json for {stage} "
                            f"({args.mapping}/{stage}/{args.benchmark}-{args.arch})\n")
            print(f"[stub] {note}")
            return
        payloads[stage] = _load_json(sched_path)
        if stage.startswith("IRIS") and stage != "IRIS-noEES":
            try:
                extra_cycles[stage] = _extra_opt_cycles(payloads[stage], args.arch)
                print(f"  {stage} extra-opt: {len(extra_cycles[stage])} cycles "
                      f"(was {len(payloads[stage]['ops'])} ops)")
            except Exception as exc:
                print(f"  extra-opt cycles failed for {stage}: {exc}")

    results: dict[str, list] = {s: [] for s in stage_labels}
    for hidden_pct in fractions_pct:
        hidden_frac = hidden_pct / 100.0
        exposed_epr_us = (1.0 - hidden_frac) * epr_gen_us
        exposed_epr_s = exposed_epr_us * 1e-6
        for stage in stage_labels:
            payload = payloads[stage]
            hp = build_hyperparameters_from_snapshot(payload.get("args_snapshot"), {})
            hp.time_move = time_move_s
            hp.time_transfer = exposed_epr_s
            hp.time_int_2Q = BASE_TIME_INT_2Q + exposed_epr_s
            hp.time_int_SWAP = BASE_TIME_INT_SWAP + exposed_epr_s
            if stage in extra_cycles:
                latency = _extra_opt_latency_under_hp(extra_cycles[stage], hp)
            else:
                _, summary = replay_saved_schedule(payload, hp)
                latency = float(summary["total_execution_time"])
            results[stage].append((hidden_pct, exposed_epr_us, latency))
            print(f"  {stage} @ hidden={hidden_pct:.0f}% "
                  f"exposed_EPR={exposed_epr_us:.1f}us: latency={latency:.6f}s")

    csv_path = out / "figure19_epr_pair_generation_latency.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["serialization_pct", "exposed_epr_us", "stage",
                         "program_latency_s"])
        for stage in stage_labels:
            for pct, exposed_us, lat in results[stage]:
                writer.writerow([f"{pct:.0f}", f"{exposed_us:.2f}", stage,
                                 f"{lat:.9f}"])
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

    fig, ax = plt.subplots(figsize=(5, 2.052))
    for stage in stage_labels:
        xs = [pt[0] for pt in results[stage]]
        ys = [pt[2] for pt in results[stage]]
        color = STAGE_COLORS.get(stage, "#888888")
        label = STAGE_DISPLAY.get(stage, stage)
        marker = STAGE_MARKERS.get(stage, "o")
        mec = "black" if stage == "QuComm" else color
        msize = 13 if marker == "*" else 9
        ax.plot(xs, ys, marker=marker, markersize=msize, color=color,
                linewidth=2, label=label, zorder=5,
                markeredgecolor=mec, markeredgewidth=0.8)

    ax.set_xlim(-2, 102)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("Fraction of Hidden EPR Generation Latency (%)")
    ax.set_ylabel("Latency (s)")
    ax.legend(fontsize=13, frameon=False, loc="center left",
              bbox_to_anchor=(-0.01, 0.6),
              borderpad=0.2, handletextpad=0.3, labelspacing=0.2,
              handlelength=1.2)
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    pdf_path = out / "figure19_epr_pair_generation_latency.pdf"
    plt.tight_layout()
    fig.savefig(pdf_path, dpi=600, format="pdf", bbox_inches="tight")
    fig.savefig(pdf_path.with_suffix(".png"), dpi=150, format="png",
                bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {pdf_path}")
    print(f"wrote {pdf_path.with_suffix('.png')}")


if __name__ == "__main__":
    main()
