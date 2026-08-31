"""QuComm global foresight planner package."""
from __future__ import annotations
from ._challenger import _resolve_exact_top_tie_with_deeper_horizon
from ._core import _choose_qucomm_global_foresight_plan_opt1, choose_qucomm_global_foresight_plan
from ._utils import _build_block_end_gate_indices, _copy_predicted_state, _flatten_all_gate_specs, _forced_plans_by_block_from_actions, _snapshot_state, _wrap_simulate_result
