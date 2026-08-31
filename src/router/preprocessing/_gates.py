from collections import deque
from primitive import Gate
class GatePreprocessMixin:
    def initialize_atom_dag(self):
        self.gates = deque()
        self.gates_to_complete = []
        last_gate_of_atom = {}  # atom_id -> most recent Gate object
        for layer_idx, layer in enumerate(self.layers):
            for atom0, atom1 in layer:
                pos0, pos1 = self.position_table[atom0], self.position_table[atom1]
                atom0_dependency = last_gate_of_atom.get(atom0); atom1_dependency = last_gate_of_atom.get(atom1); dependencies = []
                if atom0_dependency is not None: dependencies.append(atom0_dependency)
                if atom1_dependency is not None and atom1_dependency != atom0_dependency:
                    dependencies.append(atom1_dependency)
                gate = Gate(layer_idx, atom0, atom1, pos0, pos1, dependency=dependencies, is_done=False)
                self.gates.append(gate)
                self.gates_to_complete.append(gate)
                last_gate_of_atom[atom0] = gate
                last_gate_of_atom[atom1] = gate
    def preprocess_gates(self):
        visited = set()
        result = deque()
        def dfs(gate):
            if gate in visited: return
            visited.add(gate)
            for parent in gate.dependency:
                if parent not in visited: dfs(parent)
            result.append(gate)  # Add the gate after visiting its parent
        for gate in self.gates:
            if gate not in visited: dfs(gate)
        self.gate_order = list(result) # topological order in reverse, gates are popped from end of array