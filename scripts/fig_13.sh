#!/usr/bin/env bash
# Fig 13: contribution-breakdown ablation of UMS (QuComm and IRIS variants):
# separates IRIS's two mechanisms — multi-candidate (ForeSight) search and the
# utility-driven lookahead window — by running five configurations:
#
#   label                        lookahead  multi-candidate  window
#   QuComm (default)             off        —                —
#   QuComm w/ Next-K lookahead   on         off (single)     serial (naive next-K)
#   IRIS w/ single candidate     on         off (single)     future_partner (utility)
#   IRIS w/ Next-K lookahead     on         on  (ForeSight)  serial (naive next-K)
#   IRIS (default)               on         on  (ForeSight)  future_partner_ranked
#
# Usage:  bash scripts/fig_13.sh [BENCH] [ARCH] [MAPPER]
#   e.g.: bash scripts/fig_13.sh qaoa_3reg_n120 F120 ILP
# Mapping caches are copied from the dataset import, so every
# configuration starts from the same mapping cache.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

BENCH="${1:-qaoa_3reg_n120}"
ARCH="${2:-F120}"
MAPPER="${3:-ILP}"

BENCH_FAMILY="${BENCH%_n*}"
QASM="$BENCH_DIR/$BENCH_FAMILY/$BENCH.qasm"
[[ -f "$QASM" ]] || { echo "Missing benchmark: $QASM (run seed_from_dataset.py)"; exit 2; }

ARCHDIR="$(arch_dir "$ARCH")"
CACHE_SRC="$(result_path QuComm "$ARCH" "$MAPPER" "$BENCH")"
if [[ ! -f "$CACHE_SRC/mapping.json" ]]; then
  echo "Missing mapping cache: $CACHE_SRC/mapping.json"
  echo "Import it first: python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset"
  exit 2
fi

ABL_ROOT="$RESULTS_DIR/ablation"

# Shared lookahead settings (paper defaults: depth |G|=4, beam w=16), matching
# the original ablation suite's config snapshots. Note: no future-touch
# opt-out here — the intermediate variants keep QuComm's future-touch
# short-circuit, exactly as in the original ablation runs.
LOOKAHEAD_BASE=(
  --qucomm_enable_gate_lookahead
  --qucomm_gate_lookahead_depth 4
  --qucomm_gate_lookahead_option opt1
  --qucomm_gate_lookahead_beam_width 16
  --qucomm_gate_lookahead_sort_mode current_then_total
  --qucomm_gate_lookahead_prune_mode selection_sort
  --qucomm_future_block_decay_mode linear
)

run_cfg() {   # $1 = tag, remaining = extra run.py args
  local tag="$1"; shift
  local out="$ABL_ROOT/$tag/${BENCH}-${ARCHDIR}"
  if ls "$out"/results*.json >/dev/null 2>&1; then
    echo "[skip] $tag (results exist)"
    return 0
  fi
  mkdir -p "$out"
  cp "$CACHE_SRC/mapping.json" "$CACHE_SRC/layers.json" "$CACHE_SRC/compile_time.json" "$out/"
  echo "[run] $tag"
  # shellcheck disable=SC2046
  python "$SRC_DIR/run.py" \
      --circuit "$QASM" --name "$BENCH" \
      --mapping_method "$MAPPER" \
      --results_dir "$out" --flat_output \
      $(arch_params "$ARCH") \
      --oee_max_passes 5 --oee_tol 0.0 \
      "${COMMON_ARGS[@]}" "$@"
  echo "[done] $tag"
}

run_cfg QuComm-default &
run_cfg QuComm-next-k          "${LOOKAHEAD_BASE[@]}" --qucomm_future_window_mode serial &
run_cfg IRIS-single-candidate  "${LOOKAHEAD_BASE[@]}" --qucomm_future_window_mode future_partner &
run_cfg IRIS-next-k            "${LOOKAHEAD_BASE[@]}" --qucomm_future_window_mode serial --qucomm_enable_gate_foresight &
run_cfg IRIS-default           "${IRIS_LOOKAHEAD_ARGS[@]}" &
wait

python "$SCRIPT_DIR/plot/fig_13_contrib.py" \
       --root "$ABL_ROOT" --bench "$BENCH" --archdir "$ARCHDIR" \
       --output "$FIGURES_DIR/fig_contrib_${BENCH_FAMILY}.pdf"
echo "Contribution breakdown -> $FIGURES_DIR/fig_contrib_${BENCH_FAMILY}.pdf"
