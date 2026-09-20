#!/usr/bin/env bash
# Plot Figure 16 from a complete overlay: use fresh missing-QASM reruns when
# available and fall back to the released dataset for every other sweep run.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DATASET_DIR="${DATASET:-$AE_ROOT/IRIS-dataset}"
# Fresh runs produced by the full workflow and the missing-data runner live in
# the same tree by default. RESULTS_DIR can still select an isolated smoke run.
FIG16_RESULTS="${RESULTS_DIR:-$AE_ROOT/results/_full}"
OVERLAY="$AE_ROOT/results/_figure16_plot_overlay"
OUT6="$AE_ROOT/data_generator/output/section6"

if [[ ! -f "$DATASET_DIR/index.json" ]]; then
  echo "[error] IRIS-dataset not found at: $DATASET_DIR" >&2
  exit 2
fi

PYTHON_BIN="$(command -v python || command -v python3)"
if ! "$PYTHON_BIN" -c 'import matplotlib' >/dev/null 2>&1; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "[error] matplotlib unavailable; run bash setup.sh" >&2
    exit 2
  fi
  PYTHON_BIN="$(conda run -n iris-ae python -c 'import sys; print(sys.executable)')"
fi

# Recreate only the small symlink overlay, never the source result trees.
rm -rf "$OVERLAY"
mkdir -p "$OVERLAY/MinCut"
fresh_count=0
released_count=0
for released_sched in "$DATASET_DIR"/MinCut/QuComm-bw* \
                      "$DATASET_DIR"/MinCut/QuComm-lh* \
                      "$DATASET_DIR"/MinCut/IRIS-bw* \
                      "$DATASET_DIR"/MinCut/IRIS-lh*; do
  [[ -d "$released_sched" ]] || continue
  sched="$(basename "$released_sched")"
  mkdir -p "$OVERLAY/MinCut/$sched"
  for released_run in "$released_sched"/*; do
    [[ -d "$released_run" ]] || continue
    name="$(basename "$released_run")"
    fresh="$FIG16_RESULTS/MinCut/$sched/$name"
    if compgen -G "$fresh/results*.json" >/dev/null; then
      ln -s "$fresh" "$OVERLAY/MinCut/$sched/$name"
      fresh_count=$((fresh_count + 1))
    else
      ln -s "$released_run" "$OVERLAY/MinCut/$sched/$name"
      released_count=$((released_count + 1))
    fi
  done
done

total_count=$((fresh_count + released_count))
if [[ "$total_count" -ne 598 ]]; then
  echo "[error] expected 598 Figure-16 sweep runs, found $total_count" >&2
  exit 2
fi
echo "[figure16] input runs: fresh=$fresh_count released-fallback=$released_count total=$total_count"

echo "[figure16] plotting from overlay: $OVERLAY"
RESULTS_BASE="$OVERLAY" \
EXTRA_OPT_CACHE="$AE_ROOT/results/_dataset_cache" \
PYTHONPATH="$AE_ROOT/src" \
  "$PYTHON_BIN" "$AE_ROOT/data_generator/section6/figure16_w_group_sensitivity.py"

cp "$OUT6/figure16_w_group_sensitivity.csv" "$SCRIPT_DIR/figure16_w_group_sensitivity.csv"
cp "$OUT6/figure16_w_group_sensitivity.pdf" "$SCRIPT_DIR/figure16_w_group_sensitivity.pdf"
cp "$OUT6/figure16_w_group_sensitivity.png" "$SCRIPT_DIR/figure16_w_group_sensitivity.png"
echo "[figure16] wrote $SCRIPT_DIR/figure16_w_group_sensitivity.{csv,pdf,png}"
