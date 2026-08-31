#!/usr/bin/env bash
# Shared environment for IRIS artifact evaluation scripts.
# Source this from any run_*.sh / fig_*.sh / table_*.sh script.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AE_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SRC_DIR="$AE_ROOT/src"
BENCH_DIR="${BENCH_DIR:-$AE_ROOT/bench}"
RESULTS_DIR="${RESULTS_DIR:-$AE_ROOT/results}"
FIGURES_DIR="${FIGURES_DIR:-$AE_ROOT/figures}"
PLOT_DIR="$SCRIPT_DIR/plot"

# Parallel dispatch fan-out (used by run_parallel.sh and the bulk runners).
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 8)}"

export PYTHONPATH="$SRC_DIR${PYTHONPATH:+:$PYTHONPATH}"

ensure_dirs() {
  mkdir -p "$BENCH_DIR" "$RESULTS_DIR" "$FIGURES_DIR"
}

# --- Common CLI arguments shared across QuComm / IRIS-opt0 / IRIS-opt1 ---
COMMON_ARGS=(
  --K1 1 --K2 6
  --gate_cnt 0
  --qucomm_candidate_eval_mode active_chip_nodes
  --qucomm_one_meet_tiebreak_mode legacy_direct
  --qucomm_enable_teleport_hybrid
)

# --- IRIS lookahead/foresight flags (shared by IRIS-opt0 and IRIS-opt1) ---
IRIS_LOOKAHEAD_ARGS=(
  --qucomm_enable_gate_lookahead
  --qucomm_gate_lookahead_depth 4
  --qucomm_gate_lookahead_option opt1
  --qucomm_gate_lookahead_beam_width 16
  --qucomm_gate_lookahead_sort_mode current_then_total
  --qucomm_gate_lookahead_prune_mode selection_sort
  --qucomm_future_block_decay_mode linear
  --qucomm_future_window_mode future_partner_ranked
  --qucomm_enable_gate_foresight
)

# Emit architecture-specific CLI args for a preset name.
#   F120  -> 2x2, S=40,  C=5    (120 system qubits total)
#   F180  -> 2x3, S=42,  C=5    (252 max)
#   F240  -> 3x3, S=40,  C=5    (~240 program qubits target)
#   F500  -> 2x2, S=180, C=18
#   F800  -> 2x3, S=180, C=18
#   F1100 -> 3x3, S=180, C=18
arch_params() {
  local arch="$1"
  case "$arch" in
    F120)  echo "--numchipletsx 2 --numchipletsy 2 --system_qubits_per_chip 40  --num_communication_per_link 5  --max_1d 10 --routing_method IRIS4" ;;
    F180)  echo "--numchipletsx 2 --numchipletsy 3 --system_qubits_per_chip 42  --num_communication_per_link 5  --max_1d 10 --routing_method IRIS4" ;;
    F240)  echo "--numchipletsx 3 --numchipletsy 3 --system_qubits_per_chip 40  --num_communication_per_link 5  --max_1d 10 --routing_method IRIS4" ;;
    F500)  echo "--numchipletsx 2 --numchipletsy 2 --system_qubits_per_chip 180 --num_communication_per_link 18 --max_1d 10 --routing_method IRIS4" ;;
    F800)  echo "--numchipletsx 2 --numchipletsy 3 --system_qubits_per_chip 180 --num_communication_per_link 18 --max_1d 10 --routing_method IRIS4" ;;
    F1100) echo "--numchipletsx 3 --numchipletsy 3 --system_qubits_per_chip 180 --num_communication_per_link 18 --max_1d 10 --routing_method IRIS4" ;;
    # Generic flat-pool spec S<S>C<C>-<X>x<Y> (QEC codes, Fig-13 sweeps),
    # e.g. S46C5-2x2 = 2x2 chiplets, 46 system qubits/chip, 5 EPR qubits/link.
    S*C*-*x*)
      local s c x y rest
      s="${arch#S}"; s="${s%%C*}"
      c="${arch#*C}"; c="${c%%-*}"
      rest="${arch#*-}"; x="${rest%%x*}"; y="${rest#*x}"
      echo "--numchipletsx $x --numchipletsy $y --system_qubits_per_chip $s --num_communication_per_link $c --max_1d 10 --routing_method IRIS4" ;;
    *) echo "Unknown arch: $arch" >&2; return 1 ;;
  esac
}

# Per-arch link EPR capacity (used by apply_extra_opt.py).
arch_link_cap() {
  case "$1" in
    F120|F180|F240) echo 5 ;;
    F500|F800|F1100) echo 18 ;;
    S*C*-*x*) local c="${1#*C}"; echo "${c%%-*}" ;;
    *) echo "Unknown arch: $1" >&2; return 1 ;;
  esac
}

# --- IRIS-dataset naming (results are stored in the dataset layout) ---
# mapper code -> dataset mapping dir
ds_mapper() {
  case "$1" in
    ILP) echo MinCut ;; GCP-ILP) echo GCP-E ;; OEE-ILP) echo sOEE ;; WBCP) echo WBCP ;;
    *) echo "$1" ;;
  esac
}
# artifact variant -> dataset scheduling dir
ds_sched() {
  case "$1" in
    QuComm) echo QuComm ;; IRIS-opt0) echo IRIS-noEES ;; IRIS-opt1) echo IRIS ;;
    *) echo "$1" ;;
  esac
}
# arch preset -> dataset arch dir suffix (S<S>C<C>-<X>x<Y> specs pass through)
arch_dir() {
  case "$1" in
    F120) echo S40C5-2x2 ;;   F180) echo S42C5-2x3 ;;   F240) echo S40C5-3x3 ;;
    F500) echo S180C18-2x2 ;; F800) echo S180C18-2x3 ;; F1100) echo S180C18-3x3 ;;
    *) echo "$1" ;;
  esac
}

# dataset arch dir -> arch preset name (inverse of arch_dir; S-specs pass through)
arch_preset() {
  case "$1" in
    S40C5-2x2) echo F120 ;;   S42C5-2x3) echo F180 ;;   S40C5-3x3) echo F240 ;;
    S180C18-2x2) echo F500 ;; S180C18-2x3) echo F800 ;; S180C18-3x3) echo F1100 ;;
    *) echo "$1" ;;
  esac
}

# Result directory for one (variant, arch, mapper, bench) tuple —
# identical layout to the IRIS-dataset: <Mapping>/<Scheduling>/<bench>-<archdir>/
result_path() {
  local variant="$1" arch="$2" mapper="$3" bench="$4"
  echo "$RESULTS_DIR/$(ds_mapper "$mapper")/$(ds_sched "$variant")/${bench}-$(arch_dir "$arch")"
}

# Export functions and key vars so xargs-spawned subshells can use them.
export -f arch_params arch_link_cap ds_mapper ds_sched arch_dir arch_preset result_path ensure_dirs
export AE_ROOT SRC_DIR BENCH_DIR RESULTS_DIR FIGURES_DIR PLOT_DIR JOBS
