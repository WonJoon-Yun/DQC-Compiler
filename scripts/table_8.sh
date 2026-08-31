#!/usr/bin/env bash
# Table 8: Memory / Compile / Runtime ratios for qaoa_3reg at 500/800/1100 qubits.
# Long-running (large arch + program size); skip in smoke mode.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

# Pair (arch, qubit_count) → (F500, n500), (F800, n800), (F1100, n1100)
declare -a PAIRS=( "F500 500" "F800 800" "F1100 1100" )

for pair in "${PAIRS[@]}"; do
  read arch q <<<"$pair"
  bench="qaoa_3reg_n${q}"
  qasm="$BENCH_DIR/qaoa_3reg/${bench}.qasm"
  if [[ ! -f "$qasm" ]]; then
    echo "[gen] $bench"
    { echo "[missing] $qasm -- copy benchmarks: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset"; exit 2; }
  fi
  bash "$SCRIPT_DIR/run_all_variants.sh" "$bench" "$arch" ILP
done

python "$SCRIPT_DIR/extract_results.py" --root "$RESULTS_DIR" \
       --out "$RESULTS_DIR/summary.csv"

python "$SCRIPT_DIR/plot/format_table.py" \
       --csv "$RESULTS_DIR/summary.csv" \
       --archs F500,F800,F1100 --mappers ILP \
       --benches qaoa_3reg \
       --columns compile,runtime,teff \
       --out "$FIGURES_DIR/table_8.md"
echo "Table 8 -> $FIGURES_DIR/table_8.md"
