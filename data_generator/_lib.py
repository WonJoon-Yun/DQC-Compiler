"""Shared helpers for AE data_generator scripts.

Every generator script in `data_generator/section*` and `data_generator/appendix_*`
uses these helpers to locate result JSONs from `results/_full/`, route outputs to
`data_generator/output/`, and pull benchmark sources from `bench/`.

All paths resolve relative to the AE artifact root (the dir containing `src/`,
`bench/`, `results/`, etc.). Override with env vars when needed:

    ARTIFACT_ROOT   override the artifact root
    RESULTS_BASE    override the results tree (default: $ARTIFACT_ROOT/results/_full)
    BENCH_DIR       override the bench tree  (default: $ARTIFACT_ROOT/bench)
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

# ---------- root resolution ----------

def _find_artifact_root() -> Path:
    if env := os.environ.get("ARTIFACT_ROOT"):
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for cand in (here.parent, *here.parents):
        if (cand / "src").is_dir() and (cand / "bench").is_dir():
            return cand
    return here.parents[1]


ARTIFACT_ROOT = _find_artifact_root()
SRC_DIR = ARTIFACT_ROOT / "src"
BENCH_DIR = Path(os.environ.get("BENCH_DIR", ARTIFACT_ROOT / "bench"))
RESULTS_BASE = Path(os.environ.get("RESULTS_BASE", ARTIFACT_ROOT / "results" / "_full"))

DATA_GEN_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = DATA_GEN_ROOT / "output"

FOCUS_BENCH = os.environ.get("FOCUS_BENCH", "qaoa_fc_n240")
FOCUS_ARCH = os.environ.get("FOCUS_ARCH", "F240")


# ---------- output routing ----------

def output_dir(section: str) -> Path:
    """Ensure and return data_generator/output/<section>/."""
    out = OUTPUT_ROOT / section
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------- result-tree helpers ----------

def _arch_dir_suffix(arch: str) -> str:
    """F120/F180/F240 → leaf-dir name (S<sys>C<comm>-<rx>x<cy>)."""
    presets = {
        "F120":  "S40C5-2x2",
        "F180":  "S42C5-2x3",
        "F240":  "S40C5-3x3",
        "F500":  "S180C18-2x2",
        "F800":  "S180C18-2x3",
        "F1100": "S180C18-3x3",
    }
    return presets.get(arch, arch)


# artifact names <-> IRIS-dataset directory names (results are stored in the
# dataset's own layout: <Mapping>/<Scheduling>/<bench>-<archdir>/)
_DS_MAPPER = {"ILP": "MinCut", "GCP-ILP": "GCP-E", "OEE-ILP": "sOEE", "WBCP": "WBCP"}
_DS_SCHED = {"QuComm": "QuComm", "IRIS-opt0": "IRIS-noEES", "IRIS-opt1": "IRIS"}


def result_dir(variant: str, arch: str, mapper: str, bench: str) -> Path:
    """Return the run dir holding results*.json / [Ss]chedule*.json for one run.

    Layout matches the IRIS-dataset: <Mapping>/<Scheduling>/<bench>-<archdir>/

    variant: QuComm | IRIS-opt0 | IRIS-opt1
    arch:    F120 | F180 | F240 | F500 | F800 | F1100 | S<S>C<C>-<X>x<Y>
    mapper:  ILP | GCP-ILP | OEE-ILP | WBCP
    bench:   e.g. "bv_n120", "qaoa_3reg_n240"
    """
    arch_suffix = _arch_dir_suffix(arch)
    return (RESULTS_BASE / _DS_MAPPER.get(mapper, mapper)
            / _DS_SCHED.get(variant, variant) / f"{bench}-{arch_suffix}")


def result_json(variant: str, arch: str, mapper: str, bench: str) -> Optional[Path]:
    d = result_dir(variant, arch, mapper, bench)
    matches = sorted(d.glob("results*.json")) or sorted(d.glob("results*.json.gz"))
    return matches[0] if matches else None


def schedule_json(variant: str, arch: str, mapper: str, bench: str) -> Optional[Path]:
    d = result_dir(variant, arch, mapper, bench)
    matches = sorted(d.glob("[Ss]chedule*.json")) or sorted(d.glob("[Ss]chedule*.json.gz"))
    return matches[0] if matches else None


def tracer_csv(variant: str, arch: str, mapper: str, bench: str) -> Optional[Path]:
    d = result_dir(variant, arch, mapper, bench)
    matches = sorted(d.glob("[Tt]racer*.csv")) or sorted(d.glob("[Tt]racer*.csv.gz"))
    return matches[0] if matches else None


def extra_opt_json(arch: str, mapper: str, bench: str) -> Optional[Path]:
    """IRIS-opt1 post-hoc extra-opt JSON, or None.

    Falls back to the sidecar cache written by get_data_all.sh --from_dataset
    ($EXTRA_OPT_CACHE/<Mapping>/IRIS/<bench>-<archdir>/extra_opt.json), so the
    same EES-replay latency definition works for both data sources.
    """
    p = result_dir("IRIS-opt1", arch, mapper, bench) / "extra_opt.json"
    if p.exists():
        return p
    cache = os.environ.get("EXTRA_OPT_CACHE")
    if cache:
        rel = p.relative_to(RESULTS_BASE)
        c = Path(cache) / rel
        if c.exists():
            return c
    return None


def load_json(p: Path) -> dict:
    """Read a JSON file (plain or .gz), bypassing polluted stdlib json.load."""
    if str(p).endswith(".gz"):
        return json.loads(gzip.decompress(p.read_bytes()))
    return json.loads(p.read_text())


# ---------- bench helpers ----------

def bench_qasm(family: str, n: int) -> Path:
    """Return bench/<family>/<family>_n<N>.qasm."""
    return BENCH_DIR / family / f"{family}_n{n}.qasm"


# ---------- arch parameters ----------

def link_epr_capacity(arch: str) -> int:
    presets = {"F120": 5, "F180": 5, "F240": 5, "F500": 18, "F800": 18, "F1100": 18}
    return presets.get(arch, 5)


def numchiplets(arch: str) -> Tuple[int, int]:
    presets = {
        "F120":  (2, 2),
        "F180":  (2, 3),
        "F240":  (3, 3),
        "F500":  (2, 2),
        "F800":  (2, 3),
        "F1100": (3, 3),
    }
    return presets.get(arch, (1, 1))


# ---------- subprocess helper ----------

def run(cmd: Iterable[str], env: Optional[dict] = None) -> None:
    cmd_list = list(cmd)
    print(f"[run] {' '.join(cmd_list)}", flush=True)
    subprocess.run(cmd_list, check=True, env=env)


def python_env() -> str:
    return os.environ.get("PYTHON", sys.executable)


# ---------- benchmark / variant sets ----------

BENCH_FAMILIES = ("bv", "qaoa_3reg", "qaoa_fc", "qft", "qugan", "qv", "shor", "vqe")
VARIANTS_3 = ("QuComm", "IRIS-opt0", "IRIS-opt1")
ARCH_SIZE = {"F120": 120, "F180": 180, "F240": 240, "F500": 500, "F800": 800, "F1100": 1100}

# ---------- T_eff metric ----------

# Per the paper:
#   T_eff = #state_teleportations + #gate_teleportations * 1.77
# (state teleportation = RELOCATE-based remote CNOT; gate teleportation = Re-CNOT;
#  the 1.77 weight reflects the extra EPR-pair / classical-communication cost of
#  a non-local two-qubit gate vs. moving a qubit then doing a local CNOT.)

RE_CNOT_WEIGHT = 1.77


def compute_teff(d: dict) -> float:
    """T_eff = #state_teleportations + #gate_teleportations * 1.77."""
    st = float(d.get("num_state_teleportations", 0) or 0)
    gt = float(d.get("num_gate_teleportations", 0) or 0)
    return st + gt * RE_CNOT_WEIGHT
