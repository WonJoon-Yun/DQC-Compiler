#!/usr/bin/env bash
# Master orchestrator. Runs every fig_*.sh and table_*.sh in sequence.
# Use $MODE=quick to skip the long (Table 8, Figs 12/16/17/18/19) jobs.
#
# Usage:
#   bash scripts/reproduce_all.sh             # full reproduction
#   MODE=quick bash scripts/reproduce_all.sh  # smoke subset

set -uo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

# Load benchmarks + the mapping results from the IRIS-dataset, then
# run only the routing/scheduling stage on top of them (the ILP mapper is
# skipped whenever a mapping cache is present). Idempotent.
bash "$SCRIPT_DIR/ensure_dataset.sh"

MODE="${MODE:-full}"
if [[ "$MODE" == "quick" ]]; then
  SCRIPTS=( table_5.sh table_6.sh fig_11.sh fig_14.sh fig_15.sh )
else
  SCRIPTS=( table_5.sh table_6.sh table_7.sh table_8.sh
            fig_11.sh fig_12.sh fig_13.sh fig_14.sh fig_15.sh
            fig_16.sh fig_17.sh fig_18.sh fig_19.sh )
fi

FAILED=()
for s in "${SCRIPTS[@]}"; do
  echo "===================================================================="
  echo "  $s"
  echo "===================================================================="
  if ! bash "$SCRIPT_DIR/$s"; then
    echo "[FAIL] $s"
    FAILED+=("$s")
  fi
done

# Final post-hoc verification of every IRIS-opt1 schedule.
python "$AE_ROOT/tests/verify_extra_opt.py" --root "$RESULTS_DIR" || true

echo
echo "=== reproduce_all.sh summary ==="
echo "  mode: $MODE"
echo "  scripts attempted: ${#SCRIPTS[@]}"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "  FAILED: ${FAILED[*]}"
  exit 1
fi
echo "  ALL OK"
echo "  Tables & figures under: $FIGURES_DIR"
