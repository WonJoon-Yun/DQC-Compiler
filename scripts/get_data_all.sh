#!/usr/bin/env bash
# Stage-2 driver: regenerate the paper's tables/figures data from one of two
# sources that share the same tree layout (<Mapping>/<Scheduling>/<bench>-<arch>/):
#
#   --from_dataset [--dataset PATH]
#       read the pre-computed results shipped in the IRIS-dataset
#       (results.json.gz / schedule.json.gz). IRIS latency is obtained by
#       replaying each IRIS schedule through the EES post-hoc optimizer
#       (the paper's definition); the replay outputs are cached OUTSIDE the
#       dataset under results/_dataset_cache/ and reused on re-runs.
#
#   --from_results [--result-dir DIR]
#       read a runtime-regenerated results tree (default: results/_full,
#       as produced by scripts/reproduce_all.sh). extra_opt.json is already
#       written there by run_iris_opt1.sh.
#
# An optional trailing SECTION argument (e.g. section6, appendix_e) restricts
# the run, mirroring data_generator/run_all.sh.
#
# Usage:
#   bash scripts/get_data_all.sh --from_dataset
#   bash scripts/get_data_all.sh --from_dataset --dataset /path/to/IRIS-dataset section6
#   bash scripts/get_data_all.sh --from_results
#   bash scripts/get_data_all.sh --from_results --result-dir results/_smoke

set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

usage() {
  sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 2
}

MODE=""
DATASET_ARG=""
RESULT_DIR_ARG=""
SECTION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from_dataset) [[ -n "$MODE" ]] && usage; MODE=dataset ;;
    --from_results) [[ -n "$MODE" ]] && usage; MODE=results ;;
    --dataset)      DATASET_ARG="${2:?--dataset needs a path}"; shift ;;
    --result-dir)   RESULT_DIR_ARG="${2:?--result-dir needs a path}"; shift ;;
    -h|--help)      usage ;;
    section*|appendix*) SECTION="$1" ;;
    *) echo "unknown argument: $1"; usage ;;
  esac
  shift
done
[[ -n "$MODE" ]] || usage

if [[ "$MODE" == "dataset" ]]; then
  DS=""
  for cand in "$DATASET_ARG" "$AE_ROOT/IRIS-dataset" "$AE_ROOT/../IRIS-dataset"; do
    if [[ -n "$cand" && -f "$cand/index.json" ]]; then DS="$(cd "$cand" && pwd)"; break; fi
  done
  if [[ -z "$DS" ]]; then
    echo "[error] IRIS-dataset not found (looked at: --dataset, ./IRIS-dataset, ../IRIS-dataset)"
    echo "        download: https://zenodo.org/records/22152933"
    exit 2
  fi
  export RESULTS_BASE="$DS"
  export BENCH_DIR="$DS/bench"

  # IRIS latency sidecar: replay every IRIS schedule in the dataset once and
  # cache extra_opt.json outside the (read-only) dataset tree.
  CACHE="$AE_ROOT/results/_dataset_cache"
  export EXTRA_OPT_CACHE="$CACHE"
  echo "[get_data_all] source: dataset at $DS"
  echo "[get_data_all] EES replay sidecars -> $CACHE (cached; first run ~10 min)"
  for sched_gz in "$DS"/{MinCut,GCP-E,sOEE,WBCP}/IRIS/*/schedule.json.gz; do
    [[ -f "$sched_gz" ]] || continue
    run_dir="$(dirname "$sched_gz")"
    name="$(basename "$run_dir")"
    # flat-pool runs only (<bench>-S<S>C<C>-<X>x<Y>); skip old-model dirs (Fig 24)
    if [[ ! "$name" =~ -(S[0-9]+C[0-9]+-[0-9]+x[0-9]+)$ ]]; then
      continue
    fi
    archdir="${BASH_REMATCH[1]}"
    rel="${run_dir#"$DS"/}"                       # <Mapping>/IRIS/<bench>-<arch>
    out="$CACHE/$rel/extra_opt.json"
    [[ -f "$out" ]] && continue
    mkdir -p "$(dirname "$out")"
    python "$SCRIPT_DIR/apply_extra_opt.py" \
        --schedule "$sched_gz" --arch "$archdir" --out "$out"
  done
else
  RESULT_DIR="${RESULT_DIR_ARG:-$AE_ROOT/results/_full}"
  [[ "$RESULT_DIR" = /* ]] || RESULT_DIR="$AE_ROOT/$RESULT_DIR"
  if [[ ! -d "$RESULT_DIR" ]]; then
    echo "[error] result dir not found: $RESULT_DIR (run scripts/reproduce_all.sh first)"
    exit 2
  fi
  export RESULTS_BASE="$RESULT_DIR"
  export BENCH_DIR="$AE_ROOT/bench"
  echo "[get_data_all] source: results at $RESULT_DIR"
fi

bash "$AE_ROOT/data_generator/run_all.sh" ${SECTION:+"$SECTION"}

# Dataset mode also renders the figures whose data ships in the dataset but
# whose plotters live under scripts/plot (no compiler re-run needed).
if [[ "$MODE" == "dataset" && ( -z "$SECTION" || "$SECTION" == "section6" ) ]]; then
  OUT6="$AE_ROOT/data_generator/output/section6"
  mkdir -p "$OUT6"
  python "$SCRIPT_DIR/plot/fig_12_crval.py" \
      --decisions "$DS/cr_validation/n32/decisions.csv" \
      --output "$OUT6/figure12_crval.pdf"
  python "$SCRIPT_DIR/alpha_retime.py" \
      --qucomm "$DS/MinCut/QuComm/qaoa_3reg_n120-S40C5-2x2" \
      --iris   "$DS/MinCut/IRIS/qaoa_3reg_n120-S40C5-2x2" \
      --out "$OUT6/figure17_alpha_table.json" > /dev/null
  python "$SCRIPT_DIR/plot/fig_17_alpha.py" \
      --table "$OUT6/figure17_alpha_table.json" \
      --output "$OUT6/figure17_alpha.pdf"
  python "$SCRIPT_DIR/plot/fig_18_commbudget.py" \
      --root "$DS" --bench qaoa_3reg_n120 --compute 30 \
      --output "$OUT6/figure18_commbudget.pdf"
fi
echo "[get_data_all] outputs -> data_generator/output/"
