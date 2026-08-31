#!/usr/bin/env bash
# Table 5: F120 (2x2) main table across 4 mappers.
# Mappers: ILP (Min-Cut), GCP-ILP (GCP-E), OEE-ILP (sOEE), WBCP.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCHES_CSV="${BENCHES:-bv,qaoa_3reg,qaoa_fc,qft,qugan,qv,shor,vqe}"
MAPPERS_CSV="${MAPPERS:-ILP,GCP-ILP,OEE-ILP,WBCP}"

BENCHES="$BENCHES_CSV" ARCHS=F120 MAPPERS="$MAPPERS_CSV" \
  bash "$SCRIPT_DIR/run_main_suite.sh"

python "$SCRIPT_DIR/extract_results.py" --root "$RESULTS_DIR" \
       --out "$RESULTS_DIR/summary.csv"

python "$SCRIPT_DIR/plot/format_table.py" \
       --csv "$RESULTS_DIR/summary.csv" \
       --archs F120 --mappers "$MAPPERS_CSV" \
       --out "$FIGURES_DIR/table_5.md"
echo "Table 5 -> $FIGURES_DIR/table_5.md"
