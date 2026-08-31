#!/usr/bin/env bash
# Fig 11: UMS cumulative teleportation cost (Shor n240 on F240).

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${BENCH:-shor_n240}"
ARCH="${ARCH:-F240}"
MAPPER="${MAPPER:-ILP}"

qasm="$BENCH_DIR/shor/${BENCH}.qasm"
if [[ ! -f "$qasm" ]]; then
  echo "[gen] $BENCH"; mkdir -p "$BENCH_DIR/shor"
  { echo "[missing] $qasm -- copy benchmarks: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset"; exit 2; }
fi

bash "$SCRIPT_DIR/run_qucomm.sh"    "$BENCH" "$ARCH" "$MAPPER"
bash "$SCRIPT_DIR/run_iris_opt0.sh" "$BENCH" "$ARCH" "$MAPPER"

python "$SCRIPT_DIR/plot/fig_11_ums.py" \
       --qucomm   "$(result_path QuComm    "$ARCH" "$MAPPER" "$BENCH")" \
       --iris-opt0 "$(result_path IRIS-opt0 "$ARCH" "$MAPPER" "$BENCH")" \
       --output "$FIGURES_DIR/fig_11.pdf"
echo "Fig 11 -> $FIGURES_DIR/fig_11.pdf"
