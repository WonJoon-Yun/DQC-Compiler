#!/usr/bin/env bash
# Fig 12: C_R estimator validation — estimated vs actual (realized) future
# teleportation cost per scheduling decision (qaoa_3reg n32 on a 2x2 DQC).
#
# Phase 1 runs the normal pipeline with capture hooks; phase 2 replays each
# candidate with an MPC-style ground-truth re-plan, so this script is compute
# heavy (n32 takes a few hours single-threaded; WHICH=n120 much longer).
#
# Usage:
#   bash scripts/fig_12.sh            # n32 (the paper's Fig 12)
#   WHICH=n120 bash scripts/fig_12.sh

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

WHICH="${WHICH:-n32}"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

case "$WHICH" in
  n32)  qasm="$ROOT/bench/qaoa_3reg/qaoa_3reg_n32.qasm" ;;
  n120) qasm="$ROOT/bench/qaoa_3reg/qaoa_3reg_n120.qasm" ;;
  *) echo "WHICH must be n32 or n120"; exit 2 ;;
esac
if [[ ! -f "$qasm" ]]; then
  echo "[missing] $qasm"
  echo "  n32 ships with the repository; n120 comes from the IRIS-dataset"
  echo "  (bash scripts/ensure_dataset.sh)"
  exit 2
fi

# Import the n32 ILP mapping cache from the IRIS-dataset so the run is
# deterministic end-to-end. Without the
# cache the mapping is recomputed and the placement (hence the captured
# decisions) may differ across ILP-solver builds.
case "$WHICH" in
  n32)  ARCHDIR=S14C3-2x2 ;;
  n120) ARCHDIR=S40C5-2x2 ;;
esac
DS=""
for cand in "${DATASET:-}" "$ROOT/IRIS-dataset" "$ROOT/../IRIS-dataset"; do
  if [[ -n "$cand" && -f "$cand/cr_validation/$WHICH/mapping.json.gz" ]]; then
    DS="$cand"; break
  fi
done
if [[ -n "$DS" ]]; then
  CACHE_DIR="$ROOT/results/cr_validation/$WHICH/pipeline/qaoa_3reg_$WHICH/ILP/$ARCHDIR"
  mkdir -p "$CACHE_DIR"
  for f in mapping layers compile_time; do
    gunzip -c "$DS/cr_validation/$WHICH/$f.json.gz" > "$CACHE_DIR/$f.json"
  done
  echo "[fig_12] mapping cache imported from $DS/cr_validation/$WHICH"
else
  echo "[fig_12] no dataset mapping cache for $WHICH; the ILP mapping will be"
  echo "         recomputed (placement may differ from the paper's)"
fi

cd "$ROOT"
python "$SCRIPT_DIR/cr_validation.py" "$WHICH"

python "$SCRIPT_DIR/plot/fig_12_crval.py" \
       --decisions "$ROOT/results/cr_validation/$WHICH/decisions.csv" \
       --output "$FIGURES_DIR/fig_12.pdf"
echo "Fig 12 -> $FIGURES_DIR/fig_12.pdf"
