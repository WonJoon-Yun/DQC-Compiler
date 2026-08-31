"""Benchmark setup container."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from .types import Gate, RoutingState

@dataclass
class BenchmarkSetup:
    blocks: List[List[Gate]]
    aggs: List[Any]
    block_ids: List[int]
    start_state: RoutingState
    connectivity: Any
    interact_info: Optional[Dict]
    K: int
