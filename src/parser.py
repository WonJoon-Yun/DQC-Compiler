from qiskit import QuantumCircuit
from qiskit.converters import circuit_to_dag
class ProgramParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.list_2q_gates = []  # Stores two-qubit gates as (control, target)
        self.num_1q_gates = 0
        self.num_2q_gates = 0
        self.num_qubits = 0
        self.parse()
    def parse(self):
        qc = QuantumCircuit.from_qasm_file(self.filepath)
        self.num_qubits = qc.num_qubits
        self.has_multiple_qregs = len(qc.qregs) > 1
        dag = circuit_to_dag(qc)
        for node in dag.topological_op_nodes():
            qargs = [qc.find_bit(qubit).index for qubit in node.qargs]
            if node.op.name == "cx" and len(qargs) == 2:
                self.list_2q_gates.append((qargs[0], qargs[1]))
                self.num_2q_gates += 1
            elif node.op.name == 'rzz' and len(qargs) == 2:
                self.list_2q_gates.append((qargs[0], qargs[1]))
                self.list_2q_gates.append((qargs[0], qargs[1]))
                self.num_2q_gates += 2
            elif node.op.name == 'cp' and len(qargs) == 2:
                self.list_2q_gates.append((qargs[0], qargs[1]))
                self.num_2q_gates += 1
            elif node.op.name == 'swap' and len(qargs) == 2:
                self.list_2q_gates.append((qargs[0], qargs[1]))
                self.list_2q_gates.append((qargs[1], qargs[0]))
                self.list_2q_gates.append((qargs[0], qargs[1]))
                self.num_2q_gates += 3
            elif len(qargs) == 1: self.num_1q_gates += 1
    def __call__(self):
        return self.list_2q_gates
