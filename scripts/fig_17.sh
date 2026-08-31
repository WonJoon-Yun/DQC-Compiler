#!/usr/bin/env bash
# Fig 17: Re-CNOT to RELOCATE cost-ratio (alpha) sensitivity for qaoa_3reg
# n120 on a 2x2 DQC. Post-hoc analysis: retimes the existing QuComm and IRIS
# schedules under a Re-CNOT rewrite (fires for alpha <= 1.5) — no re-routing.
#
# Runs the three variants first if their results are missing (same runs as
# Table 5), then computes the alpha table and renders the figure.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${BENCH:-qaoa_3reg_n120}"
ARCH="${ARCH:-F120}"
MAPPER="${MAPPER:-ILP}"

qasm="$BENCH_DIR/qaoa_3reg/${BENCH}.qasm"
if [[ ! -f "$qasm" ]]; then
  { echo "[missing] $qasm -- run: bash scripts/ensure_dataset.sh"; exit 2; }
fi

qu_dir="$(result_path QuComm "$ARCH" "$MAPPER" "$BENCH")"
ir_dir="$(result_path IRIS-opt1 "$ARCH" "$MAPPER" "$BENCH")"
if ! ls "$qu_dir"/[Ss]chedule*.json* >/dev/null 2>&1 || \
   ! ls "$ir_dir"/[Ss]chedule*.json* >/dev/null 2>&1; then
  bash "$SCRIPT_DIR/run_all_variants.sh" "$BENCH" "$ARCH" "$MAPPER"
fi

TABLE="$RESULTS_DIR/alpha_sweep/alpha_latency_table.json"
python "$SCRIPT_DIR/alpha_retime.py" \
       --qucomm "$qu_dir" --iris "$ir_dir" --out "$TABLE"

python "$SCRIPT_DIR/plot/fig_17_alpha.py" \
       --table "$TABLE" --output "$FIGURES_DIR/fig_17.pdf"
echo "Fig 17 -> $FIGURES_DIR/fig_17.pdf"
