#!/usr/bin/env python3
"""§6.10 Table 7 — Effective teleportation count (T_eff) and logical cycle time
(L_cycle in ms) on a 2×2 DQC for three QEC codes:
  - Bivariate Bicycle [[72,12,6]]
  - Color [[61,1,9]]
  - Surface [[49,1,7]]
QuComm vs IRIS (IRIS-opt0-EEE).

Source: per-(code, arch) result JSONs under
  results/_qec_codes/qec_codes_2x2_vs_mono_<code>_<arch>/.../results*.json
(the paper QEC sweep; copied into the artifact for self-containment).
The vendored `_build_qec_summary.py` reads those JSONs and emits
`qec_codes_2x2_vs_mono_summary.md`; this wrapper invokes it, parses the
headline section, and emits the paper's compact Table 7 (T_eff + L_cycle for
both stages, plus a relative row).

Logical cycle time (L_cycle) is the latency of the syndrome-extraction
schedule; the IRIS value uses the EES-replay latency, matching the latency
definition used throughout the paper.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os

from _lib import ARTIFACT_ROOT, RESULTS_BASE, load_json, output_dir, python_env, result_json, run

# Paper QEC sweep lives alongside the main results tree.
# Pinned to the artifact root (not RESULTS_BASE.parent) so that reading a
# dataset tree via --from_dataset never resolves paths near the dataset.
QEC_BASE = Path(os.environ.get("QEC_BASE", ARTIFACT_ROOT / "results" / "_qec_codes"))
SUMMARY_MD = QEC_BASE / "qec_codes_2x2_vs_mono_summary.md"
VENDOR_SCRIPT = Path(__file__).with_name("_build_qec_summary.py")
CODE_DISPLAY = {
    "BB [[72,12,6]]": "Bivariate Bicycle [[72,12,6]]",
    "Color [[61,1,9]]": "Color [[61,1,9]]",
    "Surface d=7": "Surface [[49,1,7]]",
}
ROW_ORDER = ["BB [[72,12,6]]", "Color [[61,1,9]]", "Surface d=7"]

HEADER = ["Code", "QuComm T_eff", "QuComm L_cycle (ms)",
          "IRIS T_eff", "IRIS L_cycle (ms)"]




# Primary source: the QEC runs in the main results tree (present both in the
# IRIS-dataset and in results/_full after `bash scripts/table_7.sh`).
QEC_RUNS = [
    ("Bivariate Bicycle [[72,12,6]]", "bb_72_12_6_n144", "S46C5-2x2"),
    ("Color [[61,1,9]]", "color_61_1_9_n121", "S42C5-2x2"),
    ("Surface [[49,1,7]]", "surface_code_n97", "S33C4-2x2"),
]


def _rows_from_results_tree() -> list[list[str]] | None:
    """Compute Table 7 directly from the QuComm / IRIS run results.

    L_cycle is the latency of the syndrome-extraction schedule: the stored
    schedule latency for QuComm, and the EES-replay latency for IRIS (the
    IRIS latency definition used throughout the paper). The Relative row is
    the geometric mean of the per-code IRIS/QuComm ratios.

    Returns None when any of the six runs is missing, so the caller can fall
    back to the bundled QEC sweep or (last resort) the reference values.
    """
    from _lib import extra_opt_json
    rows = [HEADER]
    teff_ratios: list[float] = []
    lct_ratios: list[float] = []
    for display, bench, archdir in QEC_RUNS:
        pair = []
        for variant in ("QuComm", "IRIS-opt1"):
            path = result_json(variant, archdir, "ILP", bench)
            if path is None:
                return None
            d = load_json(path)
            teleports = int(d.get("num_state_teleportations", 0))
            lct_ms = float(d.get("total_execution_time", 0.0)) * 1000.0
            if variant == "IRIS-opt1":
                eo = extra_opt_json(archdir, "ILP", bench)
                if eo is not None:
                    lct_ms = float(load_json(eo)["wall_time_ms_extra"])
            pair.append((teleports, lct_ms))
        (qc_t, qc_l), (ir_t, ir_l) = pair
        rows.append([display, f"{qc_t}", f"{qc_l:.0f}", f"{ir_t}", f"{ir_l:.0f}"])
        teff_ratios.append(ir_t / qc_t)
        lct_ratios.append(ir_l / qc_l)
    def _gmean(xs: list[float]) -> float:
        prod = 1.0
        for x in xs:
            prod *= x
        return prod ** (1.0 / len(xs))

    rows.append(["Relative", "1.00", "1.00",
                 f"{_gmean(teff_ratios):.2f}", f"{_gmean(lct_ratios):.2f}"])
    return rows

def _emit(out: Path, rows: list[list[str]]) -> None:
    """Write the Table-7 rows (header first) as CSV and a LaTeX tabular."""
    csv_path = out / "table7_qec_logical_cycle.csv"
    tex_path = out / "table7_qec_logical_cycle.tex"
    with csv_path.open("w", newline="") as fh:
        csv.writer(fh).writerows(rows)
    with tex_path.open("w") as fh:
        fh.write(r"\begin{tabular}{|l|c|c|c|c|}\hline" + "\n")
        fh.write(" & ".join(rows[0]) + r" \\\hline" + "\n")
        for r in rows[1:]:
            fh.write(" & ".join(r) + r" \\\hline" + "\n")
        fh.write(r"\end{tabular}" + "\n")
    print(f"Saved: {csv_path}")
    print(f"Saved: {tex_path}")


def _parse_headline(md_text: str) -> dict[str, dict[str, dict[str, float]]]:
    """Return {code: {stage: {teff, lct}}} parsed from the headline table."""
    section_re = re.compile(r"## Headline:.*?\n(.*?)(?=\n## |\Z)", re.S)
    section = section_re.search(md_text)
    if not section:
        raise SystemExit("Headline section not found in QEC summary.md")
    parsed: dict[str, dict[str, dict[str, float]]] = {}
    # Lines look like: | Surface d=7 | QuComm | 589 | 745.64 | 106.52 | 1.000× | 1.000× |
    for line in section.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0].startswith("---") or cells[0] == "Code":
            continue
        code, stage, teleports, lct = cells[0], cells[1], cells[2], cells[3]
        try:
            t = float(teleports)
            l = float(lct)
        except ValueError:
            continue
        parsed.setdefault(code, {})[stage] = {"teff": t, "lct": l}
    return parsed


def main() -> None:
    out = output_dir("section6")
    computed = _rows_from_results_tree()
    if computed is not None:
        _emit(out, computed)
        return
    if not QEC_BASE.exists():
        # No QEC run data anywhere: emit nothing but an explanation. Table 7
        # is only ever produced from actual run results (main tree or the
        # bundled sweep) — never from stored constants.
        note = out / "table7_qec_logical_cycle.MISSING.txt"
        note.write_text(
            "Table 7 needs the QEC runs (QuComm/IRIS x BB, Color, Surface).\n"
            "Provide them via the IRIS-dataset (get_data_all.sh --from_dataset)\n"
            "or re-run them with: bash scripts/table_7.sh\n")
        print(f"[skip] {note} — no QEC run data found")
        return

    # Always (re)build the summary so the LCT model params are explicit.
    run([
        python_env(), str(VENDOR_SCRIPT),
        "--results-base", str(QEC_BASE),
        "--output", str(SUMMARY_MD),
        "--t_meas_reset_ms_per_round", "1.0",
        "--t_final_meas_ms", "1.0",
    ])
    if not SUMMARY_MD.exists():
        raise SystemExit(f"vendor script did not produce {SUMMARY_MD}")

    data = _parse_headline(SUMMARY_MD.read_text())

    rows = [HEADER]
    qc_lct_sum = qc_teff_sum = iris_lct_sum = iris_teff_sum = 0.0
    for code in ROW_ORDER:
        if code not in data:
            print(f"[warn] {code} missing from headline", file=sys.stderr)
            rows.append([CODE_DISPLAY.get(code, code), "n/a", "n/a", "n/a", "n/a"])
            continue
        qc = data[code].get("QuComm", {})
        ir = data[code].get("IRIS-opt0-EEE", {})
        rows.append([
            CODE_DISPLAY.get(code, code),
            f"{int(qc.get('teff', 0))}",
            f"{qc.get('lct', 0.0):.0f}",
            f"{int(ir.get('teff', 0))}",
            f"{ir.get('lct', 0.0):.0f}",
        ])
        qc_teff_sum += qc.get("teff", 0.0)
        iris_teff_sum += ir.get("teff", 0.0)
        qc_lct_sum += qc.get("lct", 0.0)
        iris_lct_sum += ir.get("lct", 0.0)

    rel_teff = iris_teff_sum / qc_teff_sum if qc_teff_sum > 0 else float("nan")
    rel_lct = iris_lct_sum / qc_lct_sum if qc_lct_sum > 0 else float("nan")
    rows.append(["Relative", "1.00", "1.00", f"{rel_teff:.2f}", f"{rel_lct:.2f}"])

    _emit(out, rows)


if __name__ == "__main__":
    main()
