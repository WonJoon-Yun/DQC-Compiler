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
    if row['CNOT'] is True:
        return (row['SIdx'], row['TIdx'])
    if row['SPos'] != row['SNextPos']:
        return (row['SIdx'],)
    if row['TPos'] != row['TNextPos']:
        return (row['TIdx'],)
    return ()
def build_qubit_use_times(pipeline: List[Row]) -> Dict[int, List[int]]:
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
    for q in uses:
        uses[q].sort()
    return uses
def last_use_before(uses: Dict[int, List[int]], q: int, t0: int) -> int:
    use_times = uses.get(q, [])
    if not use_times:
        return -10**9
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
    finish_times = sorted(set(finish_by_block.values())); global_tmin = min(r['Time'] for r in pipeline); schedule = []; ts = global_tmin
    for t in finish_times:
        p = [r for r in pipeline if ts <= r['Time'] <= t]
        p.sort(key=lambda r: r['Time'])
        schedule.append(p)
        ts = t + 1
    return schedule
def _window_qubits(window: List[Row]) -> Set[int]:
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
    raise RuntimeError("pruned: _window_edge_usage")
def _windows_can_merge(w1: List[Row], w2: List[Row],
                       max_comm_value: int) -> bool:
    raise RuntimeError("pruned: _windows_can_merge")
def merge_parallel_windows(windows: List[List[Row]],
                           max_comm_value: int,
                           n_passes: int = 5,
                           log: Optional[Callable[[str], None]] = None) -> List[List[Row]]:
    """Merge independent windows to increase parallelism."""
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
    if len(windows) > 1:
        absorbed: List[bool] = [False] * len(windows)
        out: List[List[Row]] = []
        for i in range(len(windows)):
            if absorbed[i]:
                continue
            group = list(windows[i]); group_qubits = _window_qubits(group); group_edge_usage = _window_edge_usage(group); cap = max_comm_value // 2
            for j in range(i + 1, len(windows)):
                if absorbed[j]:
                    continue
                cand = windows[j]
                cand_qubits = _window_qubits(cand)
                if group_qubits & cand_qubits:
                    continue
                cand_edge_usage = _window_edge_usage(cand)
                ok = True
                for key, cnt in cand_edge_usage.items():
                    if group_edge_usage.get(key, 0) + cnt > cap:
                        ok = False
                        break
                if not ok:
                    continue
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
    """- CNOT: dedup based on (Time, {SIdx,TIdx}) unordered pair"""
    out: List[Row] = []
    seen_cnot = set()
    seen_move = set()
    for r in pipeline:
        if r['CNOT'] is True:
            q1, q2 = r['SIdx'], r['TIdx']
            k = ('CNOT', r['Time'], (min(q1, q2), max(q1, q2)))
            if k in seen_cnot:
                continue
            seen_cnot.add(k)
            out.append(r)
            continue
        if r['SPos'] != r['SNextPos']:
            q = r['SIdx']; f = r['SPos']; t = r['SNextPos']; k = ('MOVE', r['Time'], q, f, t)
            if k not in seen_move:
                seen_move.add(k)
                nr = r.copy()
                nr['TIdx'] = q
                nr['TPos'] = f
                nr['TNextPos'] = f   # no-op
                nr['CNOT'] = False
                out.append(nr)
        if r['TPos'] != r['TNextPos']:
            q = r['TIdx']; f = r['TPos']; t = r['TNextPos']; k = ('MOVE', r['Time'], q, f, t)
            if k not in seen_move:
                seen_move.add(k)
                nr = r.copy()
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
    def is_local_cnot(r: Row) -> bool:
        return r['CNOT'] is True and r['SPos'] == r['TPos']
    def compute_cnot_candidates() -> List[int]:
        return [i for i, r in enumerate(pipeline) if is_local_cnot(r)]
    used_at_time: Dict[int, Set[int]] = defaultdict(set)
    for r in pipeline:
        t = r['Time']
        for q in row_used_qubits(r):
            used_at_time[t].add(q)
    candidates = compute_cnot_candidates(); sweep_limit = 100; sweep_count = 0; total_moves = 0; improved = True
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
            t_earliest_b = max(t_min, lu_b + 1) if lu_b != -10**9 else t_min; t_earliest = max(t_earliest_a, t_earliest_b); best_t = t0
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
    def log(msg: str) -> None:
        if debug:
            (debug_fn or print)(msg)
    if not pipeline:
        return [], {}
    pipeline = remove_duplicate_rows(pipeline); orig_snapshots = [r.copy() for r in pipeline]; t_min = min(r['Time'] for r in pipeline); t_max = max(r['Time'] for r in pipeline)
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
    uses = build_qubit_use_times(pipeline)
    channel_t: Dict[int, Dict[Edge, int]] = {t_min: clone_channel_state(initial_channel_dict)}
    moves_at_time: Dict[int, set] = defaultdict(set)
    cnot_uses_at_time: Dict[int, set] = defaultdict(set)
    for r in pipeline:
        if r['CNOT'] is True:
            t = r['Time']
            cnot_uses_at_time[t].add(r['SIdx'])
            cnot_uses_at_time[t].add(r['TIdx'])
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
    max_cap = {t: {} for t in range(t_min, t_max + 1)}
    for t in range(t_min, t_max + 1):
        for e in channel_t[t]:
            val_cap = min(channel_t[t][e], channel_t[t][(e[1], e[0])])
            max_cap[t][e] = val_cap
    channel_used_cache: Dict[int, Dict[Edge, int]] = {}
    def get_channel_used(time: int) -> Dict[Edge, int]:
        if time not in channel_used_cache:
            channel_used_cache[time] = how_many_channel_used(pipeline, time, channel_t, max_comm_value)
        return channel_used_cache[time]
    def can_place_at_time(r: Row, t_try: int, t0: int, reasons: List[str]) -> bool:
        deltas = row_channel_deltas(r)
        for tt in range(t_try, t0):
            if violates_bounds(channel_t[tt], deltas, min_comm_value, max_comm_value):
                reasons.append(f"bounds@{tt}")
                return False
        q = r['SIdx'] if r['SPos'] != r['SNextPos'] else r['TIdx']
        if q in moves_at_time.get(t_try, set()):
            reasons.append(f"move-conflict@{t_try}")
            return False
        if require_remote_at_move_time and (t_try not in relocate_any_times):
            reasons.append(f"requires-relocate@{t_try}")
            return False
        if t_try < t0:
            used = get_channel_used(t_try)
            if r['SPos'] != r['SNextPos']:
                e_fwd = (r['SPos'], r['SNextPos'])
                e_rev = (r['SNextPos'], r['SPos'])
            else:
                e_fwd = (r['TPos'], r['TNextPos'])
                e_rev = (r['TNextPos'], r['TPos'])
            max_c_value = max_comm_value // 2
            if (used[e_fwd] + 1 > max_c_value) or (used[e_rev] + 1 > max_c_value):
                reasons.append(f"cap-exceeded@{t_try}")
                return False
        return True
    def compute_candidates() -> List[int]:
        return [i for i, r in enumerate(pipeline) if (r['CNOT'] is False) and is_move_row(r)]
    candidates = compute_candidates(); improved = True; sweep_limit = 100; sweep_count = 0; total_moves = 0
    log(f"[init] rows={len(pipeline)} time=[{t_min},{t_max}] candidates={len(candidates)}")
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
            moving_qubits = []
            if r['SPos'] != r['SNextPos']:
                moving_qubits.append(r['SIdx'])
            elif r['TPos'] != r['TNextPos']:
                moving_qubits.append(r['TIdx'])
            if not moving_qubits:
                continue
            q = moving_qubits[0]; lu = last_use_before(uses, q, t0); t_earliest = max(t_min, lu + 1) if lu != -10**9 else t_min; best_t = t0; deltas = row_channel_deltas(r); searched_any = False
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
    flat: List[Row] = [r for w in windows for r in w]
    flat.sort(key=lambda r: r['Time'])
    violations = _verify_placed_pipeline(flat, initial_channel_dict, min_comm_value, max_comm_value)
    if violations:
        preview = "; ".join(violations[:5])
        extra = f" (+{len(violations)-5} more)" if len(violations) > 5 else ""
        raise AssertionError(
            f"pipeline_optimization post-condition failed: "
            f"{len(violations)} violation(s): {preview}{extra}")
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
    violations: List[str] = []
    if not placed:
        return violations
    rows_by_time: Dict[int, List[Row]] = defaultdict(list)
    for r in placed:
        rows_by_time[r['Time']].append(r)
    for t in sorted(rows_by_time):
        seen: Set[int] = set()
        for r in rows_by_time[t]:
            for q in row_used_qubits(r):
                if q in seen:
                    violations.append(f"(a)qubit-collision@{t}:q{q}")
                seen.add(q)
    last_seen: Dict[int, int] = {}
    for r in sorted(placed, key=lambda x: x['Time']):
        t = r['Time']
        for q in row_used_qubits(r):
            if q in last_seen and last_seen[q] > t:
                violations.append(f"(b)qubit-order:q{q} {last_seen[q]}>{t}")
            last_seen[q] = max(last_seen.get(q, t), t)
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
    if log is None:
        log = print if debug else (lambda _msg: None)
    if not pipeline:
        return []
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
    t_min = min(r['Time'] for r in pipeline)
    channel_t: Dict[int, Dict[Edge, int]] = {t_min: dict(initial_channel_dict)}
    current_t_max = t_min
    qubit_uses_at: Dict[int, Set[int]] = defaultdict(set)
    edge_uses_at: Dict[int, Dict[Edge, int]] = defaultdict(dict)
    qubit_last_busy: Dict[int, int] = {}
    chip_inbound_at: Dict[int, Dict[Pos, int]] = defaultdict(dict)
    link_use_at: Dict[int, Dict[FrozenSet[Pos], int]] = defaultdict(dict)
    def ensure_time(t: int) -> None:
        nonlocal current_t_max
        while current_t_max < t:
            channel_t[current_t_max + 1] = dict(channel_t[current_t_max])
            current_t_max += 1
    def can_place(rel_rows: List[Row], start_try: int) -> bool:
        local_qubit_uses: Dict[int, Set[int]] = defaultdict(set)
        local_edge_uses: Dict[int, Dict[Edge, int]] = defaultdict(dict)
        local_chip_inbound: Dict[int, Dict[Pos, int]] = defaultdict(dict)
        local_link_uses: Dict[int, Dict[FrozenSet[Pos], int]] = defaultdict(dict)
        local_running: Dict[Edge, int] = defaultdict(int)
        cap = max_comm_value // 2
        rows_in_order = sorted(rel_rows, key=lambda r: r['Time'])
        for r in rows_in_order:
            tt = start_try + r['Time']
            for q in row_used_qubits(r):
                if q in qubit_uses_at.get(tt, set()) or q in local_qubit_uses[tt]:
                    return False
                local_qubit_uses[tt].add(q)
            for e, dv in row_channel_deltas(r):
                if dv > 0:
                    used_now = edge_uses_at.get(tt, {}).get(e, 0) + local_edge_uses[tt].get(e, 0)
                    if used_now + 1 > cap:
                        return False
                    local_edge_uses[tt][e] = local_edge_uses[tt].get(e, 0) + 1
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
            if chip_epr_capacity is not None and not r['CNOT']:
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
    placed_pipeline: List[Row] = []
    placed_count = 0
    for orig_start, bid, duration, rel_rows in block_items:
        lb = t_min
        for r in rel_rows:
            for q in row_used_qubits(r):
                if q in qubit_last_busy:
                    lb = max(lb, qubit_last_busy[q] + 1 - r['Time'])
        start_try = lb; max_iter = 10**6; iter_count = 0
        while not can_place(rel_rows, start_try):
            start_try += 1
            iter_count += 1
            if iter_count > max_iter:
                raise RuntimeError(
                    f"qucomm_parallel_schedule: cannot place block {bid} "
                    f"within {max_iter} attempts (current start_try={start_try})")
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
            link_epr_capacity=link_epr_capacity, chip_epr_capacity=chip_epr_capacity)
        if violations:
            preview = "; ".join(violations[:5])
            extra = f" (+{len(violations)-5} more)" if len(violations) > 5 else ""
            raise AssertionError(
                f"qucomm_parallel_schedule post-condition failed: "
                f"{len(violations)} violation(s): {preview}{extra}")
    return placed_pipeline