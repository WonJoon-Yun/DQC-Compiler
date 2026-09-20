#!/usr/bin/env bash
# Rerun the Figure 16 scheduling sweeps whose QASM files were omitted from the
# released dataset. The exact released mapping.json/layers.json files remain
# the experiment input; the minimal QASMs only satisfy run.py's eager parser.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
DATASET_DIR="${DATASET:-$AE_ROOT/IRIS-dataset}"
# Match scripts/reproduce_all.sh and scripts/ensure_dataset.sh by default so
# the recovered sweep runs complete the same results tree as the full workflow.
FIG16_RESULTS="${RESULTS_DIR:-$AE_ROOT/results/_full}"
STUB_BENCH_DIR="$SCRIPT_DIR/missing_qasm"
MISSING_BENCHES="qaoa_5reg_n120,qaoa_5reg_n180,qaoa_5reg_n240,qaoa_7reg_n120,qaoa_7reg_n180,qaoa_7reg_n240,xorr_n120,xorr_n180"
DEFAULT_SCHEDS="QuComm-bw2,QuComm-bw4,QuComm-bw8,QuComm-bw16,QuComm-bw32,QuComm-lh2,QuComm-lh4,QuComm-lh6,QuComm-lh8,QuComm-lh10,IRIS-bw2,IRIS-bw4,IRIS-bw8,IRIS-bw16,IRIS-bw32,IRIS-lh2,IRIS-lh4,IRIS-lh6,IRIS-lh8,IRIS-lh10"
FULL_MISSING_SWEEP=1
if [[ -n "${SCHEDS:-}" || -n "${BENCH_FILTER:-}" ]]; then
  FULL_MISSING_SWEEP=0
fi

if [[ ! -f "$DATASET_DIR/index.json" ]]; then
  echo "[error] IRIS-dataset not found at: $DATASET_DIR" >&2
  echo "        set DATASET=/absolute/path/to/IRIS-dataset and rerun" >&2
  exit 2
fi

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

echo "[figure16] Python:  $PYTHON_BIN"
echo "[figure16] dataset: $DATASET_DIR"
echo "[figure16] results: $FIG16_RESULTS"
echo "[figure16] seeding exact released mapping/layer caches"
"$PYTHON_BIN" "$AE_ROOT/scripts/seed_from_dataset.py" \
  --dataset "$DATASET_DIR" \
  --results "$FIG16_RESULTS" \
  --bench-dir "$AE_ROOT/bench" \
  --benches "$MISSING_BENCHES" \
  --archs F120,F180,F240

# Guard against accidentally mapping an empty stub circuit. Every seeded run
# must have all three cache files, and mapping size must equal the stub qreg.
FIG16_RESULTS="$FIG16_RESULTS" STUB_BENCH_DIR="$STUB_BENCH_DIR" \
  "$PYTHON_BIN" - <<'PY'
import json
import os
import re
from pathlib import Path

root = Path(os.environ["FIG16_RESULTS"])
stubs = Path(os.environ["STUB_BENCH_DIR"])
for qasm in sorted(stubs.glob("*/*.qasm")):
    bench = qasm.stem
    n = int(re.search(r"_n(\d+)$", bench).group(1))
    matched = []
    for pattern in ("QuComm-bw*", "QuComm-lh*", "IRIS-bw*", "IRIS-lh*"):
        matched.extend((root / "MinCut").glob(f"{pattern}/{bench}-S*C*-*x*"))
    if not matched:
        raise SystemExit(f"no seeded Figure-16 cache directories for {bench}")
    for run in matched:
        required = [run / "mapping.json", run / "layers.json", run / "compile_time.json"]
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise SystemExit("incomplete cache: " + ", ".join(missing))
        if len(json.loads((run / "mapping.json").read_text())) != n:
            raise SystemExit(f"mapping size mismatch for {run}")
print("[figure16] cache preflight passed for all missing-QASM sweep directories")
PY

echo "[figure16] starting/resuming missing scheduling sweeps"
echo "[figure16] completed results are skipped; parallel jobs: ${JOBS:-5}"
BENCH_DIR="$STUB_BENCH_DIR" \
RESULTS_DIR="$FIG16_RESULTS" \
BENCH_FILTER="${BENCH_FILTER:-qaoa_5reg_,qaoa_7reg_,xorr_}" \
SCHEDS="${SCHEDS:-$DEFAULT_SCHEDS}" \
JOBS="${JOBS:-5}" \
  bash "$AE_ROOT/scripts/fig_16.sh"

if [[ "$FULL_MISSING_SWEEP" -eq 1 ]]; then
  FIG16_RESULTS="$FIG16_RESULTS" "$PYTHON_BIN" - <<'PY'
from pathlib import Path
import os

root = Path(os.environ["FIG16_RESULTS"]) / "MinCut"
benches = (
    "qaoa_5reg_n120", "qaoa_5reg_n180", "qaoa_5reg_n240",
    "qaoa_7reg_n120", "qaoa_7reg_n180", "qaoa_7reg_n240",
    "xorr_n120", "xorr_n180",
)
runs = []
for pattern in ("QuComm-bw*", "QuComm-lh*", "IRIS-bw*", "IRIS-lh*"):
    for sched in root.glob(pattern):
        runs.extend(
            p for p in sched.iterdir()
            if p.is_dir() and any(p.name.startswith(f"{bench}-") for bench in benches)
        )
missing = [p for p in runs if not list(p.glob("results*.json"))]
if missing:
    sample = "\n  ".join(str(p) for p in missing[:10])
    raise SystemExit(f"{len(missing)} Figure-16 reruns are incomplete:\n  {sample}")
if len(runs) != 150:
    raise SystemExit(f"expected 150 missing-QASM sweep runs, found {len(runs)}")
missing_ees = [p for p in runs if p.parent.name.startswith("IRIS-")
               and not (p / "extra_opt.json").is_file()]
if missing_ees:
    sample = "\n  ".join(str(p) for p in missing_ees[:10])
    raise SystemExit(f"{len(missing_ees)} IRIS reruns lack EES post-processing:\n  {sample}")
print("[figure16] completeness check passed: 150/150 reruns have results; "
      "75/75 IRIS reruns have EES post-processing")
PY
else
  echo "[figure16] subset mode: full 150-run completeness check skipped"
fi

echo "[figure16] missing-data rerun complete"
echo "[figure16] render with: bash $SCRIPT_DIR/plot_figure16.sh"
