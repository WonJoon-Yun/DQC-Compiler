#!/usr/bin/env bash
# Run QuComm baseline on one benchmark / arch / mapper.
# Usage:  bash scripts/run_qucomm.sh <BENCH> <ARCH> <MAPPER>
#   e.g.: bash scripts/run_qucomm.sh bv_n120 F120 ILP

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${1:?bench name required (e.g. bv_n120)}"
ARCH="${2:?arch required (F120|F180|F240|F500|F800|F1100)}"
MAPPER="${3:?mapper required (ILP|OEE-ILP|GCP-ILP|WBCP)}"

# Resolve the benchmark family from name (bv_n120 -> bv).
BENCH_FAMILY="${BENCH%_n*}"
QASM="$BENCH_DIR/$BENCH_FAMILY/$BENCH.qasm"
[[ -f "$QASM" ]] || { echo "Missing benchmark: $QASM"; exit 2; }

OUT_DIR="$(result_path QuComm "$ARCH" "$MAPPER" "$BENCH")"
mkdir -p "$OUT_DIR"

# shellcheck disable=SC2046
python "$SRC_DIR/run.py" \
    --circuit "$QASM" --name "$BENCH" \
    --mapping_method "$MAPPER" \
    --results_dir "$OUT_DIR" --flat_output \
    $(arch_params "$ARCH") \
    --oee_max_passes 5 --oee_tol 0.0 \
    "${COMMON_ARGS[@]}"

echo "QuComm done: $OUT_DIR"
