#!/usr/bin/env bash
# Fig 14: EES schedule overlay (QAOA-3reg n240 on F240, 3 variants).
# Replays IRIS-opt1's EES schedule through qucomm_parallel_schedule
# to overlay the extra-opt curve.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${BENCH:-qaoa_3reg_n240}"
ARCH="${ARCH:-F240}"
MAPPER="${MAPPER:-ILP}"

qasm="$BENCH_DIR/qaoa_3reg/${BENCH}.qasm"
if [[ ! -f "$qasm" ]]; then
  echo "[gen] $BENCH"; mkdir -p "$BENCH_DIR/qaoa_3reg"
  { echo "[missing] $qasm -- copy benchmarks: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset"; exit 2; }
fi

bash "$SCRIPT_DIR/run_all_variants.sh" "$BENCH" "$ARCH" "$MAPPER"

python "$SCRIPT_DIR/plot/fig_14_ees.py" \
       --qucomm    "$(result_path QuComm    "$ARCH" "$MAPPER" "$BENCH")" \
       --iris-opt0 "$(result_path IRIS-opt0 "$ARCH" "$MAPPER" "$BENCH")" \
       --iris-opt1 "$(result_path IRIS-opt1 "$ARCH" "$MAPPER" "$BENCH")" \
       --arch "$ARCH" \
       --output "$FIGURES_DIR/fig_14.pdf"
echo "Fig 14 -> $FIGURES_DIR/fig_14.pdf"
