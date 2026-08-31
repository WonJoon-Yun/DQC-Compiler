"""Pipeline construction from schedules."""
from typing import Any, Dict, List, Set, Tuple
Row = Dict[str, Any]

def _entry_hash_key(entry: Row) -> tuple:
    return (entry['BlockID'], entry['Time'], entry['SIdx'], entry['SPos'], entry['SNextPos'], entry['TIdx'], entry['TPos'], entry['TNextPos'], entry['CNOT'])

def append_schedule_segment_to_pipeline(pipeline: List[Row], schedule: List[Row], *, start_T: int, duplicated: Set[tuple]) -> None:
    """Append one schedule segment into a flat pipeline in-place."""
    for sched_entry in schedule:
        entry = sched_entry.copy()
        entry['Time'] += start_T
        hash_key = _entry_hash_key(entry)
        if hash_key in duplicated:
            if entry['CNOT']:
                duplicated.add(hash_key)
                pipeline.append(entry)
        else:
            pipeline.append(entry)
            duplicated.add(hash_key)

def build_pipeline_from_schedules(schedules: List[List[Row]]) -> Tuple[List[Row], List[int]]:
    """Build a flat pipeline from schedule segments."""
    pipeline: List[Row] = []
    start_T = 0
    duplicated: Set[tuple] = set()
    segment_start_times: List[int] = []
    for schedule in schedules:
        segment_start_times.append(start_T)
        append_schedule_segment_to_pipeline(pipeline, schedule, start_T=start_T, duplicated=duplicated)
        start_T += max((s['Time'] for s in schedule), default=0) + 1
    return (pipeline, segment_start_times)