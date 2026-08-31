"""Shared type aliases and dataclasses for buffer_design."""
from dataclasses import dataclass
from typing import Any, Hashable, List, Set
Qubit = int
Node = Hashable
_LARGE_CAPACITY = 10**9
@dataclass
class CollectiveCommBlock:
    """Minimal block model required for L3 cost estimation."""
    gates: List[Any]
    qubits: Set[Qubit]
    nodes: Set[Node]
