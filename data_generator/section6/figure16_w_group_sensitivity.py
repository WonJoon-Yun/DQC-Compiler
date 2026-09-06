#!/usr/bin/env python3
"""§6.7 Fig 16 — Sensitivity of T_eff/Latency/compile time to
    w   (qucomm_gate_lookahead_beam_width) ∈ {2, 4, 8, 16, 32}
    |G| (qucomm_gate_lookahead_depth)      ∈ {2, 4, 6, 8, 10}

Collects the sweep runs from the dataset-layout results tree
    <RESULTS_BASE>/MinCut/{QuComm,IRIS}-bw<W>/<bench>-<archdir>/
    <RESULTS_BASE>/MinCut/{QuComm,IRIS}-lh<G>/<bench>-<archdir>/
(shipped in the IRIS-dataset; regenerable via `bash scripts/fig_16.sh`),
emits one CSV row per run, and renders the paper's 2x3 figure:
per sweep point, each benchmark's IRIS value is normalized to the QuComm run
at the same setting; the line is the geometric mean across benchmarks and the
band is the interquartile range. Compile time is absolute (log scale). The
IRIS latency uses the EES replay (extra_opt) when available, matching the
paper's latency definition.

Output: output/section6/figure16_w_group_sensitivity.{csv,pdf,png}
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import RESULTS_BASE, compute_teff, output_dir

SWEEP_RE = re.compile(r"^(QuComm|IRIS)-(bw|lh)(\d+)$")
RUN_RE = re.compile(r"^(.*)-(S\d+C\d+-\d+x\d+)$")
BEAM_VALUES = [2, 4, 8, 16, 32]
LOOKAHEAD_VALUES = [2, 4, 6, 8, 10]
BEAM_COLOR = "#111FA2"
LOOKAHEAD_COLOR = "#F13E93"
TIME_TICK_SPECS = [(1.0, "1s"), (10.0, "10s"), (60.0, "1m"), (600.0, "10m"),
                   (3600.0, "1h"), (36000.0, "10h"), (86400.0, "1day")]


def _load_results(run_dir: Path) -> dict | None:
    for p in sorted(run_dir.glob("results*.json")):
        return json.loads(p.read_text())
    for p in sorted(run_dir.glob("results*.json.gz")):
        return json.loads(gzip.decompress(p.read_bytes()))
    return None


def _compile_total(d: dict) -> float:
    return (
        float(d.get("compile_time_total", 0) or 0)
        or sum(float(d.get(k, 0) or 0) for k in (
            "compile_time_mapper", "compile_time_router",
            "compile_time_circuit_rewriting",
            "compile_time_block_updating",
            "compile_time_communication_fusion",
            "compile_time_for_block_scheduling",
            "compile_time_for_early_execution",
        ))
    )


def _ees_latency_s(sched_name: str, run_name: str, raw_s: float) -> float:
    """EES replay latency for an IRIS sweep run, from the run dir's
    extra_opt.json or the $EXTRA_OPT_CACHE sidecar; raw latency otherwise."""
    candidates = [RESULTS_BASE / "MinCut" / sched_name / run_name / "extra_opt.json"]
    cache = os.environ.get("EXTRA_OPT_CACHE")
    if cache:
        candidates.append(Path(cache) / "MinCut" / sched_name / run_name / "extra_opt.json")
    for p in candidates:
        if p.exists():
            try:
                return float(json.loads(p.read_text())["wall_time_ms_extra"]) / 1000.0
            except (KeyError, ValueError, json.JSONDecodeError):
                pass
    return raw_s


def _geomean(values: list[float]) -> float:
    vals = [v for v in values if v > 0]
    if not vals:
        return 0.0
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def _collect() -> list[dict]:
    rows: list[dict] = []
    mincut = RESULTS_BASE / "MinCut"
    if not mincut.exists():
        return rows
    for sched_dir in sorted(mincut.iterdir()):
        m = SWEEP_RE.match(sched_dir.name)
        if not m or not sched_dir.is_dir():
            continue
        variant, axis, value = m.group(1), m.group(2), int(m.group(3))
        for run_dir in sorted(sched_dir.iterdir()):
            rm = RUN_RE.match(run_dir.name)
            if not rm or not run_dir.is_dir():
                continue
            d = _load_results(run_dir)
            if d is None:
                continue
            raw_lat = float(d.get("total_execution_time", 0) or 0)
            lat = raw_lat
            if variant == "IRIS":
                lat = _ees_latency_s(sched_dir.name, run_dir.name, raw_lat)
            rows.append({
                "variant": variant,
                "axis": "w" if axis == "bw" else "G",
                "value": value,
                "bench": rm.group(1),
                "archdir": rm.group(2),
                "teff": compute_teff(d),
                "total_execution_time_s": raw_lat,
                "latency_s": lat,
                "compile_time_total_s": _compile_total(d),
            })
    return rows


def _series(rows: list[dict], axis: str, values: list[int]):
    """Per sweep point: per-bench IRIS/QuComm ratios -> geomean + IQR."""
    out = {"teff": [], "lat": [], "compile": []}
    for v in values:
        iris = {r["bench"]: r for r in rows
                if r["axis"] == axis and r["value"] == v and r["variant"] == "IRIS"}
        base = {r["bench"]: r for r in rows
                if r["axis"] == axis and r["value"] == v and r["variant"] == "QuComm"}
        teff_r, lat_r, compiles = [], [], []
        for bench, s in iris.items():
            b = base.get(bench)
            if b is None:
                continue
            if b["teff"] > 0:
                teff_r.append(s["teff"] / b["teff"])
            if b["latency_s"] > 0:
                lat_r.append(s["latency_s"] / b["latency_s"])
            if s["compile_time_total_s"] > 0:
                compiles.append(s["compile_time_total_s"])
        for key, ratios in (("teff", teff_r), ("lat", lat_r), ("compile", compiles)):
            out[key].append(ratios)
    return out


def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * q
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _plot(rows: list[dict], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = "Times New Roman"
    plt.rcParams["font.size"] = 12
    plt.rcParams["axes.titlesize"] = 12
    plt.rcParams["axes.labelsize"] = 12
    plt.rcParams["xtick.labelsize"] = 11
    plt.rcParams["ytick.labelsize"] = 11
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42

    fig, axes = plt.subplots(2, 3, figsize=(5, 3.3 * 0.95))
    panels = [
        (0, "w", BEAM_VALUES, BEAM_COLOR, "# Solutions"),
        (1, "G", LOOKAHEAD_VALUES, LOOKAHEAD_COLOR, "Group Size"),
    ]
    for row_idx, axis, values, color, xlabel in panels:
        series = _series(rows, axis, values)
        xs = list(range(len(values)))
        for col_idx, (key, ylabel, marker) in enumerate((
                ("teff", r"Norm. $T_{eff}$", "D"),
                ("lat", "Norm. Latency", "o"),
                ("compile", "Compile Time", "^"))):
            ax = axes[row_idx][col_idx]
            geo, q25, q75 = [], [], []
            for ratios in series[key]:
                vals = sorted(v for v in ratios if v > 0)
                geo.append(_geomean(vals))
                q25.append(_percentile(vals, 0.25))
                q75.append(_percentile(vals, 0.75))
            ax.fill_between(xs, q25, q75, color=color, alpha=0.15, zorder=2)
            ax.plot(xs, q25, color=color, alpha=0.4, linewidth=0.8,
                    linestyle="--", zorder=3)
            ax.plot(xs, q75, color=color, alpha=0.4, linewidth=0.8,
                    linestyle="--", zorder=3)
            ax.plot(xs, geo, marker=marker, markersize=7, color=color,
                    linewidth=2, zorder=5)
            ax.set_xticks(xs)
            ax.set_xticklabels([str(v) for v in values])
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.grid(axis="y", linestyle="--", alpha=0.3)
            if key == "compile":
                ax.set_yscale("log")
                lo = min(v for v in q25 if v > 0) / 1.5
                hi = max(q75) * 1.5
                ticks = [t for t, _ in TIME_TICK_SPECS if lo <= t <= hi]
                if ticks:
                    ax.set_ylim(min(lo, ticks[0] * 0.8), max(hi, ticks[-1] * 1.2))
                    ax.set_yticks(ticks)
                    ax.set_yticklabels([lbl for t, lbl in TIME_TICK_SPECS
                                        if lo <= t <= hi], fontsize=11)
                ax.minorticks_off()
            else:
                ax.axhline(y=1.0, color="gray", linestyle="--", linewidth=0.8,
                           alpha=0.5)
                ax.set_ylim(0.0, 1.05)
                ax.set_yticks([0.0, 0.5, 1.0])
                ax.set_yticklabels(["0", "0.5", "1"], fontsize=11)

    plt.tight_layout()
    fig.savefig(out / "figure16_w_group_sensitivity.pdf", dpi=600,
                format="pdf", bbox_inches="tight")
    fig.savefig(out / "figure16_w_group_sensitivity.png", dpi=150,
                format="png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    out = output_dir("section6")
    csv_path = out / "figure16_w_group_sensitivity.csv"
    rows = _collect()
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["variant", "axis", "value", "bench",
                                          "archdir", "teff",
                                          "total_execution_time_s",
                                          "latency_s", "compile_time_total_s"])
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["axis"], r["variant"],
                                             r["value"], r["bench"])):
            rr = dict(r)
            rr["teff"] = f"{r['teff']:.2f}"
            w.writerow(rr)
    if rows:
        _plot(rows, out)
        print(f"wrote {csv_path} ({len(rows)} sweep runs)")
        print(f"wrote {out / 'figure16_w_group_sensitivity.pdf'}")
    else:
        print(f"[stub] {csv_path} — no sweep runs found under "
              f"{RESULTS_BASE}/MinCut/(QuComm|IRIS)-(bw|lh)*/. "
              f"Run `bash scripts/fig_16.sh` first (see its runtime warning).")


if __name__ == "__main__":
    main()
