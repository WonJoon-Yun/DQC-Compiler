from collections import defaultdict
import numpy as np
class BaselineMapper:
    def __init__(self, args, hardware, program):
        self.args = args
        self.hardware = hardware
        self.program = program
        self.qubit_mapping = None
        self.mapped_cmap = None
        self.layers = None
        self.cost   = None
        self.args.mapping_manhattan_distance = defaultdict(int)
        self.manhattan_distance = {}
        self.logical_weights = defaultdict(int)
        self.physical_weights = defaultdict(int)
        self.chip_pos = defaultdict(tuple)
        for c in range(self.args.numchipletsx * self.args.numchipletsy):
            x, y = divmod(c, self.args.numchipletsy)  # same as c // y, c % y
            self.chip_pos[c] = (x, y)
        for c1 in range(self.args.numchipletsx * self.args.numchipletsy):
            for c2 in range(self.args.numchipletsx * self.args.numchipletsy):
                x1, y1 = self.chip_pos[c1]
                x2, y2 = self.chip_pos[c2]
                self.physical_weights[(c1, c2)] = abs(x1 - x2) + abs(y1 - y2)
        self.positions = [self.chip_pos[c] for c in range(self.args.numchipletsx * self.args.numchipletsy)]
    def get_cost(self, physical_program, perm=None):
        cost = 0
        self.cost = 0
        self.args.mapping_manhattan_distance = {}
        for _, edge in enumerate(physical_program):
            pos1, pos2 = self.hardware.get_chiplet_pos(edge)
            if perm is not None:
                pos1idx = pos1[0]*self.args.numchipletsy + pos1[1]; pos2idx = pos2[0]*self.args.numchipletsy + pos2[1]; pos1 = self.positions[perm[pos1idx]]; pos2 = self.positions[perm[pos2idx]]
            c = int(np.abs(pos1 - pos2).sum())
            key = str(c)
            self.args.mapping_manhattan_distance[key] = (
                self.args.mapping_manhattan_distance.get(key, 0) + 1)
            cost += c
        self.cost = int(cost)
        return self.cost
    def compile(self):
        raise NotImplementedError("Compile not implemented for baseline mapper")
    def program_to_layers(self, program, max_layer_size=1000000):
        len_gates = len(program)
        if len_gates == 0:
            raise ValueError("[FATAL] Program length is 0")
        last_gate_on_qubit = {}
        dependencies = [set() for _ in range(len_gates)]
        for gate_idx, (q0, q1) in enumerate(program):
            if q0 in last_gate_on_qubit:
                dependencies[gate_idx].add(last_gate_on_qubit[q0])
            if q1 in last_gate_on_qubit:
                dependencies[gate_idx].add(last_gate_on_qubit[q1])
            last_gate_on_qubit[q0] = gate_idx
            last_gate_on_qubit[q1] = gate_idx
        gate_to_layer = [-1] * len_gates
        ready_gates = set()
        for gate_idx in range(len_gates):
            if len(dependencies[gate_idx]) == 0:
                ready_gates.add(gate_idx)
        remaining_deps = [len(deps) for deps in dependencies]; layers = []; current_layer_idx = 0
        while ready_gates:
            layer = []; qubits_in_layer = set(); gates_to_remove = []
            for gate_idx in sorted(ready_gates):  # Sort for deterministic behavior
                q0, q1 = program[gate_idx]
                if q0 not in qubits_in_layer and q1 not in qubits_in_layer:
                    layer.append([q0, q1])
                    qubits_in_layer.add(q0)
                    qubits_in_layer.add(q1)
                    gate_to_layer[gate_idx] = current_layer_idx
                    gates_to_remove.append(gate_idx)
            for gate_idx in gates_to_remove:
                ready_gates.remove(gate_idx)
            for gate_idx in gates_to_remove:
                for dependent_idx in range(len_gates):
                    if gate_idx in dependencies[dependent_idx]:
                        remaining_deps[dependent_idx] -= 1
                        if remaining_deps[dependent_idx] == 0 and gate_to_layer[dependent_idx] == -1:
                            ready_gates.add(dependent_idx)
            if layer:
                layers.append(layer)
                current_layer_idx += 1
            else:
                if ready_gates:
                    gate_idx = ready_gates.pop()
                    q0, q1 = program[gate_idx]
                    layers.append([[q0, q1]])
                    gate_to_layer[gate_idx] = current_layer_idx
                    current_layer_idx += 1
                    for dependent_idx in range(len_gates):
                        if gate_idx in dependencies[dependent_idx]:
                            remaining_deps[dependent_idx] -= 1
                            if remaining_deps[dependent_idx] == 0 and gate_to_layer[dependent_idx] == -1:
                                ready_gates.add(dependent_idx)
        layer_idx = 0
        for layer in layers:
            layer_idx += 1
        return layers