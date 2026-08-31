"""Top-level buffer design entry points."""
from typing import Any, Dict, Mapping, Optional, Tuple
from .fusion_cost import communication_fusion, count_gates_involving, count_remote_gates_per_node, estimate_total_comm_all_blocks, has_idle_data_qubit_slot
from .topology_utils import _all_qubits, _extract_node_capacity, _restore_capacity_type, _restore_partition_type, _to_capacity_dict, _to_channel_dict, _to_partition_dict, _topology_nodes
from .types import _LARGE_CAPACITY, Node, Qubit

def communication_buffer_design(circuit: Any, partition: Any, dqc_topology: Any, dist_matrix: Any, epr_capacity: Mapping[Node, int], channel_dict: Optional[Mapping[Tuple[Node, Node], int]]=None, node_data_capacity: Optional[Mapping[Node, int]]=None) -> Tuple[Any, Any, Dict[Tuple[Node, Node], int]]:
    _ = dist_matrix
    (partition_map, part_kind) = _to_partition_dict(partition)
    capacity_map = _to_capacity_dict(epr_capacity)
    channel_map = _to_channel_dict(channel_dict)
    nodes = _topology_nodes(dqc_topology)
    if not nodes:
        nodes = sorted(set(partition_map.values()), key=str)
    for n in nodes:
        capacity_map.setdefault(n, 0)
    all_qubits = _all_qubits(circuit, partition_map)
    if node_data_capacity is None:
        effective_node_data_capacity = _extract_node_capacity(dqc_topology, nodes, partition_map)
    else:
        effective_node_data_capacity = {node: int(cap) for (node, cap) in node_data_capacity.items()}
    generous_capacity = dict.fromkeys(nodes, _LARGE_CAPACITY)
    ideal_blocks = communication_fusion(circuit, partition_map, generous_capacity)
    node_remote_gate_count = count_remote_gates_per_node(ideal_blocks, partition_map)
    nodes_sorted = sorted(nodes, key=lambda n: node_remote_gate_count.get(n, 0), reverse=True)
    for node in nodes_sorted:
        while True:
            data_qubits_on_node = [q for q in all_qubits if partition_map.get(q) == node]
            if not data_qubits_on_node:
                break
            best_q: Optional[Qubit] = None
            best_target: Optional[Node] = None
            best_relocation_cost = float('inf')
            for q in data_qubits_on_node:
                local_gate_count = count_gates_involving(q, node, ideal_blocks, partition_map)
                for target_node in nodes:
                    if target_node == node:
                        continue
                    if not has_idle_data_qubit_slot(target_node, partition_map, effective_node_data_capacity):
                        continue
                    remote_gate_count = count_gates_involving(q, target_node, ideal_blocks, partition_map)
                    relocation_cost = local_gate_count - remote_gate_count
                    if relocation_cost < best_relocation_cost:
                        best_relocation_cost = relocation_cost
                        best_q = q
                        best_target = target_node
            if best_q is None or best_target is None:
                break
            old_total_comm = estimate_total_comm_all_blocks(ideal_blocks, partition_map, capacity_map)
            capacity_map[node] += 1
            new_total_comm = estimate_total_comm_all_blocks(ideal_blocks, partition_map, capacity_map)
            capacity_map[node] -= 1
            reduction = old_total_comm - new_total_comm
            if reduction > 0 and best_relocation_cost <= reduction:
                partition_map[best_q] = best_target
                capacity_map[node] += 1
                ideal_blocks = communication_fusion(circuit, partition_map, capacity_map)
            else:
                break
    partition_out = _restore_partition_type(partition, partition_map, part_kind)
    capacity_out = _restore_capacity_type(epr_capacity, capacity_map)
    return (partition_out, capacity_out, channel_map)