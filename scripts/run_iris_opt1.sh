#!/usr/bin/env bash
# Run IRIS-opt1 = IRIS-opt0 + EES, then apply post-hoc extra-opt
# (qucomm_parallel_schedule) to the EES schedule.
# Usage:  bash scripts/run_iris_opt1.sh <BENCH> <ARCH> <MAPPER>

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${1:?bench name required}"
ARCH="${2:?arch required}"
MAPPER="${3:?mapper required}"

BENCH_FAMILY="${BENCH%_n*}"
QASM="$BENCH_DIR/$BENCH_FAMILY/$BENCH.qasm"
[[ -f "$QASM" ]] || { echo "Missing benchmark: $QASM"; exit 2; }

# Phase 1: run IRIS-opt0 + EES (writes [Ss]chedule*.json with EES applied).
OUT_DIR="$(result_path IRIS-opt1 "$ARCH" "$MAPPER" "$BENCH")"
mkdir -p "$OUT_DIR"

# shellcheck disable=SC2046
python "$SRC_DIR/run.py" \
    --circuit "$QASM" --name "$BENCH" \
    --mapping_method "$MAPPER" \
    --results_dir "$OUT_DIR" --flat_output \
    $(arch_params "$ARCH") \
    --oee_max_passes 5 --oee_tol 0.0 \
    "${COMMON_ARGS[@]}" \
    "${IRIS_LOOKAHEAD_ARGS[@]}" \
    --enable_ees

# Phase 2: apply post-hoc extra-opt to the EES schedule.
SCHED=$(find "$OUT_DIR" -name '[Ss]chedule*.json' | head -1)
if [[ -n "$SCHED" ]]; then
  python "$SCRIPT_DIR/apply_extra_opt.py" \
      --schedule "$SCHED" \
      --arch "$ARCH" \
      --out "$OUT_DIR/extra_opt.json"
  echo "Extra-opt done: $OUT_DIR/extra_opt.json"
else
  echo "WARNING: no [Ss]chedule*.json found in $OUT_DIR; skipping extra-opt." >&2
fi

echo "IRIS-opt1 done: $OUT_DIR"
