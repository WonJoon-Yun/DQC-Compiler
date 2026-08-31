#!/usr/bin/env bash
# Run IRIS-opt0 (UMS routing, no EES) on one benchmark / arch / mapper.
# Usage:  bash scripts/run_iris_opt0.sh <BENCH> <ARCH> <MAPPER>

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

OUT_DIR="$(result_path IRIS-opt0 "$ARCH" "$MAPPER" "$BENCH")"
mkdir -p "$OUT_DIR"

# shellcheck disable=SC2046
python "$SRC_DIR/run.py" \
    --circuit "$QASM" --name "$BENCH" \
    --mapping_method "$MAPPER" \
    --results_dir "$OUT_DIR" --flat_output \
    $(arch_params "$ARCH") \
    --oee_max_passes 5 --oee_tol 0.0 \
    "${COMMON_ARGS[@]}" \
    "${IRIS_LOOKAHEAD_ARGS[@]}"

echo "IRIS-opt0 done: $OUT_DIR"
