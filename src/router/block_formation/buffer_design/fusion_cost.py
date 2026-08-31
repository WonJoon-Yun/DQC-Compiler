from collections import defaultdict
from math import inf
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, Optional
from .circuit_utils import _gate_qubits, _iter_circuit_gates
from .types import CollectiveCommBlock, Node, Qubit

def _block_from_gate(gate: Any, partition: Mapping[Qubit, Node]) -> CollectiveCommBlock:
    qbs = set(_gate_qubits(gate))
    nodes = {partition[q] for q in qbs if q in partition}
    return CollectiveCommBlock(gates=[gate], qubits=qbs, nodes=nodes)

def _merge_block_and_gate(block: CollectiveCommBlock, gate: Any, partition: Mapping[Qubit, Node]) -> CollectiveCommBlock:
    qbs = set(block.qubits)
    qbs.update(_gate_qubits(gate))
    return CollectiveCommBlock(gates=[*block.gates, gate], qubits=qbs, nodes={partition[q] for q in qbs if q in partition})

def _is_inter_node_gate(gate: Any, partition: Mapping[Qubit, Node]) -> bool:
    qbs = _gate_qubits(gate)
    if len(qbs) < 2:
        return False
    nodes = {partition[q] for q in qbs if q in partition}
    return len(nodes) > 1

def communication_fusion(circuit: Any, partition: Mapping[Qubit, Node], epr_capacity: Mapping[Node, int]) -> List[CollectiveCommBlock]:
    """Greedy block fusion used only for L3 estimation."""
    _ = epr_capacity
    gates = _iter_circuit_gates(circuit)
    blocks: List[CollectiveCommBlock] = []
    current_block: Optional[CollectiveCommBlock] = None
    for gate in gates:
        gate_qubits = set(_gate_qubits(gate))
        if not _is_inter_node_gate(gate, partition):
            if current_block is not None and gate_qubits.issubset(current_block.qubits):
                current_block.gates.append(gate)
            elif current_block is not None:
                blocks.append(current_block)
                current_block = None
            continue
        if current_block is None:
            current_block = _block_from_gate(gate, partition)
            continue
        candidate_merged = _merge_block_and_gate(current_block, gate, partition)
        cost_separate = estimate_cost(current_block, epr_capacity, partition) + estimate_cost(_block_from_gate(gate, partition), epr_capacity, partition)
        cost_merged = estimate_cost(candidate_merged, epr_capacity, partition)
        if cost_merged < cost_separate:
            current_block = candidate_merged
        else:
            blocks.append(current_block)
            current_block = _block_from_gate(gate, partition)
    if current_block is not None:
        blocks.append(current_block)
    return blocks

def estimate_cost(block: CollectiveCommBlock, epr_capacity: Mapping[Node, int], partition: Mapping[Qubit, Node]) -> int:
    """Equation-style communication cost for one collective block."""
    involved_nodes = {partition[q] for q in block.qubits if q in partition}
    if not involved_nodes:
        return 0
    best_cost = inf
    for candidate_node in involved_nodes:
        external = sum((1 for q in block.qubits if partition.get(q) != candidate_node))
        cap = int(epr_capacity.get(candidate_node, 0))
        overflow = max(external - cap, 0)
        swap_cost = 2 * overflow
        direct_cost = min(cap, external)
        cost = swap_cost + direct_cost
        if cost < best_cost:
            best_cost = cost
    return int(best_cost)

def estimate_total_comm_all_blocks(blocks: Iterable[CollectiveCommBlock], partition: Mapping[Qubit, Node], epr_capacity: Mapping[Node, int]) -> int:
    return sum((estimate_cost(block, epr_capacity, partition) for block in blocks))

def count_remote_gates_per_node(blocks: Iterable[CollectiveCommBlock], partition: Mapping[Qubit, Node]) -> Dict[Node, int]:
    counts: DefaultDict[Node, int] = defaultdict(int)
    for block in blocks:
        for gate in block.gates:
            qbs = _gate_qubits(gate)
            if len(qbs) < 2:
                continue
            nodes_involved = {partition[q] for q in qbs if q in partition}
            if len(nodes_involved) > 1:
                for n in nodes_involved:
                    counts[n] += 1
    return dict(counts)

def count_gates_involving(qubit: Qubit, node: Node, blocks: Iterable[CollectiveCommBlock], partition: Mapping[Qubit, Node]) -> int:
    count = 0
    for block in blocks:
        for gate in block.gates:
            qbs = _gate_qubits(gate)
            if len(qbs) < 2 or qubit not in qbs:
                continue
            partner_nodes = {partition[q] for q in qbs if q != qubit and q in partition}
            if node in partner_nodes:
                count += 1
    return count

def has_idle_data_qubit_slot(node: Node, partition: Mapping[Qubit, Node], node_data_capacity: Mapping[Node, int]) -> bool:
    current_count = sum((1 for q in partition if partition[q] == node))
    return current_count < int(node_data_capacity.get(node, current_count))