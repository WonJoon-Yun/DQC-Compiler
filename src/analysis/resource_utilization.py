from __future__ import annotations

import ast
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from utils import atomic_json_dump


Node = tuple[int, int]
Edge = tuple[Node, Node]

TRACER_UTILIZATION_COLUMNS = [
    "chip0_id",
    "chip1_id",
    "chip0_compute_capacity_current",
    "chip1_compute_capacity_current",
    "chip0_resident_data_qubits_current",
    "chip1_resident_data_qubits_current",
    "chip0_active_compute_qubits_current",
    "chip1_active_compute_qubits_current",
    "chip0_resident_compute_utilization_current",
    "chip1_resident_compute_utilization_current",
    "chip0_active_compute_utilization_current",
    "chip1_active_compute_utilization_current",
    "link_id",
    "link_capacity_current",
    "link_active_relocates_current",
    "link_utilization_current",
]


def _parse_node(value: Any) -> Node | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = ast.literal_eval(text)
        except Exception:
            return None
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and all(isinstance(v, (int, float)) for v in value[:2]):
            return int(value[0]), int(value[1])
        if value:
            return _parse_node(value[0])
    return None


def _extract_chip(pos: Any) -> Node | None:
    return _parse_node(pos)


def _normalize_edge(a: Node, b: Node) -> Edge:
    return tuple(sorted((tuple(a), tuple(b))))  # type: ignore[return-value]


def _chip_label(node: Node | None) -> str | None:
    if node is None:
        return None
    return f"({node[0]},{node[1]})"


def _edge_label(edge: Edge | None) -> str | None:
    if edge is None:
        return None
    (ax, ay), (bx, by) = edge
    return f"({ax},{ay})-({bx},{by})"


def _build_grid_edges(numchipletsx: int, numchipletsy: int) -> list[Edge]:
    edges: list[Edge] = []
    for x in range(numchipletsx):
        for y in range(numchipletsy):
            if x + 1 < numchipletsx:
                edges.append(_normalize_edge((x, y), (x + 1, y)))
            if y + 1 < numchipletsy:
                edges.append(_normalize_edge((x, y), (x, y + 1)))
    return sorted(set(edges), key=str)


def _neighbor_count(node: Node, numchipletsx: int, numchipletsy: int) -> int:
    x, y = node
    count = 0
    if x > 0:
        count += 1
    if x + 1 < numchipletsx:
        count += 1
    if y > 0:
        count += 1
    if y + 1 < numchipletsy:
        count += 1
    return count


def _default_compute_capacity(result_data: dict[str, Any]) -> dict[Node, int]:
    numchipletsx = int(result_data.get("numchipletsx", 0) or 0)
    numchipletsy = int(result_data.get("numchipletsy", 0) or 0)
    capacities: dict[Node, int] = {}
    if not numchipletsx or not numchipletsy:
        return capacities

    if result_data.get("system_qubits_per_chip") is not None and result_data.get("num_communication_per_link") is not None:
        system_qubits_per_chip = int(result_data["system_qubits_per_chip"])
        comm_per_link = int(result_data["num_communication_per_link"])
        for x in range(numchipletsx):
            for y in range(numchipletsy):
                node = (x, y)
                capacities[node] = int(system_qubits_per_chip - comm_per_link * _neighbor_count(node, numchipletsx, numchipletsy))
        return capacities

    numx = int(result_data.get("numx", 0) or 0)
    numy = int(result_data.get("numy", 0) or 0)
    if not numx or not numy:
        return capacities
    base = int(numx * numy * 2)
    for x in range(numchipletsx):
        for y in range(numchipletsy):
            capacities[(x, y)] = base
    return capacities


def _default_channel_capacity(result_data: dict[str, Any]) -> dict[Edge, int]:
    numchipletsx = int(result_data.get("numchipletsx", 0) or 0)
    numchipletsy = int(result_data.get("numchipletsy", 0) or 0)
    default_cap = (
        result_data.get("pre_schedule_default_comm_qubits")
        or result_data.get("num_communication_per_link")
        or result_data.get("num_communication_qubits")
        or 0
    )
    default_cap = int(default_cap)
    capacities = {
        edge: default_cap
        for edge in _build_grid_edges(numchipletsx, numchipletsy)
    }
    for override in result_data.get("pre_schedule_channel_overrides") or []:
        src = _parse_node(override.get("src"))
        dst = _parse_node(override.get("dst"))
        if src is None or dst is None:
            continue
        capacities[_normalize_edge(src, dst)] = int(override.get("capacity", default_cap))
    return capacities


def _serialize_epoch_maps(
    *,
    start_time: float,
    label: str,
    channel_capacity: dict[Edge, int],
    compute_capacity: dict[Node, int],
    resident_data_qubits: dict[Node, int],
) -> dict[str, Any]:
    return {
        "label": label,
        "start_time": float(start_time),
        "channel_capacity": [
            {
                "src": list(src),
                "dst": list(dst),
                "capacity": int(cap),
            }
            for (src, dst), cap in sorted(channel_capacity.items(), key=lambda item: str(item[0]))
        ],
        "compute_capacity": [
            {
                "chip": list(node),
                "capacity": int(cap),
            }
            for node, cap in sorted(compute_capacity.items(), key=lambda item: str(item[0]))
        ],
        "resident_data_qubits": [
            {
                "chip": list(node),
                "count": int(count),
            }
            for node, count in sorted(resident_data_qubits.items(), key=lambda item: str(item[0]))
        ],
    }


def ensure_resource_capacity_epochs(result_data: dict[str, Any]) -> list[dict[str, Any]]:
    epochs = result_data.get("resource_capacity_epochs")
    if epochs:
        return list(epochs)

    compute_capacity = _default_compute_capacity(result_data)
    for key, value in (result_data.get("pre_schedule_compute_capacity") or {}).items():
        node = _parse_node(key)
        if node is not None:
            compute_capacity[node] = int(value)

    resident_data_qubits: dict[Node, int] = {}
    for key, value in (result_data.get("pre_schedule_chip_data_qubit_counts") or {}).items():
        node = _parse_node(key)
        if node is not None:
            resident_data_qubits[node] = int(value)

    epoch = _serialize_epoch_maps(
        start_time=0.0,
        label="pre_schedule",
        channel_capacity=_default_channel_capacity(result_data),
        compute_capacity=compute_capacity,
        resident_data_qubits=resident_data_qubits,
    )
    result_data["resource_capacity_epochs"] = [epoch]
    return [epoch]


def _normalize_epoch_list(result_data: dict[str, Any]) -> list[dict[str, Any]]:
    epochs = ensure_resource_capacity_epochs(result_data)
    normalized: list[dict[str, Any]] = []
    for raw in epochs:
        channel_capacity: dict[Edge, int] = {}
        for item in raw.get("channel_capacity") or []:
            src = _parse_node(item.get("src"))
            dst = _parse_node(item.get("dst"))
            if src is None or dst is None:
                continue
            channel_capacity[_normalize_edge(src, dst)] = int(item.get("capacity", 0))

        compute_capacity: dict[Node, int] = {}
        raw_compute = raw.get("compute_capacity") or []
        if isinstance(raw_compute, dict):
            raw_compute = [{"chip": k, "capacity": v} for k, v in raw_compute.items()]
        for item in raw_compute:
            node = _parse_node(item.get("chip"))
            if node is None:
                continue
            compute_capacity[node] = int(item.get("capacity", 0))

        resident_data_qubits: dict[Node, int] = {}
        raw_resident = raw.get("resident_data_qubits") or []
        if isinstance(raw_resident, dict):
            raw_resident = [{"chip": k, "count": v} for k, v in raw_resident.items()]
        for item in raw_resident:
            node = _parse_node(item.get("chip"))
            if node is None:
                continue
            resident_data_qubits[node] = int(item.get("count", 0))

        normalized.append(
            {
                "label": str(raw.get("label", "epoch")),
                "start_time": float(raw.get("start_time", 0.0)),
                "channel_capacity": channel_capacity,
                "compute_capacity": compute_capacity,
                "resident_data_qubits": resident_data_qubits,
            }
        )
    normalized.sort(key=lambda item: float(item["start_time"]))
    return normalized


def _row_compute_contribution(row: Any) -> Counter[Node]:
    contributions: Counter[Node] = Counter()
    seen_pairs: set[tuple[Any, Node]] = set()
    chip0 = _extract_chip(getattr(row, "pos0", None))
    chip1 = _extract_chip(getattr(row, "pos1", None))

    atom0 = getattr(row, "atom0", None)
    atom1 = getattr(row, "atom1", None)

    if chip0 is not None and atom0 is not None:
        seen_pairs.add((atom0, chip0))
    if chip1 is not None and atom1 is not None:
        seen_pairs.add((atom1, chip1))

    for _, chip in seen_pairs:
        contributions[chip] += 1
    return contributions


def _build_network_segments(tracer_df: pd.DataFrame, epochs: list[dict[str, Any]]) -> pd.DataFrame:
    runtime = float(tracer_df["end_time"].max()) if not tracer_df.empty else 0.0
    event_times = {0.0, runtime}
    events_by_edge: dict[Edge, list[tuple[float, int]]] = defaultdict(list)

    for row in tracer_df.itertuples(index=False):
        if str(getattr(row, "optype", "")) != "RELOCATE":
            continue
        src = _extract_chip(getattr(row, "pos0", None))
        dst = _extract_chip(getattr(row, "pos1", None))
        if src is None or dst is None or src == dst:
            continue
        edge = _normalize_edge(src, dst)
        t_start = float(getattr(row, "start_time", 0.0))
        t_end = float(getattr(row, "end_time", t_start))
        if t_end < t_start:
            t_start, t_end = t_end, t_start
        events_by_edge[edge].append((t_start, +1))
        events_by_edge[edge].append((t_end, -1))
        event_times.add(t_start)
        event_times.add(t_end)

    event_times.update(float(epoch["start_time"]) for epoch in epochs)
    timeline = sorted(event_times)
    if len(timeline) < 2:
        timeline = [0.0, runtime]

    all_edges = set(events_by_edge)
    for epoch in epochs:
        all_edges.update(epoch["channel_capacity"].keys())
        for start_time in (float(epoch["start_time"]),):
            if start_time not in event_times and start_time < runtime:
                timeline.append(start_time)
    timeline = sorted(set(timeline))

    edge_events = {edge: sorted(vals) for edge, vals in events_by_edge.items()}
    edge_indices = {edge: 0 for edge in all_edges}
    active_counts = {edge: 0 for edge in all_edges}

    records: list[dict[str, Any]] = []
    epoch_idx = 0
    for idx in range(len(timeline) - 1):
        t_start = float(timeline[idx])
        t_end = float(timeline[idx + 1])
        if t_end <= t_start:
            continue
        while epoch_idx + 1 < len(epochs) and float(epochs[epoch_idx + 1]["start_time"]) <= t_start + 1e-15:
            epoch_idx += 1
        current_epoch = epochs[epoch_idx]

        for edge in all_edges:
            vals = edge_events.get(edge, [])
            ptr = edge_indices[edge]
            while ptr < len(vals) and vals[ptr][0] <= t_start + 1e-15:
                active_counts[edge] += vals[ptr][1]
                ptr += 1
            edge_indices[edge] = ptr
            capacity = int(current_epoch["channel_capacity"].get(edge, 0))
            active = int(active_counts[edge])
            records.append(
                {
                    "t_start": t_start,
                    "t_end": t_end,
                    "edge": edge,
                    "link_id": _edge_label(edge),
                    "active_relocates": active,
                    "capacity": capacity,
                    "utilization": float(active) / float(capacity) if capacity > 0 else 0.0,
                    "epoch_label": current_epoch["label"],
                }
            )

    return pd.DataFrame.from_records(records)


def _build_compute_segments(tracer_df: pd.DataFrame, epochs: list[dict[str, Any]]) -> pd.DataFrame:
    runtime = float(tracer_df["end_time"].max()) if not tracer_df.empty else 0.0
    event_times = {0.0, runtime}
    events_by_chip: dict[Node, list[tuple[float, int]]] = defaultdict(list)

    for row in tracer_df.itertuples(index=False):
        contributions = _row_compute_contribution(row)
        if not contributions:
            continue
        t_start = float(getattr(row, "start_time", 0.0))
        t_end = float(getattr(row, "end_time", t_start))
        if t_end < t_start:
            t_start, t_end = t_end, t_start
        for chip, amount in contributions.items():
            events_by_chip[chip].append((t_start, +int(amount)))
            events_by_chip[chip].append((t_end, -int(amount)))
        event_times.add(t_start)
        event_times.add(t_end)

    event_times.update(float(epoch["start_time"]) for epoch in epochs)
    timeline = sorted(event_times)
    if len(timeline) < 2:
        timeline = [0.0, runtime]

    all_chips = set(events_by_chip)
    for epoch in epochs:
        all_chips.update(epoch["compute_capacity"].keys())
        all_chips.update(epoch["resident_data_qubits"].keys())
    chip_events = {chip: sorted(vals) for chip, vals in events_by_chip.items()}
    chip_indices = {chip: 0 for chip in all_chips}
    active_counts = {chip: 0 for chip in all_chips}

    records: list[dict[str, Any]] = []
    epoch_idx = 0
    for idx in range(len(timeline) - 1):
        t_start = float(timeline[idx])
        t_end = float(timeline[idx + 1])
        if t_end <= t_start:
            continue
        while epoch_idx + 1 < len(epochs) and float(epochs[epoch_idx + 1]["start_time"]) <= t_start + 1e-15:
            epoch_idx += 1
        current_epoch = epochs[epoch_idx]

        for chip in all_chips:
            vals = chip_events.get(chip, [])
            ptr = chip_indices[chip]
            while ptr < len(vals) and vals[ptr][0] <= t_start + 1e-15:
                active_counts[chip] += vals[ptr][1]
                ptr += 1
            chip_indices[chip] = ptr
            capacity = int(current_epoch["compute_capacity"].get(chip, 0))
            resident = int(current_epoch["resident_data_qubits"].get(chip, 0))
            active = int(active_counts[chip])
            records.append(
                {
                    "t_start": t_start,
                    "t_end": t_end,
                    "chip": chip,
                    "chip_id": _chip_label(chip),
                    "active_compute_qubits": active,
                    "resident_data_qubits": resident,
                    "capacity": capacity,
                    "active_utilization": float(active) / float(capacity) if capacity > 0 else 0.0,
                    "resident_utilization": float(resident) / float(capacity) if capacity > 0 else 0.0,
                    "epoch_label": current_epoch["label"],
                }
            )

    return pd.DataFrame.from_records(records)


def _summarize_network_segments(network_df: pd.DataFrame) -> list[dict[str, Any]]:
    if network_df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for link_id, sub in network_df.groupby("link_id", dropna=False):
        runtime = float((sub["t_end"] - sub["t_start"]).sum())
        weighted_util = float(((sub["t_end"] - sub["t_start"]) * sub["utilization"]).sum())
        rows.append(
            {
                "link_id": link_id,
                "capacity_min": int(sub["capacity"].min()) if not sub.empty else 0,
                "capacity_max": int(sub["capacity"].max()) if not sub.empty else 0,
                "avg_utilization": weighted_util / runtime if runtime > 0 else 0.0,
                "peak_utilization": float(sub["utilization"].max()) if not sub.empty else 0.0,
                "peak_active_relocates": int(sub["active_relocates"].max()) if not sub.empty else 0,
                "runtime": runtime,
            }
        )
    rows.sort(key=lambda row: str(row["link_id"]))
    return rows


def _summarize_compute_segments(compute_df: pd.DataFrame) -> list[dict[str, Any]]:
    if compute_df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for chip_id, sub in compute_df.groupby("chip_id", dropna=False):
        runtime = float((sub["t_end"] - sub["t_start"]).sum())
        weighted_active = float(((sub["t_end"] - sub["t_start"]) * sub["active_utilization"]).sum())
        weighted_resident = float(((sub["t_end"] - sub["t_start"]) * sub["resident_utilization"]).sum())
        rows.append(
            {
                "chip_id": chip_id,
                "capacity_min": int(sub["capacity"].min()) if not sub.empty else 0,
                "capacity_max": int(sub["capacity"].max()) if not sub.empty else 0,
                "resident_qubits_max": int(sub["resident_data_qubits"].max()) if not sub.empty else 0,
                "avg_active_utilization": weighted_active / runtime if runtime > 0 else 0.0,
                "peak_active_utilization": float(sub["active_utilization"].max()) if not sub.empty else 0.0,
                "avg_resident_utilization": weighted_resident / runtime if runtime > 0 else 0.0,
                "peak_active_compute_qubits": int(sub["active_compute_qubits"].max()) if not sub.empty else 0,
                "runtime": runtime,
            }
        )
    rows.sort(key=lambda row: str(row["chip_id"]))
    return rows


def _build_segment_lookup(df: pd.DataFrame, key_col: str) -> dict[Any, tuple[list[float], list[float], list[dict[str, Any]]]]:
    lookups: dict[Any, tuple[list[float], list[float], list[dict[str, Any]]]] = {}
    if df.empty:
        return lookups
    for key, sub in df.groupby(key_col, dropna=False):
        ordered = sub.sort_values(["t_start", "t_end"]).to_dict(orient="records")
        starts = [float(row["t_start"]) for row in ordered]
        ends = [float(row["t_end"]) for row in ordered]
        lookups[key] = (starts, ends, ordered)
    return lookups


def _lookup_segment(lookup: dict[Any, tuple[list[float], list[float], list[dict[str, Any]]]], key: Any, t: float) -> dict[str, Any] | None:
    data = lookup.get(key)
    if data is None:
        return None
    starts, ends, rows = data
    idx = bisect_right(starts, t) - 1
    if idx < 0 or idx >= len(rows):
        return None
    if t > ends[idx] + 1e-12:
        return None
    return rows[idx]


def _build_tracer_annotations(
    tracer_df: pd.DataFrame,
    network_df: pd.DataFrame,
    compute_df: pd.DataFrame,
) -> dict[int, dict[str, Any]]:
    network_lookup = _build_segment_lookup(network_df, "edge")
    compute_lookup = _build_segment_lookup(compute_df, "chip")
    annotations: dict[int, dict[str, Any]] = {}

    for row in tracer_df.itertuples(index=False):
        count = int(getattr(row, "count"))
        midpoint = (float(getattr(row, "start_time", 0.0)) + float(getattr(row, "end_time", 0.0))) / 2.0
        chip0 = _extract_chip(getattr(row, "pos0", None))
        chip1 = _extract_chip(getattr(row, "pos1", None))
        ann: dict[str, Any] = {
            "chip0_id": _chip_label(chip0),
            "chip1_id": _chip_label(chip1),
        }

        chip0_seg = _lookup_segment(compute_lookup, chip0, midpoint) if chip0 is not None else None
        chip1_seg = _lookup_segment(compute_lookup, chip1, midpoint) if chip1 is not None else None
        if chip0_seg is not None:
            ann.update(
                {
                    "chip0_compute_capacity_current": int(chip0_seg["capacity"]),
                    "chip0_resident_data_qubits_current": int(chip0_seg["resident_data_qubits"]),
                    "chip0_active_compute_qubits_current": int(chip0_seg["active_compute_qubits"]),
                    "chip0_resident_compute_utilization_current": float(chip0_seg["resident_utilization"]),
                    "chip0_active_compute_utilization_current": float(chip0_seg["active_utilization"]),
                }
            )
        if chip1_seg is not None:
            ann.update(
                {
                    "chip1_compute_capacity_current": int(chip1_seg["capacity"]),
                    "chip1_resident_data_qubits_current": int(chip1_seg["resident_data_qubits"]),
                    "chip1_active_compute_qubits_current": int(chip1_seg["active_compute_qubits"]),
                    "chip1_resident_compute_utilization_current": float(chip1_seg["resident_utilization"]),
                    "chip1_active_compute_utilization_current": float(chip1_seg["active_utilization"]),
                }
            )

        if str(getattr(row, "optype", "")) == "RELOCATE" and chip0 is not None and chip1 is not None and chip0 != chip1:
            edge = _normalize_edge(chip0, chip1)
            edge_seg = _lookup_segment(network_lookup, edge, midpoint)
            ann["link_id"] = _edge_label(edge)
            if edge_seg is not None:
                ann.update(
                    {
                        "link_capacity_current": int(edge_seg["capacity"]),
                        "link_active_relocates_current": int(edge_seg["active_relocates"]),
                        "link_utilization_current": float(edge_seg["utilization"]),
                    }
                )

        annotations[count] = ann

    return annotations


def _write_summary_markdown(
    path: Path,
    result_data: dict[str, Any],
    network_summary: list[dict[str, Any]],
    compute_summary: list[dict[str, Any]],
) -> None:
    lines = ["# Utilization Summary", ""]
    lines.append(f"- benchmark: `{result_data.get('name', '')}`")
    lines.append(f"- mapper: `{result_data.get('mapping_method', '')}`")
    lines.append(f"- router: `{result_data.get('routing_method', '')}`")
    lines.append(
        f"- arch: `{result_data.get('system_qubits_per_chip', result_data.get('numx', ''))}`"
    )
    lines.append("")

    lines.append("## Network")
    lines.append("")
    lines.append("| link | capacity min | capacity max | avg util | peak util | peak active relocates |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: |")
    for row in network_summary:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["link_id"]),
                    str(row["capacity_min"]),
                    str(row["capacity_max"]),
                    f"{100.0 * float(row['avg_utilization']):.2f}%",
                    f"{100.0 * float(row['peak_utilization']):.2f}%",
                    str(row["peak_active_relocates"]),
                ]
            )
            + " |"
        )
    lines.append("")

    lines.append("## Compute")
    lines.append("")
    lines.append("| chip | capacity min | capacity max | resident qubits max | avg resident util | avg active util | peak active util | peak active compute qubits |")
    lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in compute_summary:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["chip_id"]),
                    str(row["capacity_min"]),
                    str(row["capacity_max"]),
                    str(row["resident_qubits_max"]),
                    f"{100.0 * float(row['avg_resident_utilization']):.2f}%",
                    f"{100.0 * float(row['avg_active_utilization']):.2f}%",
                    f"{100.0 * float(row['peak_active_utilization']):.2f}%",
                    str(row["peak_active_compute_qubits"]),
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_utilization_artifacts(
    tracer_df: pd.DataFrame,
    result_data: dict[str, Any],
) -> dict[str, Any]:
    epochs = _normalize_epoch_list(result_data)
    network_df = _build_network_segments(tracer_df, epochs)
    compute_df = _build_compute_segments(tracer_df, epochs)
    network_summary = _summarize_network_segments(network_df)
    compute_summary = _summarize_compute_segments(compute_df)
    annotations = _build_tracer_annotations(tracer_df, network_df, compute_df)

    return {
        "resource_capacity_epochs": ensure_resource_capacity_epochs(result_data),
        "network_segments": network_df,
        "compute_segments": compute_df,
        "network_summary": network_summary,
        "compute_summary": compute_summary,
        "tracer_annotations": annotations,
        "summary": {
            "network": network_summary,
            "compute": compute_summary,
        },
    }


def apply_utilization_outputs(
    tracer: Any,
    result_data: dict[str, Any],
    output_dir: str | Path,
    k_suffix: str,
) -> dict[str, Any]:
    tracer_df = tracer.to_dataframe(sort_by_count=True).copy()
    artifacts = build_utilization_artifacts(tracer_df, result_data)
    tracer.annotate_rows(artifacts["tracer_annotations"])

    result_data["resource_capacity_epochs"] = artifacts["resource_capacity_epochs"]
    result_data["utilization_summary"] = artifacts["summary"]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    network_csv = output_dir / f"NetworkUtilization-{k_suffix}.csv"
    network_json = output_dir / f"NetworkUtilization-{k_suffix}.json"
    compute_csv = output_dir / f"ComputeUtilization-{k_suffix}.csv"
    compute_json = output_dir / f"ComputeUtilization-{k_suffix}.json"
    resource_json = output_dir / f"ResourceCapacityEpochs-{k_suffix}.json"
    summary_md = output_dir / f"UtilizationSummary-{k_suffix}.md"

    artifacts["network_segments"].to_csv(network_csv, index=False)
    artifacts["network_segments"].to_json(network_json, orient="records")
    artifacts["compute_segments"].to_csv(compute_csv, index=False)
    artifacts["compute_segments"].to_json(compute_json, orient="records")
    atomic_json_dump(artifacts["resource_capacity_epochs"], resource_json, indent=1)
    _write_summary_markdown(
        summary_md,
        result_data,
        artifacts["network_summary"],
        artifacts["compute_summary"],
    )

    artifacts["saved_paths"] = {
        "network_csv": str(network_csv),
        "network_json": str(network_json),
        "compute_csv": str(compute_csv),
        "compute_json": str(compute_json),
        "resource_json": str(resource_json),
        "summary_md": str(summary_md),
    }
    return artifacts
