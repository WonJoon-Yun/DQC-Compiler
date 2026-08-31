"""Shared plotting helpers and Tracer loading utilities."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

AE_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = AE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

INCLUDED_OPTYPES = {"Local CNOT", "RELOCATE", "Transfer", "Re-CNOT"}


def find_tracer(result_dir: Path) -> Path | None:
    """Find the [Tt]racer*.csv produced by run.py under a result_dir tree."""
    cs = sorted(Path(result_dir).rglob("[Tt]racer*.csv"))
    return cs[0] if cs else None


def find_schedule(result_dir: Path) -> Path | None:
    cs = sorted(Path(result_dir).rglob("[Ss]chedule*.json"))
    return cs[0] if cs else None


def find_results_json(result_dir: Path) -> Path | None:
    cs = sorted(Path(result_dir).rglob("results*.json"))
    return cs[0] if cs else None


def load_tracer_ms(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["optype"].isin(INCLUDED_OPTYPES)].copy()
    df = df.sort_values("end_time").reset_index(drop=True)
    df["start_time"] = df["start_time"] * 1000
    df["end_time"] = df["end_time"] * 1000
    return df


def setup_rcparams(font_size: int = 13):
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Times New Roman"
    plt.rcParams["font.size"] = font_size
    for k in ("axes.titlesize", "axes.labelsize", "xtick.labelsize",
              "ytick.labelsize", "legend.fontsize"):
        plt.rcParams[k] = font_size
    plt.rcParams["pdf.fonttype"] = 42
    plt.rcParams["ps.fonttype"] = 42
