#!/usr/bin/env bash
# Locate the IRIS-dataset and import the benchmarks and mapping caches from it (benchmarks into
# $BENCH_DIR, the paper's mapper outputs into $RESULTS_DIR).
#
# Search order for the dataset:
#   1. $DATASET (if set)
#   2. <repo>/IRIS-dataset            (recommended location)
#   3. <repo>/../IRIS-dataset
#   4. <repo>/IRIS-dataset.tar        (unpacked automatically)
#   5. with DOWNLOAD_DATASET=1: downloaded from Zenodo (~1.4 GB), then unpacked
#
# Idempotent — safe to re-run. Used by setup.sh and reproduce_all.sh.

set -euo pipefail

# Remember whether the caller pinned RESULTS_DIR before common_env defaults it.
RESULTS_DIR_SET="${RESULTS_DIR+x}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"

# The import targets the main sweep tree by default (README Step 2 uses it).
if [[ -z "$RESULTS_DIR_SET" ]]; then
  RESULTS_DIR="$AE_ROOT/results/_full"
fi

ZENODO_URL="https://zenodo.org/records/22152933/files/IRIS-dataset.tar"

resolve_dataset() {
  if [[ -n "${DATASET:-}" && -f "$DATASET/index.json" ]]; then
    echo "$DATASET"; return 0
  fi
  for d in "$AE_ROOT/IRIS-dataset" "$AE_ROOT/../IRIS-dataset"; do
    if [[ -f "$d/index.json" ]]; then echo "$d"; return 0; fi
  done
  if [[ -f "$AE_ROOT/IRIS-dataset.tar" ]]; then
    echo "[dataset] unpacking $AE_ROOT/IRIS-dataset.tar" >&2
    tar -xf "$AE_ROOT/IRIS-dataset.tar" -C "$AE_ROOT"
    [[ -f "$AE_ROOT/IRIS-dataset/index.json" ]] && { echo "$AE_ROOT/IRIS-dataset"; return 0; }
  fi
  if [[ "${DOWNLOAD_DATASET:-0}" == "1" ]]; then
    echo "[dataset] downloading IRIS-dataset.tar (~1.4 GB) from Zenodo" >&2
    curl -L --fail -o "$AE_ROOT/IRIS-dataset.tar" "$ZENODO_URL" >&2
    tar -xf "$AE_ROOT/IRIS-dataset.tar" -C "$AE_ROOT"
    [[ -f "$AE_ROOT/IRIS-dataset/index.json" ]] && { echo "$AE_ROOT/IRIS-dataset"; return 0; }
  fi
  return 1
}

if ! DS="$(resolve_dataset)"; then
  echo "[dataset] IRIS-dataset not found."
  echo "  Download it into the repository root:"
  echo "    wget $ZENODO_URL"
  echo "    tar -xf IRIS-dataset.tar          # -> ./IRIS-dataset/"
  echo "  (or re-run with DOWNLOAD_DATASET=1, or set DATASET=/path/to/IRIS-dataset)"
  exit 2
fi

# seed_from_dataset.py is stdlib-only, so any python3 works (conda env not required).
PY="$(command -v python || command -v python3)"
echo "[dataset] importing from $DS"
"$PY" "$SCRIPT_DIR/seed_from_dataset.py" \
    --dataset "$DS" --results "$RESULTS_DIR" --bench-dir "$BENCH_DIR"
