#!/usr/bin/env bash
# End-to-end Table 2 reproduction: seed mapping caches, rerun the five F240
# QuComm programs, derive delayed-teleportation metrics from their new tracers,
# and compare the generated CSV with the released reference.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DATASET_DIR="${DATASET:-$AE_ROOT/IRIS-dataset}"
TABLE2_RESULTS="${RESULTS_DIR:-$AE_ROOT/results/_table2_rerun}"
TABLE2_JOBS="${JOBS:-5}"

if [[ ! -f "$DATASET_DIR/index.json" ]]; then
  echo "[error] IRIS-dataset not found at: $DATASET_DIR" >&2
  echo "        set DATASET=/absolute/path/to/IRIS-dataset and rerun" >&2
  exit 2
fi

# Use the active Python when it has the artifact dependencies. Otherwise use
# the conda environment created by setup.sh without requiring `conda activate`.
PYTHON_BIN="$(command -v python || command -v python3)"
if ! "$PYTHON_BIN" -c 'import pymetis, qiskit' >/dev/null 2>&1; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "[error] current Python lacks pymetis/qiskit and conda is unavailable" >&2
    echo "        run: bash setup.sh" >&2
    exit 2
  fi
  PYTHON_BIN="$(conda run -n iris-ae python -c 'import sys; print(sys.executable)')"
fi
"$PYTHON_BIN" -c 'import pymetis, qiskit' >/dev/null
export PATH="$(dirname "$PYTHON_BIN"):$PATH"

echo "[table2] Python:  $PYTHON_BIN"
echo "[table2] dataset: $DATASET_DIR"
echo "[table2] results: $TABLE2_RESULTS"
echo "[table2] seeding the released mapping caches"
"$PYTHON_BIN" "$AE_ROOT/scripts/seed_from_dataset.py" \
  --dataset "$DATASET_DIR" \
  --results "$TABLE2_RESULTS" \
  --bench-dir "$AE_ROOT/bench" \
  --benches qaoa_fc_n240,qft_n240,qv_n240,shor_n240,vqe_n240 \
  --archs F240

echo "[table2] rerunning five F240 QuComm schedules (resume-safe)"
RESULTS_DIR="$TABLE2_RESULTS" \
JOBS="$TABLE2_JOBS" \
BENCHES=qaoa_fc,qft,qv,shor,vqe \
ARCHS=F240 \
MAPPERS=ILP \
VARIANTS=QuComm \
  bash "$AE_ROOT/scripts/run_main_suite.sh"

echo "[table2] deriving delayed-teleportation metrics from rerun tracers"
RESULTS_BASE="$TABLE2_RESULTS" \
PYTHONPATH="$AE_ROOT/src" \
  "$PYTHON_BIN" "$AE_ROOT/data_generator/section3/table2_delayed_teleportations.py"

GENERATED="$AE_ROOT/data_generator/output/section3/table2_delayed_teleportations.csv"
REFERENCE="$AE_ROOT/data_generator/expected/section3/table2_delayed_teleportations.csv"

if [[ -f "$REFERENCE" ]]; then
  diff -u "$REFERENCE" "$GENERATED"
  echo "[table2] PASS: rerun values exactly match the released reference"
fi
"$PYTHON_BIN" - "$GENERATED" "$SCRIPT_DIR/table2_delayed_teleportations.csv" <<'PY'
from pathlib import Path
import sys

source, output = map(Path, sys.argv[1:])
output.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
PY
echo "[table2] wrote $GENERATED"
echo "[table2] copied $SCRIPT_DIR/table2_delayed_teleportations.csv"
