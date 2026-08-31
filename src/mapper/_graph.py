import networkx as nx
import numpy as np
try:
    from numba import njit
except ImportError:
    def njit(func):
        return func
@njit
def count_edges_numba(program, num_gates, num_qubits):
    mat = np.zeros((num_qubits, num_qubits), dtype=np.uint32)
    for idx in range(num_gates):
        q1, q2 = program[idx]
        i = min(q1, q2)
        j = max(q1, q2)
        mat[i, j] += 1
    return mat
def build_graph_numba(program, num_qubits):
    prog_arr = np.array(program, dtype=np.int32); num_gates = prog_arr.shape[0]; mat = count_edges_numba(prog_arr, num_gates, num_qubits); G = nx.Graph()
    rows, cols = np.nonzero(mat)
    weights = mat[rows, cols]
    G.add_edges_from(((i, j, {'weight': int(w)}) for i, j, w in zip(rows, cols, weights)))
    return G