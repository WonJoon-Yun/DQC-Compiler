from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from .types import Node, Qubit
def _to_partition_dict(partition: Any) -> Tuple[Dict[Qubit, Node], str]:
    if isinstance(partition, Mapping):
        return {int(k): v for k, v in partition.items()}, "mapping"
    if isinstance(partition, Sequence):
        return {int(i): partition[i] for i in range(len(partition))}, "sequence"
    raise TypeError("partition must be a mapping or sequence")
def _restore_partition_type(partition_template: Any, partition_map: Dict[Qubit, Node], part_kind: str) -> Any:
    if part_kind == "mapping":
        if isinstance(partition_template, defaultdict):
            out = defaultdict(partition_template.default_factory)
            out.update(partition_map)
            return out
        return dict(partition_map)
    n = len(partition_template)
    out = [partition_map[i] for i in range(n)]
    if isinstance(partition_template, tuple):
        return tuple(out)
    return out
def _to_capacity_dict(epr_capacity: Any) -> Dict[Node, int]:
    if not isinstance(epr_capacity, Mapping):
        raise TypeError("epr_capacity must be a mapping")
    return {k: int(v) for k, v in epr_capacity.items()}
def _restore_capacity_type(cap_template: Any, cap_map: Dict[Node, int]) -> Any:
    if isinstance(cap_template, defaultdict):
        out = defaultdict(cap_template.default_factory)
        out.update(cap_map)
        return out
    return dict(cap_map)
def _to_channel_dict(channel_dict: Optional[Mapping[Tuple[Node, Node], int]]) -> Dict[Tuple[Node, Node], int]:
    if channel_dict is None:
        return {}
    if not isinstance(channel_dict, Mapping):
        raise TypeError("channel_dict must be a mapping")
    return {tuple(k): int(v) for k, v in channel_dict.items()}
def _topology_nodes(dqc_topology: Any) -> List[Node]:
    if hasattr(dqc_topology, "nodes"):
        try:
            return list(dqc_topology.nodes())
        except TypeError:
            return list(dqc_topology.nodes)
    if isinstance(dqc_topology, Mapping):
        return list(dqc_topology.keys())
    return []
def _extract_node_capacity(dqc_topology: Any, nodes: Iterable[Node], partition: Mapping[Qubit, Node],) -> Dict[Node, int]:
    """Return max data-qubit capacity per node, with safe fallback."""
    capacities: Dict[Node, int] = {}
    def _pull_attr(data: Any, keys: Tuple[str, ...]) -> Optional[int]:
        if isinstance(data, Mapping):
            for k in keys:
                if k in data and data[k] is not None:
                    return int(data[k])
            return None
        for k in keys:
            if hasattr(data, k):
                v = getattr(data, k)
                if v is not None:
                    return int(v)
        return None
    keys = ("max_data_qubits", "num_data_qubits", "data_qubits", "max_qubits")
    if hasattr(dqc_topology, "nodes"):
        try:
            for n, data in dqc_topology.nodes(data=True):
                val = _pull_attr(data, keys)
                if val is not None:
                    capacities[n] = val
        except TypeError:
            pass
    counts = defaultdict(int)
    for q in partition:
        counts[partition[q]] += 1
    inferred_cap = max(counts.values()) if counts else 0
    for node in nodes:
        capacities.setdefault(node, inferred_cap)
    return capacities
def _all_qubits(circuit: Any, partition_map: Mapping[Qubit, Node]) -> List[Qubit]:
    from .circuit_utils import _gate_qubits, _iter_circuit_gates
    qubits = set(partition_map.keys())
    for gate in _iter_circuit_gates(circuit):
        for q in _gate_qubits(gate):
            qubits.add(int(q))
    return sorted(qubits)