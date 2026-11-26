"""Select and independently verify the synchronized schedule used for extra-opt metrics."""
from collections import defaultdict
import re
from typing import Any, Dict, FrozenSet, List, Set, Tuple

from analysis.schedule_locations import (initial_locations, pipeline_rows, read_schedule,
                                         validate_channels, validate_locations)
from router.optim.early_execution import (apply_deltas, is_move_row, qucomm_parallel_schedule,
                                          row_channel_deltas, row_used_qubits)

Pos = Tuple[int, int]
Edge = Tuple[Pos, Pos]
Row = Dict[str, Any]

_ARCH_LINK_CAP = {
    "F120": 5, "F180": 5, "F240": 5,
    "F500": 18, "F800": 18, "F1100": 18,
}


def parse_link_cap(arch: str) -> int:
    if arch in _ARCH_LINK_CAP:
        return _ARCH_LINK_CAP[arch]
    m = re.search(r"C(\d+)", arch)
    if m:
        return int(m.group(1))
    raise SystemExit(f"Cannot infer link_epr_capacity from arch: {arch}")


def _cycle_violations(pipeline, init_ch, min_v, max_v, link_cap):
    violations: List[str] = []
    rows_by_time: Dict[int, List[Row]] = defaultdict(list)
    for r in pipeline:
        rows_by_time[r["Time"]].append(r)

    for t in sorted(rows_by_time):
        seen: Set[int] = set()
        for r in rows_by_time[t]:
            for q in row_used_qubits(r):
                if q in seen:
                    violations.append(f"(a) qubit-collision@{t}: q{q}")
                seen.add(q)

    # Placed rows retain the emitted timestamp. A shared atom must see the
    # same operation order even when all of its gates are on the same chip.
    last_original_start = {}
    for t in sorted(rows_by_time):
        for row in rows_by_time[t]:
            for atom in row_used_qubits(row):
                start = row["_start"]
                if atom in last_original_start and start < last_original_start[atom]:
                    violations.append(f"atom {atom} order@{t}: original start {start} "
                                      f"follows {last_original_start[atom]}")
                last_original_start[atom] = start

    channel = dict(init_ch)
    cap_dir = max_v // 2
    for t in sorted(rows_by_time):
        dir_count: Dict[Edge, int] = defaultdict(int)
        touched: Set[Edge] = set()
        for r in rows_by_time[t]:
            deltas = row_channel_deltas(r)
            for e, dv in deltas:
                if dv > 0:
                    dir_count[e] += 1
                touched.add(e)
            apply_deltas(channel, deltas)
        for e, cnt in dir_count.items():
            if cnt > cap_dir:
                violations.append(f"(d) edge-cap@{t}: {e} {cnt}>{cap_dir}")
        for e in touched:
            v = channel.get(e, 0)
            if v < min_v or v > max_v:
                violations.append(f"(c) cap@{t}: {e}={v} out-of-bounds")

    for t in sorted(rows_by_time):
        link_count: Dict[FrozenSet[Pos], int] = defaultdict(int)
        for r in rows_by_time[t]:
            if r["CNOT"] or not is_move_row(r):
                continue
            if r["SPos"] != r["SNextPos"]:
                link = frozenset({r["SPos"], r["SNextPos"]})
            elif r["TPos"] != r["TNextPos"]:
                link = frozenset({r["TPos"], r["TNextPos"]})
            else:
                continue
            link_count[link] += 1
        for link, cnt in link_count.items():
            if cnt > link_cap:
                violations.append(f"(e) link-cap@{t}: {sorted(link)} {cnt}>{link_cap}")

    return violations


def replay_schedule(path, link_cap=None, *, min_comm_value=-1000, max_comm_value=2000,
                    historical_replay=False):
    """Read and replay an emitted schedule; with a link cap also select its postprocessing."""
    schedule = read_schedule(path)
    initial = initial_locations(schedule)
    original, init_ch = pipeline_rows(schedule.pop("ops"))
    violations = []
    metadata = {"selection": "original_cycles", "candidate_rejection": None, "violations": violations}

    def report(stage, message):
        if historical_replay:
            violations.append(f"{stage}: {message}")
        else:
            raise ValueError(f"({stage}): {message}")

    for validate, context in ((validate_locations, initial), (validate_channels, schedule)):
        try:
            validate(original, context, original_times=True)
        except ValueError as error:
            report("emitted", error)
    if link_cap is None:
        return original, original, metadata

    selected = qucomm_parallel_schedule(
        original, init_ch, min_comm_value, max_comm_value, link_epr_capacity=link_cap,
    )
    metadata["selection"] = "parallelized"
    stage = "postprocessed"
    try:
        validate_channels(selected, schedule)
    except ValueError as error:
        if historical_replay:
            report(stage, error)
        else:
            metadata.update(selection="original_cycles", candidate_rejection=str(error))
            selected = original
            stage = "original_cycles"
            try:
                validate_channels(selected, schedule)
            except ValueError as fallback_error:
                report(stage, fallback_error)

    try:
        validate_locations(selected, initial)
    except ValueError as error:
        report(stage, error)
    cycle_violations = _cycle_violations(selected, init_ch, min_comm_value, max_comm_value, link_cap)
    if cycle_violations:
        report(stage, cycle_violations[0])
    return original, selected, metadata
