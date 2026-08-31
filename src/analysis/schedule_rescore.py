from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import fields
from pathlib import Path
from typing import Any

import pandas as pd

from hyperparameters import HyperParameters
from router._metrics import MetricsMixin
from tracer._core import TRACER_COLUMNS
from utils import atomic_json_dump


class _ReplayMetrics(MetricsMixin):
    def __init__(self, args: HyperParameters):
        self.args = args
        self.num_CNOTs = 0
        self.num_transfers = 0
        self.num_interconnect_CNOTs = 0
        self.num_interconnect_SWAPs = 0
        self.num_local_cnots = 0
        self.num_state_teleportations = 0
        self.num_gate_teleportations = 0
        self.num_effective_cnots = 0
        self.total_execution_time = 0.0


def _hyperparameter_field_names() -> set[str]:
    return {field.name for field in fields(HyperParameters)}


def build_hyperparameters_from_snapshot(
    snapshot: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> HyperParameters:
    params = HyperParameters()
    valid_fields = _hyperparameter_field_names()
    for source in (snapshot or {}, overrides or {}):
        for key, value in source.items():
            if key in valid_fields and value is not None:
                setattr(params, key, value)
    return params


def _duration_for_operation(args: HyperParameters, optype: str, fallback: float | None = None) -> float:
    if optype in {"Local CNOT", "Local SWAP"}:
        return float(args.time_2Q) + float(args.time_move)
    if optype == "Transfer":
        return float(args.time_transfer) + float(args.time_move)
    if optype == "Re-CNOT":
        return float(args.time_int_2Q)
    if optype == "RELOCATE":
        return float(args.time_int_SWAP)
    if optype == "MOVE":
        return float(args.time_move)
    if fallback is not None:
        return float(fallback)
    return 1e-12


def _tracer_row_from_record(record: dict[str, Any], fidelity: dict[str, Any]) -> dict[str, Any]:
    optype = record["optype"]
    return {
        "count": record["count"],
        "layer_idx": record["schedule_layer_idx"],
        "atom0": record["atom0"],
        "atom1": record["atom1"],
        "pos0": record["pos0"],
        "pos1": record["pos1"],
        "optype": optype,
        "start_time": record["start_time"],
        "end_time": record["end_time"],
        "is_moveback": bool(record.get("is_moveback", False)),
        "display_optype": "Local Ops" if optype in {"Local CNOT", "Local SWAP"} else optype,
        **fidelity,
    }


def _summary_from_replay(
    payload: dict[str, Any],
    args: HyperParameters,
    metrics: _ReplayMetrics,
) -> dict[str, Any]:
    results_snapshot = payload.get("results_snapshot") or {}
    metrics.num_local_cnots = int(metrics.num_CNOTs)
    metrics.num_state_teleportations = int(metrics.num_interconnect_SWAPs)
    metrics.num_gate_teleportations = int(metrics.num_interconnect_CNOTs)
    metrics.num_effective_cnots = int(metrics.effective_number_of_cnots)
    metrics._update_total_fidelity_metrics()

    total_gate_count = results_snapshot.get("total_gate_count")
    if total_gate_count is None:
        total_gate_count = metrics.num_local_cnots + metrics.num_gate_teleportations

    return {
        "total_gate_count": int(total_gate_count),
        "num_local_cnots": metrics.num_local_cnots,
        "num_gate_teleportations": metrics.num_gate_teleportations,
        "num_state_teleportations": metrics.num_state_teleportations,
        "num_effective_cnots": metrics.num_effective_cnots,
        "total_execution_time": float(metrics.total_execution_time),
        "total_fidelity_local_2q": float(metrics.fidelity_2Q),
        "total_fidelity_transfer": float(metrics.fidelity_transfer),
        "total_fidelity_remote_2q": float(metrics.fidelity_remote_2Q_total),
        "total_fidelity_relocation": float(metrics.fidelity_relocation_total),
        "total_fidelity_interconnect": float(metrics.fidelity_int),
        "total_fidelity_deco": float(metrics.fidelity_deco),
        "total_fidelity_total": float(metrics.fidelity_total),
        "latency_penalty": float(metrics.latency_penalty),
        "fidelity_penalty": float(metrics.fidelity_penalty),
        "total_cost": float(metrics.total_cost),
        "fidelity_model": {
            "fidelity_1Q": float(getattr(args, "fidelity_1Q", 1.0)),
            "fidelity_2Q": float(getattr(args, "fidelity_2Q", 1.0)),
            "fidelity_transfer": float(getattr(args, "fidelity_transfer", 1.0)),
            "fidelity_remote_2Q": float(getattr(args, "fidelity_remote_2Q", 1.0)),
            "fidelity_relocation": float(getattr(args, "fidelity_relocation", 1.0)),
            "coherence_time": float(getattr(args, "coherence_time", 0.0)),
            "num_qubits": int(getattr(args, "num_qubits", 0) or 0),
        },
    }


def replay_saved_schedule(
    payload: dict[str, Any],
    args: HyperParameters,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scheduler_policy = payload.get("scheduler_policy") or {}
    if scheduler_policy.get("schedule_cap_channels"):
        raise ValueError(
            "Rescore replay does not support schedules built with schedule_cap_channels=True."
        )

    raw_ops = payload.get("ops") or []
    id_to_record: dict[str, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for count, raw in enumerate(raw_ops):
        record = dict(raw)
        record["count"] = count
        record["dependency_ids"] = list(raw.get("dependency_ids") or [])
        record["duration"] = max(
            _duration_for_operation(
                args,
                str(raw["optype"]),
                raw.get("original_duration"),
            ),
            1e-12,
        )
        record["start_time"] = None
        record["end_time"] = None
        record["is_done"] = False
        pending.append(record)
        id_to_record[str(record["unique_id"])] = record

    records_by_schedule_layer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in pending:
        records_by_schedule_layer[int(record["schedule_layer_idx"])].append(record)

    replay_metrics = _ReplayMetrics(args)
    tracer_rows: list[dict[str, Any]] = []
    done = 0
    current_time = 0.0

    for schedule_layer_idx in sorted(records_by_schedule_layer):
        layer_pending = sorted(
            records_by_schedule_layer[schedule_layer_idx],
            key=lambda record: int(record["count"]),
        )
        running: list[dict[str, Any]] = []

        while layer_pending or running:
            ready = [
                record for record in list(layer_pending)
                if all(id_to_record[dep_id]["is_done"] for dep_id in record["dependency_ids"])
            ]
            ready.sort(key=lambda record: int(record["count"]))
            started_any = False
            for record in ready:
                record["start_time"] = current_time
                running.append(record)
                layer_pending.remove(record)
                started_any = True

            if not running and layer_pending and not started_any:
                raise RuntimeError("Replay deadlock: unresolved dependencies remain in saved schedule.")

            if not running:
                break

            next_finish_time = min(record["start_time"] + record["duration"] for record in running)
            current_time = next_finish_time
            finishing = [
                record for record in running
                if abs(record["start_time"] + record["duration"] - current_time) < 1e-12
            ]
            finishing.sort(key=lambda record: int(record["count"]))

            for record in finishing:
                record["is_done"] = True
                record["end_time"] = current_time
                running.remove(record)
                fidelity = replay_metrics._build_tracer_fidelity_metadata(
                    record["optype"],
                    current_time,
                )
                tracer_rows.append(_tracer_row_from_record(record, fidelity))
                if record["optype"] == "Transfer":
                    replay_metrics.num_transfers += 1
                elif record["optype"] == "Local CNOT":
                    replay_metrics.num_CNOTs += 1
                elif record["optype"] == "Re-CNOT":
                    replay_metrics.num_interconnect_CNOTs += 1
                elif record["optype"] == "RELOCATE":
                    replay_metrics.num_interconnect_SWAPs += 1
                done += 1

    replay_metrics.total_execution_time = current_time
    summary = _summary_from_replay(payload, args, replay_metrics)
    summary["schedule_k_suffix"] = payload.get("k_suffix")
    summary["scheduler_policy"] = scheduler_policy
    return tracer_rows, summary


def save_replay_outputs(
    output_dir: str | Path,
    tag: str,
    tracer_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tracer_df = pd.DataFrame(
        [[row.get(column) for column in TRACER_COLUMNS] for row in tracer_rows],
        columns=TRACER_COLUMNS,
    )

    tracer_json_path = output_dir / f"RescoredTracer-{tag}.json"
    tracer_csv_path = output_dir / f"RescoredTracer-{tag}.csv"
    results_json_path = output_dir / f"rescored-results-{tag}.json"

    tracer_df.to_json(tracer_json_path, orient="records")
    tracer_df.to_csv(tracer_csv_path, index=False)
    atomic_json_dump(summary, results_json_path, indent=1)

    return {
        "results_json": str(results_json_path),
        "tracer_json": str(tracer_json_path),
        "tracer_csv": str(tracer_csv_path),
    }


def load_schedule_payload(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())
