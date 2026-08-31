#!/usr/bin/env bash
# Health check for the IRIS artifact:
#   - verifies bench/ has all required QASM files
#   - verifies src/ Python imports work
#   - runs the EES post-condition unit tests
#   - optionally runs a tiny smoke job
#
# Usage:
#   bash scripts/health_check.sh           # static + unit
#   SMOKE=1 bash scripts/health_check.sh   # also run bv_n8 × 3 variants

set -uo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$AE_ROOT"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $*"; }
fail() { FAIL=$((FAIL+1)); echo "  ✗ $*" >&2; }

echo "=== 1. Benchmark inventory ==="
for b in bv qaoa_3reg qaoa_fc qft qugan qv shor vqe; do
  missing=()
  for n in 120 180 240; do
    if [[ ! -f "bench/$b/${b}_n${n}.qasm" ]]; then
      missing+=("n$n")
    fi
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "$b: all sizes present"
  else
    fail "$b: missing ${missing[*]}"
  fi
done

echo ""
echo "=== 2. Source import ==="
PYTHONPATH="$AE_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python -c "
from router import IRISRouter
from route import schedule_blocks, BenchmarkSetup
from router.optim.early_execution import pipeline_optimization, qucomm_parallel_schedule, _verify_placed_pipeline
print('imports OK')
" 2>&1 | tail -1 | grep -q "imports OK" && ok "Python src imports" || fail "Python src imports"

echo ""
echo "=== 3. EES unit tests ==="
PYTHONPATH="$AE_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python "$AE_ROOT/tests/test_ees_postcondition.py" 2>&1 | tail -1 | grep -q "ALL TESTS PASSED" \
  && ok "tests/test_ees_postcondition.py" \
  || fail "tests/test_ees_postcondition.py"

if [[ "${SMOKE:-}" == "1" ]]; then
  echo ""
  echo "=== 4. Tiny smoke (bv_n120 × 3 variants × F120 ILP) ==="
  rm -rf "results/_healthcheck" 2>/dev/null
  for v in qucomm iris_opt0 iris_opt1; do
    RESULTS_DIR="$AE_ROOT/results/_healthcheck" bash scripts/run_${v}.sh bv_n120 F120 ILP > "/tmp/health_${v}.log" 2>&1 &
  done
  wait
  for V in QuComm IRIS-noEES IRIS; do
    if ls "results/_healthcheck/MinCut/$V/bv_n120-S40C5-2x2/"results*.json >/dev/null 2>&1; then
      ok "smoke $V"
    else
      fail "smoke $V"
    fi
  done
fi

echo ""
echo "=== Summary: $PASS pass, $FAIL fail ==="
[[ $FAIL -eq 0 ]] || exit 1
