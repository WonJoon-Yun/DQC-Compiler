#!/usr/bin/env bash
# Fig 15: scaling study — chip-size sweep (panel a) and number-of-chips
# sweep (panel b) for qaoa_3reg. Re-runs the sweep tuples from the imported
# mapping results, then renders via data_generator/section6/figure15_scaling.py.
#
# Usage: bash scripts/fig_15.sh

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

MAPPER="${MAPPER:-ILP}"
CONFIGS=(
  "qaoa_3reg_n120 S40C4-2x2"
  "qaoa_3reg_n250 S80C8-2x2"
  "qaoa_3reg_n370 S120C12-2x2"
  "qaoa_3reg_n500 S160C16-2x2"
  "qaoa_3reg_n120 S40C3-2x2"
  "qaoa_3reg_n180 S40C3-2x3"
  "qaoa_3reg_n240 S40C3-3x3"
  "qaoa_3reg_n350 S40C3-3x4"
)

for cfg in "${CONFIGS[@]}"; do
  read -r bench arch <<< "$cfg"
  qasm="$BENCH_DIR/qaoa_3reg/$bench.qasm"
  if [[ ! -f "$qasm" ]]; then
    { echo "[missing] $qasm -- run: bash scripts/ensure_dataset.sh"; exit 2; }
  fi
  echo "==== $bench @ $arch ===="
  bash "$SCRIPT_DIR/run_all_variants.sh" "$bench" "$arch" "$MAPPER"
done

RESULTS_BASE="$RESULTS_DIR" PYTHONPATH="$AE_ROOT/src" \
  python "$AE_ROOT/data_generator/section6/figure15_scaling.py"
cp "$AE_ROOT/data_generator/output/section6/figure15_scaling.pdf" \
   "$FIGURES_DIR/fig_15.pdf"
echo "Fig 15 -> $FIGURES_DIR/fig_15.pdf"
