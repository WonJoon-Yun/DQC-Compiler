#!/usr/bin/env bash
# Table 6: F180 (2x3) and F240 (3x3) DQCs with Min-Cut mapper.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCHES_CSV="${BENCHES:-bv,qaoa_3reg,qaoa_fc,qft,qugan,qv,shor,vqe}"

BENCHES="$BENCHES_CSV" ARCHS=F180,F240 MAPPERS=ILP \
  bash "$SCRIPT_DIR/run_main_suite.sh"

python "$SCRIPT_DIR/extract_results.py" --root "$RESULTS_DIR" \
       --out "$RESULTS_DIR/summary.csv"

python "$SCRIPT_DIR/plot/format_table.py" \
       --csv "$RESULTS_DIR/summary.csv" \
       --archs F180,F240 --mappers ILP \
       --out "$FIGURES_DIR/table_6.md"
echo "Table 6 -> $FIGURES_DIR/table_6.md"
