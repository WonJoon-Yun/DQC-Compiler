#!/usr/bin/env bash
# Fig 19: EPR generation latency sensitivity.
# Re-uses existing IRIS-opt1 schedules and re-times them at different EPR
# generation latencies (purely a replay; no re-routing).

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${BENCH:-qaoa_fc_n240}"
ARCH="${ARCH:-F240}"
MAPPER="${MAPPER:-ILP}"

qasm="$BENCH_DIR/qaoa_fc/${BENCH}.qasm"
if [[ ! -f "$qasm" ]]; then
  { echo "[missing] $qasm -- copy benchmarks: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset"; exit 2; }
fi

bash "$SCRIPT_DIR/run_all_variants.sh" "$BENCH" "$ARCH" "$MAPPER"

python "$SCRIPT_DIR/plot/fig_19_epr.py" \
       --qucomm    "$(result_path QuComm    "$ARCH" "$MAPPER" "$BENCH")" \
       --iris-opt0 "$(result_path IRIS-opt0 "$ARCH" "$MAPPER" "$BENCH")" \
       --iris-opt1 "$(result_path IRIS-opt1 "$ARCH" "$MAPPER" "$BENCH")" \
       --arch "$ARCH" \
       --output "$FIGURES_DIR/fig_19.pdf"
echo "Fig 19 -> $FIGURES_DIR/fig_19.pdf"
