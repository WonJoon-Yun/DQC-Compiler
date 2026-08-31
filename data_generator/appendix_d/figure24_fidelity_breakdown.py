#!/usr/bin/env python3
"""Appendix D / Fig 24 — fidelity breakdown, QuComm vs IRIS, for the
32-qubit QAOA-3reg program on a 2x2 DQC (old-model architecture 2x2-2x2-3).

Inputs (dataset layout, gz-aware):
    <RESULTS_BASE>/MinCut/QuComm/qaoa_3reg_n32-2x2-2x2-3/results.json[.gz]
    <RESULTS_BASE>/MinCut/IRIS/qaoa_3reg_n32-2x2-2x2-3/results.json[.gz]
        (+ schedule.json[.gz] for the IRIS EES-replay latency)

These runs use the old-model architecture and are shipped in the
IRIS-dataset; they are not re-run by the artifact. Run this script in
dataset mode (`get_data_all.sh --from_dataset`).

Formula:
  F_total = F_2Q^num_local_CNOTs
          * F_relocation^num_relocates
          * F_1Q^num_1Q
          * F_transfer^(num_local_CNOTs + num_relocates)
          * exp(-latency * num_qubits / T1)

Output: output/appendix_d/figure24_fidelity_breakdown.{csv,pdf,png}
"""
from __future__ import annotations

import gzip
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import RESULTS_BASE, output_dir

BENCH = "qaoa_3reg_n32"
ARCH = "2x2-2x2-3"

# -- Fidelity model parameters ------------------------------------------------
F_2Q = 0.995
F_1Q = 0.9992
F_TRANSFER = 0.999
F_REMOTE_2Q = 0.98
F_RELOCATION = 0.985
T1 = 1.5  # coherence time (seconds)

# num_1Q: from the QAOA-3reg n32 circuit (32 Hadamard + 32 RX = 64)
NUM_1Q = 64


def load_json(path: Path):
    if str(path).endswith(".gz"):
        return json.loads(gzip.decompress(path.read_bytes()))
    return json.loads(path.read_text())


def run_file(run_dir: Path, name: str) -> Path | None:
    for cand in (run_dir / name, run_dir / (name + ".gz")):
        if cand.exists():
            return cand
    return None


def link_epr_capacity(arch_dir: str, default: int = 5) -> int:
    m = re.search(r"C(\d+)", arch_dir or "")
    return int(m.group(1)) if m else default


def schedule_to_pipeline(schedule_path: Path):
    """Convert schedule.json into the pipeline rows consumed by
    qucomm_parallel_schedule."""
    data = load_json(schedule_path)
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


def ees_replay_latency(schedule_path: Path, arch_dir: str) -> float:
    """Post-hoc EES replay latency (original parameters: min=-1000, max=2000,
    link cap from the arch dir)."""
    from _early_execution import qucomm_parallel_schedule
    pipe, init_ch = schedule_to_pipeline(schedule_path)
    res = qucomm_parallel_schedule(pipe, init_ch, min_comm_value=-1000,
                                   max_comm_value=2000,
                                   link_epr_capacity=link_epr_capacity(arch_dir),
                                   debug=False)
    by_cycle: dict[int, list] = {}
    for r in res:
        by_cycle.setdefault(r["Time"], []).append(r)
    return sum(max((r["_dur"] for r in by_cycle[c]), default=0.0)
               for c in sorted(by_cycle))


def load_metrics(results_path: Path) -> dict:
    d = load_json(results_path)
    return {
        "num_local_cnots": d["num_local_cnots"],
        "num_relocates": d["num_state_teleportations"],
        "num_recnots": d["num_gate_teleportations"],
        "num_1Q": NUM_1Q,
        "latency": d["total_execution_time"],
        "num_qubits": d["fidelity_model"]["num_qubits"],
    }


def compute_breakdown(m: dict) -> dict:
    f_local_2q = F_2Q ** m["num_local_cnots"]
    f_relocation = F_RELOCATION ** m["num_relocates"]
    f_recnot = F_REMOTE_2Q ** m["num_recnots"]
    f_1q = F_1Q ** m["num_1Q"]
    f_transfer = F_TRANSFER ** (m["num_local_cnots"] + m["num_relocates"])
    f_deco = math.exp(-m["latency"] * m["num_qubits"] / T1)
    f_total = f_local_2q * f_relocation * f_recnot * f_1q * f_transfer * f_deco
    return {
        "Single\nQubit": f_1q,
        "Transfer": f_transfer,
        "Local\nCNOT": f_local_2q,
        "Teleportation": f_relocation,
        "Decoherence": f_deco,
        "Overall": f_total,
    }


def main() -> None:
    out = output_dir("appendix_d")
    run_qc = RESULTS_BASE / "MinCut" / "QuComm" / f"{BENCH}-{ARCH}"
    run_ir = RESULTS_BASE / "MinCut" / "IRIS" / f"{BENCH}-{ARCH}"
    res_qc = run_file(run_qc, "results.json")
    res_ir = run_file(run_ir, "results.json")
    if res_qc is None or res_ir is None:
        note = out / "figure24_fidelity_breakdown.MISSING.txt"
        note.write_text(
            "Figure 24 needs the old-model runs "
            f"MinCut/{{QuComm,IRIS}}/{BENCH}-{ARCH}/, which ship in the\n"
            "IRIS-dataset and are not re-run by the artifact.\n"
            "Run: bash scripts/get_data_all.sh --from_dataset\n")
        print(f"[stub] {note}")
        return

    m_qc = load_metrics(res_qc)
    m_ir = load_metrics(res_ir)
    sched_ir = run_file(run_ir, "schedule.json")
    if sched_ir is not None:
        try:
            new_lat = ees_replay_latency(sched_ir, ARCH)
            print(f"  IRIS extra-opt latency: {m_ir['latency']:.6f}s -> {new_lat:.6f}s")
            m_ir["latency"] = new_lat
        except Exception as exc:
            print(f"  extra-opt failed: {exc}")
    bd_qc = compute_breakdown(m_qc)
    bd_ir = compute_breakdown(m_ir)

    print(f"{'Component':<30} {'QuComm':>12} {'IRIS':>12}")
    print("-" * 56)
    for key in bd_qc:
        print(f"{key:<30} {bd_qc[key]:>12.6f} {bd_ir[key]:>12.6f}")

    labels = list(bd_qc.keys())
    csv_path = out / "figure24_fidelity_breakdown.csv"
    with open(csv_path, "w") as fh:
        fh.write("component,QuComm,IRIS\n")
        for k in labels:
            fh.write(f"{k.replace(chr(10), ' ')},{bd_qc[k]:.6f},{bd_ir[k]:.6f}\n")
    print(f"wrote {csv_path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
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
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42

    vals_qc = [bd_qc[k] for k in labels]
    vals_ir = [bd_ir[k] for k in labels]
    x = np.arange(len(labels))
    bar_w = 0.35

    fig, ax = plt.subplots(figsize=(5, 2.2))
    fig.subplots_adjust(bottom=0.28, top=0.95, left=0.08, right=0.98)
    bars_qc = ax.bar(x - bar_w / 2, vals_qc, bar_w, label="QuComm",
                     color="#FFEABB", edgecolor="black", linewidth=0.4, zorder=3)
    bars_ir = ax.bar(x + bar_w / 2, vals_ir, bar_w, label="IRIS",
                     color="#346739", edgecolor="black", linewidth=0.4, zorder=3)
    for bars in (bars_qc, bars_ir):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h, f"{h:.2f}",
                    ha="center", va="bottom", fontsize=13, rotation=45)
    sep_x = labels.index("Decoherence") + 0.5
    ax.axvline(x=sep_x, color="#cccccc", linestyle="-", linewidth=0.8, zorder=1)
    tick_labels = [r"$\bf{Overall}$" if l == "Overall" else l for l in labels]
    ax.set_xticks(x)
    ax.set_xticklabels(tick_labels, fontsize=12, rotation=20)
    ax.tick_params(axis="x", pad=0)
    ax.set_yticks([0, 0.5, 1.0], ["0", "0.5", "1"])
    ax.set_xlabel("Fidelity Components")
    ax.set_ylabel("Fidelity")
    ax.set_ylim(0, 1.26)
    ax.legend(loc="upper right", frameon=True, fontsize=13, framealpha=1)
    ax.grid(axis="y", linestyle="--", linewidth=0.4, alpha=0.3)
    ax.set_axisbelow(True)

    pdf_path = out / "figure24_fidelity_breakdown.pdf"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(out / "figure24_fidelity_breakdown.png", dpi=200,
                bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {pdf_path}")


if __name__ == "__main__":
    main()
