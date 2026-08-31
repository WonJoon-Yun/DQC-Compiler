from typing import Any, Dict, List

def analyze_ees_opportunity_from_tracer(tracer_rows: List[List], tracer_columns: List[str]) -> Dict[str, Any]:
    """Analyze EES opportunity from tracer data."""
    if not tracer_rows:
        return _empty_result()
    col_idx = {name: i for (i, name) in enumerate(tracer_columns)}
    i_atom0 = col_idx['atom0']
    i_atom1 = col_idx['atom1']
    i_optype = col_idx['optype']
    i_start = col_idx['start_time']
    i_end = col_idx['end_time']
    i_count = col_idx['count']
    relocates = []
    all_ops = []
    for row in tracer_rows:
        a0 = row[i_atom0]
        a1 = row[i_atom1]
        st = row[i_start]
        et = row[i_end]
        op = row[i_optype]
        cnt = row[i_count]
        all_ops.append((cnt, a0, a1, st, et, op))
        if op == 'RELOCATE':
            relocates.append((cnt, a0, a1, st, et))
    if not relocates:
        return _empty_result()
    from collections import defaultdict
    qubit_end_times: Dict[int, List] = defaultdict(list)
    for (cnt, a0, a1, st, et, op) in all_ops:
        qubit_end_times[a0].append((et, cnt))
        if a1 != a0:
            qubit_end_times[a1].append((et, cnt))
    for q in qubit_end_times:
        qubit_end_times[q].sort()
    total_relocates = len(relocates)
    early_ready_count = 0
    total_idle_gap_sum = 0.0
    idle_intervals = []
    details = []
    for (cnt, a0, a1, reloc_start, reloc_end) in relocates:
        q = a0
        last_prior_end = None
        for (et, c) in qubit_end_times[q]:
            if c == cnt:
                continue
            if et <= reloc_start + 1e-12:
                if last_prior_end is None or et > last_prior_end:
                    last_prior_end = et
        if last_prior_end is None:
            details.append({'qubit': q, 'count': cnt, 'label': 'FIRST_USE', 'reloc_start': reloc_start, 'gap': 0.0})
            continue
        gap = reloc_start - last_prior_end
        if gap > 1e-09:
            early_ready_count += 1
            total_idle_gap_sum += gap
            idle_intervals.append((last_prior_end, reloc_start))
            details.append({'qubit': q, 'count': cnt, 'label': 'EARLY', 'reloc_start': reloc_start, 'last_prior_end': last_prior_end, 'gap': gap})
        else:
            details.append({'qubit': q, 'count': cnt, 'label': 'NO_GAP', 'reloc_start': reloc_start, 'gap': 0.0})
    unique_idle_time = _union_interval_length(idle_intervals)
    total_exec_time = max((row[i_end] for row in tracer_rows)) - min((row[i_start] for row in tracer_rows))
    return {'total_relocates': total_relocates, 'early_ready_count': early_ready_count, 'early_ready_pct': early_ready_count / total_relocates * 100 if total_relocates > 0 else 0.0, 'total_idle_gap_sum': round(total_idle_gap_sum, 9), 'unique_idle_time': round(unique_idle_time, 9), 'total_execution_time': round(total_exec_time, 9), 'idle_pct': unique_idle_time / total_exec_time * 100 if total_exec_time > 0 else 0.0, 'avg_idle_per_early_relocate': round(total_idle_gap_sum / early_ready_count, 9) if early_ready_count > 0 else 0.0, 'details': details}

def _union_interval_length(intervals):
    if not intervals:
        return 0.0
    sorted_iv = sorted(intervals)
    (merged_start, merged_end) = sorted_iv[0]
    total = 0.0
    for (s, e) in sorted_iv[1:]:
        if s <= merged_end:
            merged_end = max(merged_end, e)
        else:
            total += merged_end - merged_start
            (merged_start, merged_end) = (s, e)
    total += merged_end - merged_start
    return total

def _empty_result() -> Dict[str, Any]:
    return {'total_relocates': 0, 'early_ready_count': 0, 'early_ready_pct': 0.0, 'total_idle_gap_sum': 0.0, 'unique_idle_time': 0.0, 'total_execution_time': 0.0, 'idle_pct': 0.0, 'avg_idle_per_early_relocate': 0.0, 'details': []}