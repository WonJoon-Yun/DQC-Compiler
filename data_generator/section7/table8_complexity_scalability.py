#!/usr/bin/env python3
"""§7 Table 8 — Complexity analysis and performance of IRIS relative to
QuComm across {500q on 2x2, 800q on 2x3, 1100q on 3x3} (S180C18 chips).

Per architecture the paper reports IRIS/QuComm ratios for:
  Memory            routing peak memory, from the -memtrace reruns
  T_eff             effective teleportation count
  Compile Time      total compile time
  Schedule Latency  program schedule latency (IRIS uses the EES latency)
  Program Runtime   compile time + 50K shots x schedule latency

Memory, T_eff, Compile Time, and Schedule Latency ratios are machine
independent. The Program Runtime ratio mixes compile time (wall clock,
machine dependent) with schedule latency, so it varies with the machine that
produced the compile timings.

Output: output/section7/table8_complexity_scalability.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _lib import extra_opt_json, load_json, output_dir, result_json

ARCH_CONFIGS = [("F500", 500), ("F800", 800), ("F1100", 1100)]
MAPPER = "ILP"
FAMILY = "qaoa_3reg"
SHOTS = 50_000


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


def _teff(d: dict) -> float:
    return (float(d.get("num_state_teleportations", 0) or 0)
            + float(d.get("num_gate_teleportations", 0) or 0))


def _load(variant: str, arch: str, bench: str) -> dict | None:
    p = result_json(variant, arch, MAPPER, bench)
    return load_json(p) if p else None


def main() -> None:
    out = output_dir("section7")
    csv_path = out / "table8_complexity_scalability.csv"
    rows = [["arch", "program_qubits", "memory_x", "teff_x", "compile_x",
             "schedule_latency_x", "program_runtime_x"]]
    found = 0
    for (arch, n) in ARCH_CONFIGS:
        bench = f"{FAMILY}_n{n}"
        qc = _load("QuComm", arch, bench)
        ir = _load("IRIS-opt1", arch, bench)
        if qc is None or ir is None:
            rows.append([arch, n, "", "", "", "", ""])
            continue
        found += 1

        qc_mem = _load("QuComm-memtrace", arch, bench)
        ir_mem = _load("IRIS-memtrace", arch, bench) or _load(
            "IRIS-opt1-memtrace", arch, bench)
        mem = ""
        if qc_mem and ir_mem:
            qk = float(qc_mem.get("routing_peak_traced_kb", 0) or 0)
            ik = float(ir_mem.get("routing_peak_traced_kb", 0) or 0)
            if qk:
                mem = f"{ik / qk:.2f}"

        teff = f"{_teff(ir) / _teff(qc):.2f}"

        qc_compile = _compile_total(qc)
        ir_compile = _compile_total(ir)
        compile_x = f"{ir_compile / qc_compile:.0f}" if qc_compile else ""

        qc_lat = float(qc.get("total_execution_time", 0) or 0)
        ir_lat = float(ir.get("total_execution_time", 0) or 0)
        eo = extra_opt_json(arch, MAPPER, bench)
        if eo is not None:
            ir_lat = float(load_json(eo)["wall_time_ms_extra"]) / 1000.0
        lat = f"{ir_lat / qc_lat:.2f}" if qc_lat else ""

        runtime = ""
        if qc_compile and qc_lat:
            runtime = f"{(ir_compile + SHOTS * ir_lat) / (qc_compile + SHOTS * qc_lat):.2f}"

        rows.append([arch, n, mem, teff, compile_x, lat, runtime])
        print(f"{arch}: QuComm compile {qc_compile:.1f}s lat {qc_lat * 1000:.1f}ms"
              f" | IRIS compile {ir_compile:.1f}s lat {ir_lat * 1000:.1f}ms")

    with csv_path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    if found == 0:
        print(f"[stub] {csv_path} -- no large-scale data; run table_8.sh first")
    else:
        print(f"wrote {csv_path} ({found} archs)")


if __name__ == "__main__":
    main()
