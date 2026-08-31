#!/usr/bin/env bash
# Parallel dispatcher: read VARIANT BENCH ARCH MAPPER tuples on stdin (one per
# line, whitespace-separated) and run them in parallel via `xargs -P $JOBS`.
# Each line is dispatched to scripts/run_<variant>.sh.
#
# Usage:
#   echo "QuComm bv_n32 F120 ILP" | bash scripts/run_parallel.sh
#   JOBS=160 bash scripts/run_parallel.sh < jobs.txt
#
# Environment:
#   JOBS     -- max concurrent jobs (default $(nproc))
#   FORCE    -- if set, re-run even when results exist
#   LOG_DIR  -- per-job stdout+stderr log dir (default $RESULTS_DIR/_logs)

set -uo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

LOG_DIR="${LOG_DIR:-$RESULTS_DIR/_logs}"
mkdir -p "$LOG_DIR"

dispatch_one() {
  # Args: VARIANT BENCH ARCH MAPPER
  local variant="$1" bench="$2" arch="$3" mapper="$4"
  local outdir log
  outdir="$(result_path "$variant" "$arch" "$mapper" "$bench")"
  log="$LOG_DIR/${variant}_${arch}_${mapper}_${bench}.log"

  if [[ -z "${FORCE:-}" ]] && { ls "$outdir"/results*.json >/dev/null 2>&1 || ls "$outdir"/**/results-*.json >/dev/null 2>&1; }; then
    printf '[skip] %-10s %s/%s/%s\n' "$variant" "$arch" "$mapper" "$bench"
    return 0
  fi

  local script
  case "$variant" in
    QuComm)    script="run_qucomm.sh" ;;
    IRIS-opt0) script="run_iris_opt0.sh" ;;
    IRIS-opt1) script="run_iris_opt1.sh" ;;
    *) echo "[err] unknown variant: $variant" >&2; return 2 ;;
  esac

  local t0 t1
  t0=$(date +%s)
  if bash "$SCRIPT_DIR/$script" "$bench" "$arch" "$mapper" >"$log" 2>&1; then
    t1=$(date +%s)
    printf '[ok]   %-10s %s/%s/%s (%ds)\n' "$variant" "$arch" "$mapper" "$bench" "$((t1-t0))"
  else
    t1=$(date +%s)
    printf '[FAIL] %-10s %s/%s/%s (%ds) log=%s\n' "$variant" "$arch" "$mapper" "$bench" "$((t1-t0))" "$log" >&2
    return 1
  fi
}
export -f dispatch_one
export SCRIPT_DIR LOG_DIR

# Read tuples; allow comments/blank lines.
grep -vE '^\s*(#|$)' | \
  xargs -P "$JOBS" -n 4 bash -c 'dispatch_one "$@"' _
