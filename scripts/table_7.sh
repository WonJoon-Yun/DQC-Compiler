#!/usr/bin/env bash
# Table 7: QEC syndrome-extraction circuits (paper tuples, from the IRIS-dataset):
#   BB [[72,12,6]]   -> bb_72_12_6_n144  on S46C5-2x2
#   Color [[61,1,9]] -> color_61_1_9_n121 on S42C5-2x2
#   Surface [[49,1,7]] -> surface_code_n97 on S33C4-2x2
# Compares QuComm vs IRIS-opt1. Benchmarks + mapping results come from
# `python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset`.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

TUPLES=( "bb_72_12_6_n144 S46C5-2x2" \
         "color_61_1_9_n121 S42C5-2x2" \
         "surface_code_n97 S33C4-2x2" )
MAPPER="${MAPPER:-ILP}"

BENCH_LIST=""
ARCH_LIST=""
for pair in "${TUPLES[@]}"; do
  read -r bench arch <<<"$pair"
  family="${bench%_n*}"
  qasm="$BENCH_DIR/$family/$bench.qasm"
  if [[ ! -f "$qasm" ]]; then
    echo "[missing] $qasm -- copy benchmarks: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset"
    exit 2
  fi
  bash "$SCRIPT_DIR/run_qucomm.sh"    "$bench" "$arch" "$MAPPER"
  bash "$SCRIPT_DIR/run_iris_opt1.sh" "$bench" "$arch" "$MAPPER"
  BENCH_LIST+="${BENCH_LIST:+,}$family"
  ARCH_LIST+="${ARCH_LIST:+,}$arch"
done

python "$SCRIPT_DIR/extract_results.py" --root "$RESULTS_DIR" \
       --out "$RESULTS_DIR/summary.csv"

python "$SCRIPT_DIR/plot/format_table.py" \
       --csv "$RESULTS_DIR/summary.csv" \
       --archs "$ARCH_LIST" --mappers "$MAPPER" \
       --benches "$BENCH_LIST" \
       --out "$FIGURES_DIR/table_7.md"
echo "Table 7 -> $FIGURES_DIR/table_7.md"
