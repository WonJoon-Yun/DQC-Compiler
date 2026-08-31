#!/usr/bin/env bash
# Fig 16 / Table 8 sweep runner — fills the dataset-layout sweep directories
# created by scripts/ensure_dataset.sh:
#
#   $RESULTS_DIR/MinCut/{QuComm,IRIS}-bw{2,4,8,16,32}/<bench>-<archdir>/
#   $RESULTS_DIR/MinCut/{QuComm,IRIS}-lh{2,4,6,8,10}/<bench>-<archdir>/
#   $RESULTS_DIR/MinCut/{QuComm,IRIS}-memtrace/<bench>-<archdir>/
#
# The tuple set is exactly the dataset's (whatever was imported). Per-variant
# flags follow the dataset runs' own config snapshots:
#   IRIS-bwN   = IRIS (ForeSight + EES) with --qucomm_gate_lookahead_beam_width N
#   IRIS-lhN   = IRIS with --qucomm_gate_lookahead_depth N  (lh2 also uses beam 32)
#   QuComm-*   = plain QuComm baseline (the sweep flags are inert without lookahead)
#   *-memtrace = same config as the base variant (the memory metric
#                routing_peak_traced_kb is recorded on every run)
#
# WARNING: the full sweep is several hundred runs and can take days of
# compute (qv/qft at n240 with ForeSight are multi-hour runs each). Subset:
#   SCHEDS=IRIS-bw2,IRIS-bw16 BENCH_FILTER=bv_,qaoa_3reg_ bash scripts/fig_16.sh
#
# Runs that already have a results*.json are skipped, so the sweep can be
# resumed after an interruption.

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common_env.sh"
ensure_dirs

SCHEDS_CSV="${SCHEDS:-}"
BENCH_FILTER_CSV="${BENCH_FILTER:-}"

ran=0; skipped=0; missing_bench=0
for sched_path in "$RESULTS_DIR"/MinCut/QuComm-* "$RESULTS_DIR"/MinCut/IRIS-*; do
  [[ -d "$sched_path" ]] || continue
  sched="$(basename "$sched_path")"
  [[ "$sched" == "IRIS-noEES" ]] && continue   # base variant, handled elsewhere
  if [[ -n "$SCHEDS_CSV" ]] && ! grep -q "(^|,)$sched(,|$)" -E <<<"$SCHEDS_CSV"; then
    continue
  fi

  base="${sched%%-*}"          # QuComm | IRIS
  sweep_tag="${sched#*-}"           # bw<N> | lh<N> | memtrace
  EXTRA=()
  if [[ "$base" == "IRIS" ]]; then
    depth=4; beam=16
    case "$sweep_tag" in
      bw*) beam="${sweep_tag#bw}" ;;
      lh*) depth="${sweep_tag#lh}"; [[ "$depth" == "2" ]] && beam=32 ;;
      memtrace) ;;
    esac
    EXTRA=(
      --qucomm_enable_gate_lookahead
      --qucomm_gate_lookahead_depth "$depth"
      --qucomm_gate_lookahead_option opt1
      --qucomm_gate_lookahead_beam_width "$beam"
      --qucomm_gate_lookahead_sort_mode current_then_total
      --qucomm_gate_lookahead_prune_mode selection_sort
      --qucomm_future_block_decay_mode linear
      --qucomm_future_window_mode future_partner_ranked
      --qucomm_enable_gate_foresight
      --enable_ees
    )
  else
    # QuComm sweep rows are the plain baseline; pass the (inert) sweep_tag values
    # so the recorded config snapshot matches the dataset's.
    case "$sweep_tag" in
      bw*) EXTRA=(--qucomm_gate_lookahead_beam_width "${sweep_tag#bw}") ;;
      lh*) [[ "$sweep_tag" == "lh2" ]] && EXTRA=(--qucomm_gate_lookahead_beam_width 32) ;;
      memtrace) ;;
    esac
  fi

  for run_dir in "$sched_path"/*/; do
    [[ -d "$run_dir" ]] || continue
    name="$(basename "$run_dir")"            # <bench>-<archdir>
    archdir="S${name##*-S}"
    bench="${name%-"$archdir"}"
    if [[ -n "$BENCH_FILTER_CSV" ]]; then
      keep=0
      IFS=',' read -r -a pats <<< "$BENCH_FILTER_CSV"
      for p in "${pats[@]}"; do [[ "$bench" == ${p}* ]] && keep=1; done
      [[ $keep -eq 1 ]] || continue
    fi
    if ls "$run_dir"/results*.json >/dev/null 2>&1; then
      skipped=$((skipped+1)); continue
    fi
    family="${bench%_n*}"
    qasm="$BENCH_DIR/$family/$bench.qasm"
    if [[ ! -f "$qasm" ]]; then
      echo "[miss] $qasm (copy benchmarks: bash scripts/ensure_dataset.sh)"
      missing_bench=$((missing_bench+1)); continue
    fi
    echo "[run] $sched $bench ($archdir)"
    # shellcheck disable=SC2046
    python "$SRC_DIR/run.py" \
        --circuit "$qasm" --name "$bench" \
        --mapping_method ILP \
        --results_dir "${run_dir%/}" --flat_output \
        $(arch_params "$archdir") \
        --oee_max_passes 5 --oee_tol 0.0 \
        "${COMMON_ARGS[@]}" \
        ${EXTRA[@]+"${EXTRA[@]}"}
    ran=$((ran+1))
  done
done

echo "[fig_16] ran=$ran skipped(existing)=$skipped missing_bench=$missing_bench"
echo "[fig_16] collect with: bash data_generator/run_all.sh section6 (figure16 CSV)"
