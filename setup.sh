#!/usr/bin/env bash
# Bootstrap the iris-ae conda environment.
# Re-runnable: creates or updates the env idempotently.

set -euo pipefail

ENV_NAME="${ENV_NAME:-iris-ae}"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${SKIP_ENV:-0}" != "1" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "ERROR: conda not found. Install Miniconda first: https://docs.conda.io/en/latest/miniconda.html"
    exit 1
  fi

  if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "[setup] updating $ENV_NAME"
    conda env update -n "$ENV_NAME" -f "$HERE/environment.yml" --prune
  else
    echo "[setup] creating $ENV_NAME"
    conda env create -n "$ENV_NAME" -f "$HERE/environment.yml"
  fi

  # Sanity: METIS lib present (pymetis needs it at import time).
  # Run the import inside the target env, not the current shell.
  if ! conda run -n "$ENV_NAME" python -c "import pymetis" 2>/dev/null; then
    echo "[setup] WARNING: pymetis not importable inside $ENV_NAME."
    echo "         conda install -n $ENV_NAME -c conda-forge metis pymetis"
  fi
fi

# ---- Data setup: IRIS-dataset benchmarks + the paper's mapping caches ----
# Looks for ./IRIS-dataset (recommended), ../IRIS-dataset, or ./IRIS-dataset.tar;
# DOWNLOAD_DATASET=1 fetches it from Zenodo. Skip with SKIP_DATA=1.
if [[ "${SKIP_DATA:-0}" != "1" ]]; then
  echo
  if ! bash "$HERE/scripts/ensure_dataset.sh"; then
    echo "[setup] dataset not set up yet (see message above); the env is ready regardless."
  fi
fi

echo
echo "[setup] done. Activate with:  conda activate $ENV_NAME"
