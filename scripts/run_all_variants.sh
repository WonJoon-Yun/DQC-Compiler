#!/usr/bin/env bash
# Run all 3 variants (QuComm, IRIS-opt0, IRIS-opt1) on one (bench, arch, mapper)
# in parallel. Skips a variant if its result directory already contains a
# results-*.json (so this script is idempotent).
#
# Usage:  bash scripts/run_all_variants.sh <BENCH> <ARCH> <MAPPER>

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"

BENCH="${1:?bench required}"
ARCH="${2:?arch required}"
MAPPER="${3:?mapper required}"

JOBS_FILE="$(mktemp)"
trap 'rm -f "$JOBS_FILE"' EXIT
for v in QuComm IRIS-opt0 IRIS-opt1; do
  echo "$v $BENCH $ARCH $MAPPER" >> "$JOBS_FILE"
done

bash "$SCRIPT_DIR/run_parallel.sh" < "$JOBS_FILE"
