#!/usr/bin/env bash
# Main suite: enumerate (variant, bench, arch, mapper) tuples and dispatch
# to scripts/run_parallel.sh. Honors $BENCHES, $ARCHS, $MAPPERS, $VARIANTS
# (comma-separated) for subsetting and $JOBS for parallelism.
#
# Usage:
#   bash scripts/run_main_suite.sh
#   JOBS=160 BENCHES=bv,qaoa_3reg ARCHS=F120 bash scripts/run_main_suite.sh

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"

BENCHES_CSV="${BENCHES:-bv,qaoa_3reg,qaoa_fc,qft,qugan,qv,shor,vqe}"
ARCHS_CSV="${ARCHS:-F120,F180,F240}"
MAPPERS_CSV="${MAPPERS:-ILP}"
VARIANTS_CSV="${VARIANTS:-QuComm,IRIS-opt0,IRIS-opt1}"

IFS=',' read -r -a BENCHES  <<< "$BENCHES_CSV"
IFS=',' read -r -a ARCHS    <<< "$ARCHS_CSV"
IFS=',' read -r -a MAPPERS  <<< "$MAPPERS_CSV"
IFS=',' read -r -a VARIANTS <<< "$VARIANTS_CSV"

arch_qubits() {
  case "$1" in
    F120) echo 120 ;;  F180) echo 180 ;;  F240) echo 240 ;;
    F500) echo 500 ;;  F800) echo 800 ;;  F1100) echo 1100 ;;
    *) echo "unknown arch $1" >&2; return 1 ;;
  esac
}

JOBS_FILE="$(mktemp)"
trap 'rm -f "$JOBS_FILE"' EXIT

for arch in "${ARCHS[@]}"; do
  q="$(arch_qubits "$arch")"
  for mapper in "${MAPPERS[@]}"; do
    for b in "${BENCHES[@]}"; do
      bench_name="${b}_n${q}"
      qasm="$BENCH_DIR/$b/$bench_name.qasm"
      if [[ ! -f "$qasm" ]]; then
        echo "[miss] $qasm  -- copy benchmarks: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset" >&2
        continue
      fi
      for variant in "${VARIANTS[@]}"; do
        echo "$variant $bench_name $arch $mapper" >> "$JOBS_FILE"
      done
    done
  done
done

n=$(wc -l < "$JOBS_FILE")
echo "[main_suite] dispatching $n jobs with JOBS=$JOBS"
bash "$SCRIPT_DIR/run_parallel.sh" < "$JOBS_FILE"
