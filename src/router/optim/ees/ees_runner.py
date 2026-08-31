"""EES (Early Execution Engine) runner."""
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from utils import atomic_json_dump
from ..early_execution import pipeline_optimization, remove_duplicate_rows
from .pipeline_builder import build_pipeline_from_schedules
Row = Dict[str, Any]

def run_ees(schedules: List[List[Row]], initial_channel_dict: Dict[Tuple, int], num_communication_qubits: int, output_base: str, mode_tag: str, enable_ees: bool=False, save_pipeline_json: bool=False) -> Tuple[Optional[List[List[Row]]], Optional[Dict[int, List[Row]]], float]:
    """Run the EES pipeline: build, save, optionally optimise."""
    (pipeline, _) = build_pipeline_from_schedules(schedules)
    pipeline = remove_duplicate_rows(pipeline)
    base = Path(output_base)
    if save_pipeline_json:
        os.makedirs(base, exist_ok=True)
        atomic_json_dump(pipeline, base / f'no-opt-{mode_tag}.json', sort_keys=True)
    opt_pipeline = None
    early_executed_dict = None
    start = time.time()
    if enable_ees:
        (opt_pipeline, early_executed_dict) = pipeline_optimization(pipeline, initial_channel_dict, 0, num_communication_qubits * 2)
        if save_pipeline_json:
            atomic_json_dump(opt_pipeline, base / f'opt-{mode_tag}.json', sort_keys=True)
    elapsed = time.time() - start
    return (opt_pipeline, early_executed_dict, elapsed)