#!/usr/bin/env bash
# Fig 18: communication-qubit budget sweep — qaoa_3reg fully mapped on a 2x2
# grid. Per-chip compute capacity is pinned (every chip 100% packed) while the
# comm budget C sweeps 2..6:
#   system_qubits_per_chip = COMPUTE + 2*C   (2 links per chip on a 2x2 grid)
#   arch spec              = S<COMPUTE+2C>C<C>-2x2
# Variants: QuComm baseline, IRIS-opt0, IRIS-opt1 (standard pipeline; results
# land in the dataset layout under $RESULTS_DIR, so `ensure_dataset.sh` imports
# the mapping results for these architectures and completed runs are
# skipped automatically). Note C=5 with the default COMPUTE=30 is exactly the
# main F120 configuration (S40C5-2x2) and reuses that run.
#
# Defaults reproduce the paper's 120-qubit figure (COMPUTE=30, 4x30=120).
# COMPUTE=25 BENCHES=qaoa_3reg_n100 reproduces the n100 reference sweep.
#
# Usage: bash scripts/fig_18.sh
#   options: COMPUTE=30  BENCHES="qaoa_3reg_n120"  CS="2 3 4 5 6"  JOBS=N

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

COMPUTE="${COMPUTE:-30}"
BENCHES="${BENCHES:-qaoa_3reg_n$((COMPUTE * 4))}"
CS="${CS:-2 3 4 5 6}"
MAPPER="${MAPPER:-ILP}"

for bench in $BENCHES; do
  bench_family="${bench%_n*}"
  qasm="$BENCH_DIR/$bench_family/$bench.qasm"
  if [[ ! -f "$qasm" ]]; then
    { echo "[missing] $qasm -- run: bash scripts/ensure_dataset.sh"; exit 2; }
  fi
  for c in $CS; do
    arch="S$((COMPUTE + 2 * c))C${c}-2x2"
    echo "==== comm budget C=$c -> $arch ===="
    bash "$SCRIPT_DIR/run_all_variants.sh" "$bench" "$arch" "$MAPPER"
  done
done

first_bench="${BENCHES%% *}"
python "$SCRIPT_DIR/plot/fig_18_commbudget.py" \
       --root "$RESULTS_DIR" --bench "$first_bench" --compute "$COMPUTE" \
       --output "$FIGURES_DIR/fig_18.pdf"
echo "Fig 18 -> $FIGURES_DIR/fig_18.pdf"
