#!/usr/bin/env bash
# Regenerate every paper figure and table from the AE results tree.
# All scripts read directly from `results/_full/` (no upstream IRIS tree needed).
#
# Usage:
#   bash data_generator/run_all.sh                    # everything
#   bash data_generator/run_all.sh section6           # only section6
#   bash data_generator/run_all.sh appendix_e         # only appendix_e
#
# Environment overrides:
#   ARTIFACT_ROOT  override artifact root (default: parent of data_generator/)
#   RESULTS_BASE   override results tree  (default: $ARTIFACT_ROOT/results/_full)
#   BENCH_DIR      override bench tree    (default: $ARTIFACT_ROOT/bench)
#   PYTHON         python interpreter

set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ART_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
# Use $PYTHON if set, else the active environment's python (run after
# `conda activate iris-ae`), falling back to python3.
PYTHON="${PYTHON:-$(command -v python || command -v python3)}"
export PYTHON PYTHONPATH="$ART_ROOT/src:${PYTHONPATH:-}"

cd "$SCRIPT_DIR"
filter="${1:-}"

run_one() {
  local script="$1"
  echo ""
  echo "=== $script ==="
  if ! "$PYTHON" "$script"; then
    echo "[FAIL] $script" >&2
    return 1
  fi
}

scripts=()

while IFS= read -r _line; do scripts+=("$_line"); done < <(find "$SCRIPT_DIR" -mindepth 2 -name "*.py" -not -name "_*" | sort)

failures=0
for s in "${scripts[@]}"; do
  rel="${s#$SCRIPT_DIR/}"
  if [[ -n "$filter" && "$rel" != "$filter"/* ]]; then
    continue
  fi
  if ! run_one "$s"; then
    failures=$((failures + 1))
  fi
done

echo ""
if [[ $failures -gt 0 ]]; then
  echo "[summary] $failures script(s) failed." >&2
  exit 1
fi
echo "[summary] all scripts succeeded; outputs under $SCRIPT_DIR/output/"
