import bisect
from collections import defaultdict
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

Pos = Tuple[int, int]
Edge = Tuple[Pos, Pos]
Row = Dict[str, Any]  # pipeline entry
PlacementFailure = Dict[str, Any]


def is_move_row(r: Row) -> bool:
    return (r['SPos'] != r['SNextPos']) or (r['TPos'] != r['TNextPos'])


def row_channel_deltas(row: Row) -> List[Tuple[Edge, int]]:
    """Apply edge increment/decrement exactly once per MOVE operation.
    (In standardization, only S is marked as movement, but safely perform deduplication)"""
    # Optimized: Since standardization guarantees only S or T moves, simplify logic
    deltas: List[Tuple[Edge, int]] = []
    if row['SPos'] != row['SNextPos']:
        e = (row['SPos'], row['SNextPos'])
        deltas.append((e, +1))
        deltas.append(((e[1], e[0]), -1))
    elif row['TPos'] != row['TNextPos']:
        e = (row['TPos'], row['TNextPos'])
        deltas.append((e, +1))
        deltas.append(((e[1], e[0]), -1))
    return deltas


def row_used_qubits(row: Row) -> Tuple[int, ...]:
    """Return the qubits consumed by this row at its scheduled time."""
    if row['CNOT'] is True:
        return (row['SIdx'], row['TIdx'])
    if row['SPos'] != row['SNextPos']:
        return (row['SIdx'],)
    if row['TPos'] != row['TNextPos']:
        return (row['TIdx'],)
    return ()


def find_pipeline_conflict(
    pipeline: List[Row],
    initial_channel_dict: Dict[Edge, int],
    min_comm_value: int,
    max_comm_value: int,
) -> Optional[str]:
    """Return the first data/capacity conflict in the pipeline, if any."""
    if not pipeline:
        return None

    rows_by_time: Dict[int, List[Row]] = defaultdict(list)
    for r in pipeline:
        rows_by_time[r['Time']].append(r)

    channel = dict(initial_channel_dict)
    uses_at_time: Dict[int, Set[int]] = defaultdict(set)

    for t in sorted(rows_by_time):
        touched_edges: Set[Edge] = set()
        for r in rows_by_time[t]:
            for q in row_used_qubits(r):
                if q in uses_at_time[t]:
                    return f"data@{t}: q{q}"
                uses_at_time[t].add(q)

            deltas = row_channel_deltas(r)
            if not deltas:
                continue
            apply_deltas(channel, deltas)
            for e, _ in deltas:
                touched_edges.add(e)

        for e in touched_edges:
            val = channel.get(e, 0)
            if val < min_comm_value:
                return f"cap-underflow@{t}: edge {e} -> {val}"

    return None


def repair_pipeline_by_block_shift(
    pipeline: List[Row],
    initial_channel_dict: Dict[Edge, int],
    min_comm_value: int,
    max_comm_value: int,
    log: Callable[[str], None],
    progress_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
    retry_trace_interval: int = 0,
    block_trace_interval: int = 0,
) -> List[Row]:
    """Delay whole blocks just enough to repair input data/capacity conflicts.

    The router can merge block schedules that are atom-disjoint but still
    contend on the same EPR edge. EEE assumes a valid baseline timeline, so
    repair the flat pipeline before attempting early execution.
    """
    if not pipeline:
        return []

    indexed_rows = list(enumerate(pipeline))
    blocks: Dict[int, List[Tuple[int, Row]]] = defaultdict(list)
    for idx, row in indexed_rows:
        blocks[row['BlockID']].append((idx, row))

    block_items = []
    for block_id, entries in blocks.items():
        entries.sort(key=lambda item: (item[1]['Time'], item[0]))
        block_start = min(r['Time'] for _, r in entries)
        rel_rows = []
        for _, row in entries:
            nr = row.copy()
            nr['Time'] = row['Time'] - block_start
            rel_rows.append(nr)
        duration = max(r['Time'] for r in rel_rows)
        first_idx = min(idx for idx, _ in entries)
        block_items.append((block_start, first_idx, block_id, duration, rel_rows))

    block_items.sort(key=lambda item: (item[0], item[1], item[2]))

    t_min = min(r['Time'] for r in pipeline)
    current_t_max = t_min
    channel_t: Dict[int, Dict[Edge, int]] = {t_min: clone_channel_state(initial_channel_dict)}
    uses_at_time: Dict[int, Set[int]] = defaultdict(set)
    repaired: List[Row] = []
    shifted_blocks = 0
    placed_blocks = 0
    retry_count = 0

    def emit_progress(event: str, **metrics: Any) -> None:
        if progress_fn is None:
            return
        payload = {
            "stage": event,
            "current_t_max": current_t_max,
            "channel_t_size": len(channel_t),
            "repaired_row_count": len(repaired),
            "shifted_blocks": shifted_blocks,
        }
        payload.update(metrics)
        progress_fn(payload)

    def ensure_time(t: int) -> None:
        nonlocal current_t_max
        while current_t_max < t:
            channel_t[current_t_max + 1] = clone_channel_state(channel_t[current_t_max])
            current_t_max += 1

    def can_place_block(rel_rows: List[Row], start_try: int) -> Tuple[bool, Optional[PlacementFailure]]:
        deltas_by_time: Dict[int, List[Tuple[Edge, int]]] = defaultdict(list)
        local_uses: Dict[int, Set[int]] = {}
        last_time = start_try

        for row in rel_rows:
            tt = start_try + row['Time']
            last_time = max(last_time, tt)

            for q in row_used_qubits(row):
                used_qubits = uses_at_time.get(tt)
                local_qubits = local_uses.get(tt)
                if (used_qubits is not None and q in used_qubits) or (
                    local_qubits is not None and q in local_qubits
                ):
                    return False, {
                        "kind": "qubit_conflict",
                        "time": tt,
                        "qubit": q,
                        "tail_region": tt > current_t_max,
                        "accepted_conflict": used_qubits is not None and q in used_qubits,
                    }
                if local_qubits is None:
                    local_qubits = set()
                    local_uses[tt] = local_qubits
                local_qubits.add(q)

            deltas = row_channel_deltas(row)
            if deltas:
                deltas_by_time[tt].extend(deltas)

        check_end = max(current_t_max, last_time)
        tail_base = channel_t[current_t_max]
        running_delta: Dict[Edge, int] = defaultdict(int)
        for tt in range(start_try, check_end + 1):
            for e, dv in deltas_by_time.get(tt, []):
                running_delta[e] += dv
                if running_delta[e] == 0:
                    del running_delta[e]

            if not running_delta:
                continue

            # Failed placement trials must not materialize future snapshots into the
            # shared timeline; beyond current_t_max the accepted schedule state is flat.
            base = channel_t[tt] if tt <= current_t_max else tail_base
            for e, dv in running_delta.items():
                new_val = base.get(e, 0) + dv
                if new_val < min_comm_value:
                    return False, {
                        "kind": "channel_underflow",
                        "time": tt,
                        "edge": e,
                        "new_val": new_val,
                        "tail_region": tt > current_t_max,
                    }

        return True, None

    for orig_start, _first_idx, block_id, duration, rel_rows in block_items:
        start_try = orig_start
        while True:
            can_place, failure = can_place_block(rel_rows, start_try)
            if can_place:
                break
            if failure is not None and failure.get("tail_region"):
                emit_progress(
                    "repair_impossible_tail",
                    block_id=block_id,
                    orig_start=orig_start,
                    start_try=start_try,
                    duration=duration,
                    retry_count=retry_count,
                    failure=failure,
                )
                raise ValueError(
                    "Unable to repair pipeline by block shift: "
                    f"block={block_id} start_try={start_try} "
                    f"current_t_max={current_t_max} failure={failure}"
                )
            start_try += 1
            retry_count += 1
            if retry_trace_interval > 0 and retry_count % retry_trace_interval == 0:
                emit_progress(
                    "repair_retry",
                    block_id=block_id,
                    orig_start=orig_start,
                    start_try=start_try,
                    duration=duration,
                    retry_count=retry_count,
                )

        if start_try != orig_start:
            shifted_blocks += 1
            log(f"[repair] block={block_id} {orig_start}->{start_try}")

        ensure_time(start_try + duration)
        placed_blocks += 1

        for row in rel_rows:
            nr = row.copy()
            nr['Time'] = start_try + row['Time']
            repaired.append(nr)

            tt = nr['Time']
            for q in row_used_qubits(nr):
                uses_at_time[tt].add(q)

            deltas = row_channel_deltas(nr)
            if deltas:
                for t_apply in range(tt, current_t_max + 1):
                    apply_deltas(channel_t[t_apply], deltas)

        if block_trace_interval > 0 and placed_blocks % block_trace_interval == 0:
            emit_progress(
                "repair_block_placed",
                block_id=block_id,
                placed_blocks=placed_blocks,
                orig_start=orig_start,
                start_try=start_try,
                duration=duration,
                retry_count=retry_count,
            )

    repaired.sort(key=lambda r: r['Time'])
    log(f"[repair] shifted_blocks={shifted_blocks}")
    emit_progress(
        "repair_complete",
        retry_count=retry_count,
        block_count=len(block_items),
    )
    return repaired


def build_qubit_use_times(pipeline: List[Row]) -> Dict[int, List[int]]:
    """MOVE is considered to use only 'one qubit' and is recorded only once.
       CNOT records both SIdx and TIdx."""
    uses = defaultdict(list)
    for r in pipeline:
        t = r['Time']
        if r['CNOT'] is True:
            uses[r['SIdx']].append(t)
            uses[r['TIdx']].append(t)
        elif r['SPos'] != r['SNextPos']:
            uses[r['SIdx']].append(t)
        elif r['TPos'] != r['TNextPos']:
            uses[r['TIdx']].append(t)
    # Optimized: Sort all at once
    for q in uses:
        uses[q].sort()
    return uses


def last_use_before(uses: Dict[int, List[int]], q: int, t0: int) -> int:
    # Optimized: Use binary search since uses[q] is sorted
    use_times = uses.get(q, [])
    if not use_times:
        return -10**9

    # Binary search for rightmost element < t0
    idx = bisect.bisect_left(use_times, t0)
    if idx == 0:
        return -10**9
    return use_times[idx - 1]


def clone_channel_state(state: Dict[Edge, int]) -> Dict[Edge, int]:
    return dict(state)


def apply_deltas(state: Dict[Edge, int], deltas: List[Tuple[Edge, int]]) -> None:
    for e, dv in deltas:
        state[e] = state.get(e, 0) + dv


def violates_bounds(state: Dict[Edge, int], deltas: List[Tuple[Edge, int]],
                    min_val: int, max_val: int) -> bool:
    # Optimized: Avoid creating temp dict, check on-the-fly
    for e, dv in deltas:
        new_val = state.get(e, 0) + dv
        if new_val < min_val or new_val > max_val:
            return True
    return False


def build_schedule_by_block_finish(pipeline: List[Row]) -> List[List[Row]]:
    if not pipeline:
        return []
    finish_by_block = {}
    for r in pipeline:
        b = r['BlockID']
        t = r['Time']
        finish_by_block[b] = max(finish_by_block.get(b, t), t)
    finish_times = sorted(set(finish_by_block.values()))
    global_tmin = min(r['Time'] for r in pipeline)
    schedule = []
    ts = global_tmin
    for t in finish_times:
        p = [r for r in pipeline if ts <= r['Time'] <= t]
        p.sort(key=lambda r: r['Time'])
        schedule.append(p)
        ts = t + 1
    return schedule


def _window_qubits(window: List[Row]) -> Set[int]:
    """Return the set of qubits actively used (CNOT operands or MOVE qubit)."""
    qs: Set[int] = set()
    for r in window:
        if r['CNOT']:
            qs.add(r['SIdx'])
            qs.add(r['TIdx'])
        elif r['SPos'] != r['SNextPos']:
            qs.add(r['SIdx'])
        elif r['TPos'] != r['TNextPos']:
            qs.add(r['TIdx'])
    return qs


def _window_edge_usage(window: List[Row]) -> Dict[Tuple[int, Edge], int]:
    """Count MOVE ops per (time, directed_edge) in a window.

    Each MOVE counts +1 on its forward edge and +1 on the reverse edge,
    matching the bidirectional capacity model used by ``can_place_at_time``.
    """
    usage: Dict[Tuple[int, Edge], int] = defaultdict(int)
    for r in window:
        if r['SPos'] != r['SNextPos']:
            e = (r['SPos'], r['SNextPos'])
            usage[(r['Time'], e)] += 1
            usage[(r['Time'], (e[1], e[0]))] += 1
        elif r['TPos'] != r['TNextPos']:
            e = (r['TPos'], r['TNextPos'])
            usage[(r['Time'], e)] += 1
            usage[(r['Time'], (e[1], e[0]))] += 1
    return usage


def _windows_can_merge(w1: List[Row], w2: List[Row],
                       max_comm_value: int) -> bool:
    """Two adjacent windows can merge if no qubit conflict and no channel overflow."""
    q1 = _window_qubits(w1)
    q2 = _window_qubits(w2)
    if q1 & q2:
        return False

    # Channel safety: combined MOVE usage per (time, directed_edge)
    # must stay within cap (= max_comm_value // 2), matching can_place_at_time.
    cap = max_comm_value // 2
    usage = _window_edge_usage(w1)
    for key, cnt in _window_edge_usage(w2).items():
        usage[key] += cnt
    for cnt in usage.values():
        if cnt > cap:
            return False
    return True


def merge_parallel_windows(windows: List[List[Row]],
                           max_comm_value: int,
                           n_passes: int = 5,
                           log: Optional[Callable[[str], None]] = None) -> List[List[Row]]:
    """Merge independent windows to increase parallelism.

    Phase 1 (``n_passes`` rounds): greedy adjacent-pair merge (fast, O(n)
    per pass).  Handles the common case where many consecutive windows are
    independent.

    Phase 2 (single pass): absorb non-adjacent windows.  For each window,
    scan forward and merge any later window whose qubits and channels are
    compatible with the accumulated group.  This catches windows that are
    separated by an incompatible neighbour but are independent of each other.
    """
    # --- Phase 1: adjacent merge ---
    for pass_idx in range(n_passes):
        if len(windows) <= 1:
            break
        merged: List[List[Row]] = []
        i = 0
        merged_any = False
        while i < len(windows):
            if i + 1 < len(windows) and _windows_can_merge(
                windows[i], windows[i + 1], max_comm_value
            ):
                combined = windows[i] + windows[i + 1]
                combined.sort(key=lambda r: r['Time'])
                merged.append(combined)
                i += 2
                merged_any = True
            else:
                merged.append(windows[i])
                i += 1
        if not merged_any:
            break
        windows = merged
        if log:
            log(f"[merge-adj pass {pass_idx + 1}] {len(windows)} windows")

    # --- Phase 2: non-adjacent absorb ---
    if len(windows) > 1:
        absorbed: List[bool] = [False] * len(windows)
        out: List[List[Row]] = []
        for i in range(len(windows)):
            if absorbed[i]:
                continue
            group = list(windows[i])
            group_qubits = _window_qubits(group)
            group_edge_usage = _window_edge_usage(group)
            cap = max_comm_value // 2
            for j in range(i + 1, len(windows)):
                if absorbed[j]:
                    continue
                cand = windows[j]
                cand_qubits = _window_qubits(cand)
                if group_qubits & cand_qubits:
                    continue
                # Check channel safety
                cand_edge_usage = _window_edge_usage(cand)
                ok = True
                for key, cnt in cand_edge_usage.items():
                    if group_edge_usage.get(key, 0) + cnt > cap:
                        ok = False
                        break
                if not ok:
                    continue
                # Absorb
                group.extend(cand)
                group_qubits |= cand_qubits
                for key, cnt in cand_edge_usage.items():
                    group_edge_usage[key] = group_edge_usage.get(key, 0) + cnt
                absorbed[j] = True
            group.sort(key=lambda r: r['Time'])
            out.append(group)
        if len(out) < len(windows):
            if log:
                log(f"[merge-absorb] {len(windows)} -> {len(out)} windows")
            windows = out

    return windows


def remove_duplicate_rows(pipeline: List[Row]) -> List[Row]:
    """
    - CNOT: dedup based on (Time, {SIdx,TIdx}) unordered pair
    - MOVE: dedup based on (Time, QIdx, FromPos, ToPos)
            standardize to single-move row: **only S moves**, T is kept as no-op
    """
    out: List[Row] = []
    seen_cnot = set()
    seen_move = set()

    for r in pipeline:
        if r['CNOT'] is True:
            q1, q2 = r['SIdx'], r['TIdx']
            # Optimized: Use min/max instead of sorted tuple
            k = ('CNOT', r['Time'], (min(q1, q2), max(q1, q2)))
            if k in seen_cnot:
                continue
            seen_cnot.add(k)
            out.append(r)
            continue

        # S movement branch
        if r['SPos'] != r['SNextPos']:
            q = r['SIdx']
            f = r['SPos']
            t = r['SNextPos']
            k = ('MOVE', r['Time'], q, f, t)
            if k not in seen_move:
                seen_move.add(k)
                nr = r.copy()
                # standardization: only S moves. T is no-op (stays at same position)
                nr['TIdx'] = q
                nr['TPos'] = f
                nr['TNextPos'] = f   # no-op
                nr['CNOT'] = False
                out.append(nr)

        # T movement branch
        if r['TPos'] != r['TNextPos']:
            q = r['TIdx']
            f = r['TPos']
            t = r['TNextPos']
            k = ('MOVE', r['Time'], q, f, t)
            if k not in seen_move:
                seen_move.add(k)
                nr = r.copy()
                # standardization: copy movement to S, T is no-op
                nr['SIdx'] = q
                nr['SPos'] = f
                nr['SNextPos'] = t
                nr['TIdx'] = q
                nr['TPos'] = f
                nr['TNextPos'] = f   # no-op
                nr['CNOT'] = False
                out.append(nr)

    out.sort(key=lambda x: x['Time'])
    return out

def how_many_channel_used(pipeline, time, channel_t, max_comm_value):
    channel_used = defaultdict(int)
    # Optimized: Direct iteration instead of list comprehension
    for r in pipeline:
        if r['Time'] != time:
            continue
        if r['SPos'] != r['SNextPos']:
            e_fwd = (r['SPos'], r['SNextPos'])
            e_rev = (r['SNextPos'], r['SPos'])
            channel_used[e_fwd] += 1
            channel_used[e_rev] += 1
    return channel_used



def _advance_local_cnots(pipeline: List[Row],
                          uses: Dict[int, List[int]],
                          t_min: int,
                          log: Callable[[str], None]) -> int:
    """Pass 2: advance local CNOTs whose both operand qubits become idle earlier.

    Run AFTER the RELOCATE sweep. For each CNOT(a, b) with SPos == TPos (local),
    find the earliest time at which neither operand is in use and shift the CNOT
    there. Re-CNOTs (SPos != TPos) are excluded since they consume EPR resources
    and require channel-state validation analogous to RELOCATEs.

    Mutates `pipeline` (CNOT row Time fields) and `uses` in place.
    Returns the total number of local CNOTs advanced.
    """
    def is_local_cnot(r: Row) -> bool:
        return r['CNOT'] is True and r['SPos'] == r['TPos']

    def compute_cnot_candidates() -> List[int]:
        return [i for i, r in enumerate(pipeline) if is_local_cnot(r)]

    used_at_time: Dict[int, Set[int]] = defaultdict(set)
    for r in pipeline:
        t = r['Time']
        for q in row_used_qubits(r):
            used_at_time[t].add(q)

    candidates = compute_cnot_candidates()
    sweep_limit = 100
    sweep_count = 0
    total_moves = 0
    improved = True

    log(f"[cnot-init] local-cnot candidates={len(candidates)}")

    while improved and sweep_count < sweep_limit:
        improved = False
        sweep_count += 1
        sweep_moves = 0

        for idx in candidates:
            r = pipeline[idx]
            t0 = r['Time']
            if t0 == t_min:
                continue
            a = r['SIdx']
            b = r['TIdx']

            lu_a = last_use_before(uses, a, t0)
            lu_b = last_use_before(uses, b, t0)
            t_earliest_a = max(t_min, lu_a + 1) if lu_a != -10**9 else t_min
            t_earliest_b = max(t_min, lu_b + 1) if lu_b != -10**9 else t_min
            t_earliest = max(t_earliest_a, t_earliest_b)

            best_t = t0
            for t_try in range(t0 - 1, t_earliest - 1, -1):
                if a in used_at_time[t_try] or b in used_at_time[t_try]:
                    continue
                best_t = t_try

            if best_t == t0:
                continue

            old_time = t0
            r['Time'] = best_t
            pipeline[idx] = r

            for q in (a, b):
                arr = uses.get(q, [])
                try:
                    arr.remove(old_time)
                except ValueError:
                    pass
                arr.append(best_t)
                arr.sort()
                uses[q] = arr

            used_at_time[old_time].discard(a)
            used_at_time[old_time].discard(b)
            used_at_time[best_t].add(a)
            used_at_time[best_t].add(b)

            sweep_moves += 1
            total_moves += 1
            log(f"[cnot-move] idx={idx} block={r.get('BlockID','?')} "
                f"{old_time}->{best_t} q=[{a},{b}]")

        if sweep_moves > 0:
            improved = True
            pipeline.sort(key=lambda r: r['Time'])
            candidates = compute_cnot_candidates()
            log(f"[cnot-sweep {sweep_count}] moves={sweep_moves}")
        else:
            log(f"[cnot-sweep {sweep_count}] no moves")

    log(f"[cnot-done] total_moves={total_moves}")
    return total_moves


def pipeline_optimization(pipeline: List[Row],
                          initial_channel_dict: Dict[Edge, int],
                          min_comm_value: int,
                          max_comm_value: int,
                          require_remote_at_move_time: bool = True,
                          *,
                          advance_local_cnots: bool = True,
                          debug: bool = True,
                          debug_fn: Optional[Callable[[str], None]] = None,
                          progress_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
                          retry_trace_interval: int = 0,
                          block_trace_interval: int = 0) -> Tuple[List[List[Row]], Dict[int, List[Row]]]:
    """
    If require_remote_at_move_time is True, a MOVE may be advanced to t_try
    only if there is at least one RELOCATE (i.e., a MOVE row) already scheduled
    at that exact time t_try. (RELOCATE = any MOVE row as identified by is_move_row.)

    Returns:
        windows: List of windows (List[Row]) grouped by block finish times
        early_executed_dict: Dict[host_block_id, List[Row(original_state)]]
            - Only includes MOVE rows whose final Time < original Time
            - Each Row stored is the ORIGINAL snapshot (including original Time)
            - Host block resolution order:
                (1) CNOT at that final time that uses the same qubit
                (2) Any row at that time that uses the same qubit
                (3) Any row at that time (first)
                (4) If the time slot is empty, the row is skipped
    """
    def log(msg: str) -> None:
        if debug:
            (debug_fn or print)(msg)

    if not pipeline:
        return [], {}

    pipeline = remove_duplicate_rows(pipeline)

    # Keep ORIGINAL snapshots of each row after standardization, before optimization
    # Optimized: Use index-based mapping instead of id()
    orig_snapshots = [r.copy() for r in pipeline]

    t_min = min(r['Time'] for r in pipeline)
    t_max = max(r['Time'] for r in pipeline)

    # Build RELOCATE indices using is_move_row (RELOCATE == MOVE)
    relocate_any_times: Set[int] = set()
    relocate_qubits_at_time: Dict[int, Set[int]] = defaultdict(set)
    for r in pipeline:
        if (r['CNOT'] is False) and is_move_row(r):
            tt = r['Time']
            relocate_any_times.add(tt)
            if r['SPos'] != r['SNextPos']:
                relocate_qubits_at_time[tt].add(r['SIdx'])
            if r['TPos'] != r['TNextPos']:
                relocate_qubits_at_time[tt].add(r['TIdx'])
    # print("RELOCATE_ANY_TIMES:",relocate_any_times)
    uses = build_qubit_use_times(pipeline)

    # channel/conflict table
    channel_t: Dict[int, Dict[Edge, int]] = {t_min: clone_channel_state(initial_channel_dict)}
    moves_at_time: Dict[int, set] = defaultdict(set)
    cnot_uses_at_time: Dict[int, set] = defaultdict(set)
    for r in pipeline:
        if r['CNOT'] is True:
            t = r['Time']
            cnot_uses_at_time[t].add(r['SIdx'])
            cnot_uses_at_time[t].add(r['TIdx'])

    # channel accumulation + same-time MOVE conflict table construction
    # Optimized: Pre-group rows by time to avoid repeated filtering
    rows_by_time_init: Dict[int, List[Row]] = defaultdict(list)
    for r in pipeline:
        if r['CNOT'] is False:
            rows_by_time_init[r['Time']].append(r)

    for t in range(t_min, t_max + 1):
        if t != t_min:
            channel_t[t] = clone_channel_state(channel_t[t - 1])

        rows_t = rows_by_time_init.get(t, [])
        already = set()
        for r in rows_t:
            # Since standardized, only one MOVE exists (S or T)
            if r['SPos'] != r['SNextPos']:
                q = r['SIdx']
                if q in already:
                    continue
                already.add(q)
                moves_at_time[t].add(q)
                e_fwd = (r['SPos'], r['SNextPos'])
                e_rev = (r['SNextPos'], r['SPos'])
                channel_t[t][e_fwd] = channel_t[t].get(e_fwd, 0) + 1
                channel_t[t][e_rev] = channel_t[t].get(e_rev, 0) - 1
            elif r['TPos'] != r['TNextPos']:
                q = r['TIdx']
                if q in already:
                    continue
                already.add(q)
                moves_at_time[t].add(q)
                e_fwd = (r['TPos'], r['TNextPos'])
                e_rev = (r['TNextPos'], r['TPos'])
                channel_t[t][e_fwd] = channel_t[t].get(e_fwd, 0) + 1
                channel_t[t][e_rev] = channel_t[t].get(e_rev, 0) - 1
    # Optimized: Use dict comprehension instead of deepcopy
    max_cap = {t: {} for t in range(t_min, t_max + 1)}
    for t in range(t_min, t_max + 1):
        for e in channel_t[t]:
            val_cap = min(channel_t[t][e], channel_t[t][(e[1], e[0])])
            max_cap[t][e] = val_cap

    # ---- internal helper + debug reason collection ----
    # Optimized: Cache channel usage calculations
    channel_used_cache: Dict[int, Dict[Edge, int]] = {}

    def get_channel_used(time: int) -> Dict[Edge, int]:
        if time not in channel_used_cache:
            channel_used_cache[time] = how_many_channel_used(pipeline, time, channel_t, max_comm_value)
        return channel_used_cache[time]

    def can_place_at_time(r: Row, t_try: int, t0: int, reasons: List[str]) -> bool:
        deltas = row_channel_deltas(r)

        # channel bounds: entire interval [t_try, t0)
        for tt in range(t_try, t0):
            if violates_bounds(channel_t[tt], deltas, min_comm_value, max_comm_value):
                reasons.append(f"bounds@{tt}")
                return False

        # same-time MOVE/CNOT conflict (only when same qubit)
        q = r['SIdx'] if r['SPos'] != r['SNextPos'] else r['TIdx']
        if q in moves_at_time.get(t_try, set()):
            reasons.append(f"move-conflict@{t_try}")
            return False

        # NEW: Require an existing RELOCATE (MOVE) at t_try
        if require_remote_at_move_time and (t_try not in relocate_any_times):
            reasons.append(f"requires-relocate@{t_try}")
            return False

        # keep CNOT same-qubit conflict prohibition
        if t_try < t0:
            used = get_channel_used(t_try)
            # print('time:', t_try, 'used:', dict(used))
            if r['SPos'] != r['SNextPos']:
                e_fwd = (r['SPos'], r['SNextPos'])
                e_rev = (r['SNextPos'], r['SPos'])
            else:
                e_fwd = (r['TPos'], r['TNextPos'])
                e_rev = (r['TNextPos'], r['TPos'])

            max_c_value = max_comm_value // 2
            # After adding this MOVE, each increments by +1
            if (used[e_fwd] + 1 > max_c_value) or (used[e_rev] + 1 > max_c_value):
                reasons.append(f"cap-exceeded@{t_try}")
                return False

        return True

    def compute_candidates() -> List[int]:
        return [i for i, r in enumerate(pipeline) if (r['CNOT'] is False) and is_move_row(r)]

    candidates = compute_candidates()

    improved = True
    sweep_limit = 100
    sweep_count = 0
    total_moves = 0

    log(f"[init] rows={len(pipeline)} time=[{t_min},{t_max}] candidates={len(candidates)}")

    # debug: reason aggregation
    dbg_reasons = defaultdict(int)
    dbg_samples = []

    while improved and sweep_count < sweep_limit:
        improved = False
        sweep_count += 1
        sweep_moves = 0
        log(f"[sweep {sweep_count}] start")

        for idx in candidates:
            r = pipeline[idx]
            t0 = r['Time']
            if t0 == t_min:
                continue

            # which qubit is moving
            moving_qubits = []
            if r['SPos'] != r['SNextPos']:
                moving_qubits.append(r['SIdx'])
            elif r['TPos'] != r['TNextPos']:
                moving_qubits.append(r['TIdx'])
            if not moving_qubits:
                continue
            q = moving_qubits[0]

            # CNOT boundary applies "only when same qubit" -> handled by last_use_before
            lu = last_use_before(uses, q, t0)
            t_earliest = max(t_min, lu + 1) if lu != -10**9 else t_min

            best_t = t0
            deltas = row_channel_deltas(r)

            searched_any = False
            for t_try in range(t0 - 1, t_earliest - 1, -1):
                searched_any = True
                trial_reasons = []
                if can_place_at_time(r, t_try, t0, trial_reasons):
                    best_t = t_try
                else:
                    if trial_reasons:
                        dbg_reasons[trial_reasons[0]] += 1
                        if len(dbg_samples) < 5:
                            dbg_samples.append((q, t0, t_try, trial_reasons[0], deltas))

            if best_t == t0:
                if not searched_any:
                    dbg_reasons["no-window"] += 1
                    if len(dbg_samples) < 5:
                        dbg_samples.append((q, t0, None, "no-window", deltas))
                continue

            # move confirmed: channel update
            for tt in range(t0, t_max + 1):
                apply_deltas(channel_t[tt], [(e, -dv) for e, dv in deltas])
            for tt in range(best_t, t_max + 1):
                apply_deltas(channel_t[tt], deltas)

            if q in moves_at_time.get(t0, set()):
                moves_at_time[t0].remove(q)
            moves_at_time[best_t].add(q)

            old_time = r['Time']
            r['Time'] = best_t
            pipeline[idx] = r

            arr = uses.get(q, [])
            try:
                arr.remove(old_time)
            except ValueError:
                pass
            arr.append(best_t)
            arr.sort()
            uses[q] = arr

            # Optimized: Invalidate affected cache entries
            if old_time in channel_used_cache:
                del channel_used_cache[old_time]
            if best_t in channel_used_cache:
                del channel_used_cache[best_t]

            sweep_moves += 1
            total_moves += 1
            log(f"[move] idx={idx} block={r.get('BlockID','?')} {old_time}->{best_t} q={[q]} "
                f"deltas={[(str(e), dv) for e, dv in deltas]}")

        if sweep_moves > 0:
            improved = True
            pipeline.sort(key=lambda r: r['Time'])
            candidates = compute_candidates()
            log(f"[sweep {sweep_count}] moves={sweep_moves} re-sorted")
        else:
            log(f"[sweep {sweep_count}] no moves")

    log(f"[done] total_moves={total_moves}")

    if total_moves == 0:
        ordered = sorted(dbg_reasons.items(), key=lambda x: -x[1])
        log("[no-move summary] " + ", ".join(f"{k}:{v}" for k, v in ordered[:6]))
        for (qq, t0, t_try, why, deltas) in dbg_samples:
            log(f"[example] q={qq} at {t0} -> try {t_try}: {why}, deltas={[(str(e),dv) for e,dv in deltas]}")

    # Pass 2: advance local CNOTs whose operand qubits became free after the
    # RELOCATE sweep above. Re-CNOTs are skipped (channel state would need to
    # be revalidated like RELOCATEs).
    if advance_local_cnots:
        cnot_total = _advance_local_cnots(pipeline, uses, t_min, log)
        if cnot_total > 0:
            pipeline.sort(key=lambda r: r['Time'])

    from collections import defaultdict as _dd
    early_executed_dict: Dict[int, List[Row]] = _dd(list)

    rows_by_time: Dict[int, List[Row]] = _dd(list)
    for r in pipeline:
        rows_by_time[r['Time']].append(r)

    for idx, r in enumerate(pipeline):
        if r['CNOT'] is True:
            continue
        if not is_move_row(r):
            continue

        # Optimized: Use index instead of id()
        if idx >= len(orig_snapshots):
            continue
        orig = orig_snapshots[idx]

        if orig['Time'] <= r['Time']:
            continue

        if r['SPos'] != r['SNextPos']:
            q = r['SIdx']
        else:
            q = r['TIdx']

        final_t = r['Time']
        host_block = None

        for rr in rows_by_time.get(final_t, []):
            if rr['CNOT'] and (rr['SIdx'] == q or rr['TIdx'] == q):
                host_block = rr['BlockID']
                break

        if host_block is None:
            for rr in rows_by_time.get(final_t, []):
                if rr['SIdx'] == q or rr['TIdx'] == q:
                    host_block = rr['BlockID']
                    break

        if host_block is None and rows_by_time.get(final_t, []):
            host_block = rows_by_time[final_t][0]['BlockID']

        if host_block is not None:
            early_executed_dict[host_block].append(orig)


    windows = build_schedule_by_block_finish(pipeline)
    log(f"[pre-merge] windows={len(windows)}")
    windows = merge_parallel_windows(windows, max_comm_value, n_passes=5, log=log)
    log(f"[post-merge] windows={len(windows)}")

    # Post-condition: flatten windows back to a pipeline and audit all constraints.
    flat: List[Row] = [r for w in windows for r in w]
    flat.sort(key=lambda r: r['Time'])
    violations = _verify_placed_pipeline(
        flat, initial_channel_dict, min_comm_value, max_comm_value,
    )
    if violations:
        preview = "; ".join(violations[:5])
        extra = f" (+{len(violations)-5} more)" if len(violations) > 5 else ""
        raise AssertionError(
            f"pipeline_optimization post-condition failed: "
            f"{len(violations)} violation(s): {preview}{extra}"
        )

    return windows, dict(early_executed_dict)


def _verify_placed_pipeline(
    placed: List[Row],
    initial_channel_dict: Dict[Edge, int],
    min_comm_value: int,
    max_comm_value: int,
    *,
    link_epr_capacity: Optional[int] = None,
    chip_epr_capacity: Optional[Dict[Pos, int]] = None,
) -> List[str]:
    """Post-condition audit: returns list of violations on the placed pipeline.

    Checks:
      (a) Per-cycle qubit collision
      (b) Per-qubit dependency order (no out-of-order reuse)
      (c) Channel state bounds [min_comm_value, max_comm_value]
      (d) Per-direction edge capacity max_comm_value // 2
      (e) Per-link bidirectional EPR cap (if link_epr_capacity provided)
      (f) Per-chip EPR capacity (if chip_epr_capacity provided)
    """
    violations: List[str] = []
    if not placed:
        return violations

    rows_by_time: Dict[int, List[Row]] = defaultdict(list)
    for r in placed:
        rows_by_time[r['Time']].append(r)

    # (a) Per-cycle qubit collision
    for t in sorted(rows_by_time):
        seen: Set[int] = set()
        for r in rows_by_time[t]:
            for q in row_used_qubits(r):
                if q in seen:
                    violations.append(f"(a)qubit-collision@{t}:q{q}")
                seen.add(q)

    # (b) Per-qubit dependency order
    last_seen: Dict[int, int] = {}
    for r in sorted(placed, key=lambda x: x['Time']):
        t = r['Time']
        for q in row_used_qubits(r):
            if q in last_seen and last_seen[q] > t:
                violations.append(f"(b)qubit-order:q{q} {last_seen[q]}>{t}")
            last_seen[q] = max(last_seen.get(q, t), t)

    # (c) Channel state bounds + (d) per-direction edge capacity
    channel = dict(initial_channel_dict)
    cap_dir = max_comm_value // 2
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
                violations.append(f"(d)edge-cap@{t}:{e}={cnt}>{cap_dir}")
        for e in touched:
            val = channel.get(e, 0)
            if val < min_comm_value:
                violations.append(f"(c)cap-under@{t}:{e}={val}")
            if val > max_comm_value:
                violations.append(f"(c)cap-over@{t}:{e}={val}")

    # (e) Per-link bidirectional EPR cap
    if link_epr_capacity is not None:
        for t in sorted(rows_by_time):
            link_count: Dict[FrozenSet[Pos], int] = defaultdict(int)
            for r in rows_by_time[t]:
                if r['CNOT'] or not is_move_row(r):
                    continue
                if r['SPos'] != r['SNextPos']:
                    link = frozenset({r['SPos'], r['SNextPos']})
                elif r['TPos'] != r['TNextPos']:
                    link = frozenset({r['TPos'], r['TNextPos']})
                else:
                    continue
                link_count[link] += 1
            for link, cnt in link_count.items():
                if cnt > link_epr_capacity:
                    violations.append(f"(e)link-cap@{t}:{sorted(link)}={cnt}>{link_epr_capacity}")

    # (f) Per-chip EPR capacity (inbound MOVEs)
    if chip_epr_capacity is not None:
        for t in sorted(rows_by_time):
            inbound: Dict[Pos, int] = defaultdict(int)
            for r in rows_by_time[t]:
                if r['CNOT']:
                    continue
                if r['SPos'] != r['SNextPos']:
                    dest = r['SNextPos']
                elif r['TPos'] != r['TNextPos']:
                    dest = r['TNextPos']
                else:
                    continue
                inbound[dest] += 1
            for dest, cnt in inbound.items():
                cap = chip_epr_capacity.get(dest)
                if cap is not None and cnt > cap:
                    violations.append(f"(f)chip-cap@{t}:{dest}={cnt}>{cap}")

    return violations


def qucomm_parallel_schedule(
    pipeline: List[Row],
    initial_channel_dict: Dict[Edge, int],
    min_comm_value: int,
    max_comm_value: int,
    *,
    chip_epr_capacity: Optional[Dict[Pos, int]] = None,
    link_epr_capacity: Optional[int] = None,
    log: Optional[Callable[[str], None]] = None,
    debug: bool = False,
    verify_postcondition: bool = True,
) -> List[Row]:
    """Standalone QuComm baseline parallelizer (NOT wired into pipeline_optimization).

    Take a serially-scheduled QuComm pipeline (block-after-block) and produce a
    parallel version where independent blocks run concurrently. Two blocks may
    overlap in time when:

      * No qubit collision: a qubit used by block B at time t cannot also be
        used by another block at the same t.
      * Per-qubit data dependency: a qubit's first use in block B must be later
        than the qubit's last use in any earlier-placed block.
      * Channel state bounds: cumulative channel state at every time stays
        within [min_comm_value, max_comm_value].
      * Per-direction edge capacity: at any single time t, the count of MOVE
        rows traversing an edge in one direction is at most max_comm_value//2.
      * (Optional) Per-chip EPR capacity: if ``chip_epr_capacity`` is supplied,
        the number of inbound MOVEs ending on a chip at time t cannot exceed
        the chip's capacity.
      * (Optional) Per-link EPR capacity (HARD CAP): if ``link_epr_capacity``
        is supplied, at any single time t the combined count of RELOCATEs
        using the same link (BOTH directions: (a,b) and (b,a) treated as one
        link) cannot exceed this cap. Set to e.g. 5 for an S40C5 architecture.

    Greedy: blocks are placed in original-start-time order; each block is
    shifted to the earliest start time that satisfies all constraints.

    The function does not mutate the input pipeline; it returns a new list of
    rows (each a copy) sorted by Time.
    """
    if log is None:
        log = print if debug else (lambda _msg: None)
    if not pipeline:
        return []

    # ---- Step 1: group by BlockID, normalize to relative times ----
    blocks_by_id: Dict[Any, List[Row]] = defaultdict(list)
    for r in pipeline:
        blocks_by_id[r['BlockID']].append(r)

    block_items: List[Tuple[int, Any, int, List[Row]]] = []
    for bid, rows in blocks_by_id.items():
        rows_sorted = sorted(rows, key=lambda r: r['Time'])
        orig_start = rows_sorted[0]['Time']
        rel_rows = []
        for r in rows_sorted:
            nr = r.copy()
            nr['Time'] = r['Time'] - orig_start
            rel_rows.append(nr)
        duration = rel_rows[-1]['Time']
        block_items.append((orig_start, bid, duration, rel_rows))

    block_items.sort(key=lambda x: (x[0], x[1]))
    log(f"[qpar-init] blocks={len(block_items)}")

    # ---- Step 2: tracking state ----
    t_min = min(r['Time'] for r in pipeline)
    channel_t: Dict[int, Dict[Edge, int]] = {t_min: dict(initial_channel_dict)}
    current_t_max = t_min

    qubit_uses_at: Dict[int, Set[int]] = defaultdict(set)
    edge_uses_at: Dict[int, Dict[Edge, int]] = defaultdict(dict)
    qubit_last_busy: Dict[int, int] = {}
    chip_inbound_at: Dict[int, Dict[Pos, int]] = defaultdict(dict)
    # Link key: frozenset of two endpoint chips (bidirectional)
    link_use_at: Dict[int, Dict[FrozenSet[Pos], int]] = defaultdict(dict)

    def ensure_time(t: int) -> None:
        nonlocal current_t_max
        while current_t_max < t:
            channel_t[current_t_max + 1] = dict(channel_t[current_t_max])
            current_t_max += 1

    def can_place(rel_rows: List[Row], start_try: int) -> bool:
        # Per-block tentative accumulators (reset per try)
        local_qubit_uses: Dict[int, Set[int]] = defaultdict(set)
        local_edge_uses: Dict[int, Dict[Edge, int]] = defaultdict(dict)
        local_chip_inbound: Dict[int, Dict[Pos, int]] = defaultdict(dict)
        local_link_uses: Dict[int, Dict[FrozenSet[Pos], int]] = defaultdict(dict)
        local_running: Dict[Edge, int] = defaultdict(int)
        cap = max_comm_value // 2

        rows_in_order = sorted(rel_rows, key=lambda r: r['Time'])
        for r in rows_in_order:
            tt = start_try + r['Time']

            # 1) Qubit busy
            for q in row_used_qubits(r):
                if q in qubit_uses_at.get(tt, set()) or q in local_qubit_uses[tt]:
                    return False
                local_qubit_uses[tt].add(q)

            # 2) Per-direction edge capacity
            for e, dv in row_channel_deltas(r):
                if dv > 0:
                    used_now = edge_uses_at.get(tt, {}).get(e, 0) + local_edge_uses[tt].get(e, 0)
                    if used_now + 1 > cap:
                        return False
                    local_edge_uses[tt][e] = local_edge_uses[tt].get(e, 0) + 1

            # 2b) Per-link bidirectional EPR cap (HARD CAP)
            if link_epr_capacity is not None and not r['CNOT'] and is_move_row(r):
                if r['SPos'] != r['SNextPos']:
                    link_key = frozenset({r['SPos'], r['SNextPos']})
                elif r['TPos'] != r['TNextPos']:
                    link_key = frozenset({r['TPos'], r['TNextPos']})
                else:
                    link_key = None
                if link_key is not None:
                    used_link = link_use_at.get(tt, {}).get(link_key, 0) + local_link_uses[tt].get(link_key, 0)
                    if used_link + 1 > link_epr_capacity:
                        return False
                    local_link_uses[tt][link_key] = local_link_uses[tt].get(link_key, 0) + 1

            # 3) Per-chip EPR capacity (only if requested)
            if chip_epr_capacity is not None and not r['CNOT']:
                # Inbound MOVE: qubit lands at SNextPos (or TNextPos)
                if r['SPos'] != r['SNextPos']:
                    dest = r['SNextPos']
                elif r['TPos'] != r['TNextPos']:
                    dest = r['TNextPos']
                else:
                    dest = None
                if dest is not None and dest in chip_epr_capacity:
                    placed_in = chip_inbound_at.get(tt, {}).get(dest, 0) + local_chip_inbound[tt].get(dest, 0)
                    if placed_in + 1 > chip_epr_capacity[dest]:
                        return False
                    local_chip_inbound[tt][dest] = local_chip_inbound[tt].get(dest, 0) + 1

            # 4) Channel state bounds (cumulative)
            for e, dv in row_channel_deltas(r):
                local_running[e] += dv
                if local_running[e] == 0:
                    del local_running[e]
            ensure_time(tt)
            base = channel_t[tt]
            for e, run_dv in local_running.items():
                new_val = base.get(e, 0) + run_dv
                if new_val < min_comm_value or new_val > max_comm_value:
                    return False

        return True

    # ---- Step 3: greedy placement ----
    placed_pipeline: List[Row] = []
    placed_count = 0

    for orig_start, bid, duration, rel_rows in block_items:
        # Lower-bound start_try from per-qubit dependency
        lb = t_min
        for r in rel_rows:
            for q in row_used_qubits(r):
                if q in qubit_last_busy:
                    lb = max(lb, qubit_last_busy[q] + 1 - r['Time'])

        start_try = lb
        max_iter = 10**6
        iter_count = 0
        while not can_place(rel_rows, start_try):
            start_try += 1
            iter_count += 1
            if iter_count > max_iter:
                raise RuntimeError(
                    f"qucomm_parallel_schedule: cannot place block {bid} "
                    f"within {max_iter} attempts (current start_try={start_try})"
                )

        # Place block: update trackers and emit rows
        ensure_time(start_try + duration)
        for r in rel_rows:
            tt = start_try + r['Time']
            placed_row = r.copy()
            placed_row['Time'] = tt
            placed_pipeline.append(placed_row)

            for q in row_used_qubits(r):
                qubit_uses_at[tt].add(q)
                qubit_last_busy[q] = max(qubit_last_busy.get(q, tt), tt)

            for e, dv in row_channel_deltas(r):
                if dv > 0:
                    edge_uses_at[tt][e] = edge_uses_at[tt].get(e, 0) + 1
                # Cumulative channel state update for all times >= tt
                for t_apply in range(tt, current_t_max + 1):
                    channel_t[t_apply][e] = channel_t[t_apply].get(e, 0) + dv

            if chip_epr_capacity is not None and not r['CNOT']:
                if r['SPos'] != r['SNextPos']:
                    dest = r['SNextPos']
                elif r['TPos'] != r['TNextPos']:
                    dest = r['TNextPos']
                else:
                    dest = None
                if dest is not None:
                    chip_inbound_at[tt][dest] = chip_inbound_at[tt].get(dest, 0) + 1

            if link_epr_capacity is not None and not r['CNOT'] and is_move_row(r):
                if r['SPos'] != r['SNextPos']:
                    lk = frozenset({r['SPos'], r['SNextPos']})
                elif r['TPos'] != r['TNextPos']:
                    lk = frozenset({r['TPos'], r['TNextPos']})
                else:
                    lk = None
                if lk is not None:
                    link_use_at[tt][lk] = link_use_at[tt].get(lk, 0) + 1

        placed_count += 1
        if start_try != orig_start:
            log(f"[qpar] block {bid}: {orig_start} -> {start_try} (dur={duration})")

    placed_pipeline.sort(key=lambda r: r['Time'])
    final_t_max = max((r['Time'] for r in placed_pipeline), default=t_min)
    orig_t_max = max(r['Time'] for r in pipeline)
    log(f"[qpar-done] placed={placed_count} t_max: {orig_t_max} -> {final_t_max}")

    if verify_postcondition:
        violations = _verify_placed_pipeline(
            placed_pipeline, initial_channel_dict, min_comm_value, max_comm_value,
            link_epr_capacity=link_epr_capacity, chip_epr_capacity=chip_epr_capacity,
        )
        if violations:
            preview = "; ".join(violations[:5])
            extra = f" (+{len(violations)-5} more)" if len(violations) > 5 else ""
            raise AssertionError(
                f"qucomm_parallel_schedule post-condition failed: "
                f"{len(violations)} violation(s): {preview}{extra}"
            )

    return placed_pipeline


def qucomm_layer_parallel_schedule(
    pipeline: List[Row],
    *,
    link_epr_capacity: int,
    log: Optional[Callable[[str], None]] = None,
    debug: bool = False,
) -> List[Row]:
    """Strict QuComm block-layer parallelizer (NOT wired into pipeline_optimization).

    Groups blocks into LAYERS that satisfy strict QuComm semantics:

      * Within a layer, all blocks have **disjoint qubit sets** (NO shared
        qubits, even at non-overlapping times within the layer).
      * Within a layer, the total RELOCATE count on each bidirectional link
        (sum across both directions and across all times in the layer) is at
        most ``link_epr_capacity``.
      * Layer N+1 starts only AFTER every operation of layer N has finished
        (next-layer start = previous-layer max time + 1).

    Greedy: blocks are processed in original-start-time order. Each block is
    appended to the current layer if compatible; otherwise the current layer
    is finalized and a new layer begins.

    Within a layer, every block starts at the layer's start time (relative
    block-internal timing is preserved). Layers are concatenated in time.

    The function does not mutate the input pipeline; it returns a new sorted
    list of rows.
    """
    if log is None:
        log = print if debug else (lambda _msg: None)
    if not pipeline:
        return []

    # ---- Step 1: group by BlockID, normalize, and pre-compute per-block summaries ----
    blocks_by_id: Dict[Any, List[Row]] = defaultdict(list)
    for r in pipeline:
        blocks_by_id[r['BlockID']].append(r)

    block_items: List[Dict[str, Any]] = []
    for bid, rows in blocks_by_id.items():
        rows_sorted = sorted(rows, key=lambda r: r['Time'])
        orig_start = rows_sorted[0]['Time']
        rel_rows: List[Row] = []
        qubits: Set[int] = set()
        link_count: Dict[FrozenSet[Pos], int] = defaultdict(int)
        for r in rows_sorted:
            nr = r.copy()
            nr['Time'] = r['Time'] - orig_start
            rel_rows.append(nr)
            for q in row_used_qubits(nr):
                qubits.add(q)
            if not nr['CNOT'] and is_move_row(nr):
                if nr['SPos'] != nr['SNextPos']:
                    lk = frozenset({nr['SPos'], nr['SNextPos']})
                else:
                    lk = frozenset({nr['TPos'], nr['TNextPos']})
                link_count[lk] += 1
        duration = rel_rows[-1]['Time']
        block_items.append({
            'id': bid,
            'orig_start': orig_start,
            'duration': duration,
            'rel_rows': rel_rows,
            'qubits': qubits,
            'link_count': dict(link_count),
        })

    block_items.sort(key=lambda b: (b['orig_start'], b['id']))
    log(f"[qlay-init] blocks={len(block_items)}, link_cap={link_epr_capacity}")

    # ---- Step 2: greedy layer formation ----
    t_min = min(r['Time'] for r in pipeline)
    placed_pipeline: List[Row] = []

    layer_start = t_min
    layer_qubits: Set[int] = set()
    layer_link_count: Dict[FrozenSet[Pos], int] = defaultdict(int)
    layer_max_end = t_min - 1
    layer_blocks: List[Any] = []
    layer_idx = 0

    def finalize_layer() -> None:
        nonlocal layer_start, layer_qubits, layer_link_count
        nonlocal layer_max_end, layer_blocks, layer_idx
        if not layer_blocks:
            return
        log(f"[qlay] layer {layer_idx}: t=[{layer_start}, {layer_max_end}] "
            f"blocks={len(layer_blocks)}")
        layer_idx += 1
        layer_start = layer_max_end + 1
        layer_qubits = set()
        layer_link_count = defaultdict(int)
        layer_max_end = layer_start - 1
        layer_blocks = []

    for b in block_items:
        compatible = True
        # Constraint 1: qubit disjointness within layer
        if b['qubits'] & layer_qubits:
            compatible = False
        # Constraint 2: link EPR cap (sum over directions and times in layer)
        if compatible:
            for lk, cnt in b['link_count'].items():
                if layer_link_count[lk] + cnt > link_epr_capacity:
                    compatible = False
                    break

        if not compatible:
            finalize_layer()

        # Place block in (now possibly new) current layer
        for r in b['rel_rows']:
            placed_row = r.copy()
            placed_row['Time'] = layer_start + r['Time']
            placed_pipeline.append(placed_row)
            if placed_row['Time'] > layer_max_end:
                layer_max_end = placed_row['Time']

        layer_qubits |= b['qubits']
        for lk, cnt in b['link_count'].items():
            layer_link_count[lk] += cnt
        layer_blocks.append(b['id'])

    finalize_layer()

    placed_pipeline.sort(key=lambda r: r['Time'])
    final_t_max = max((r['Time'] for r in placed_pipeline), default=t_min)
    orig_t_max = max(r['Time'] for r in pipeline)
    log(f"[qlay-done] layers={layer_idx} placed={len(block_items)} "
        f"t_max: {orig_t_max} -> {final_t_max}")
    return placed_pipeline
