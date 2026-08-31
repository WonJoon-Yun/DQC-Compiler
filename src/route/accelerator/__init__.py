"""Accelerator module: selects the fastest available backend."""
_BACKEND = "pure"
try:
    from ._cython_accel import (_capacity_neighbors as _cy_capacity_neighbors)
    from ._cython_accel import ( _deterministic_topology_shortest_path, _involved_qubits, anchor_convergence_cost, init_interact_info, lookahead_cost)
    from ._cython_accel import (find_path_with_capacity as _cy_find_path)
    from ._cython_accel import (single_source_shortest_paths_with_capacity as _cy_sssp)
    _BACKEND = "cython"
except ImportError:
    pass
if _BACKEND == "pure":
    try:
        from ._numba import ( _involved_qubits, anchor_convergence_cost, init_interact_info, lookahead_cost)
        _BACKEND = "numba"
    except (ImportError, Exception):
        pass
if _BACKEND == "pure":
    from ._pure import ( _deterministic_topology_shortest_path, _involved_qubits, anchor_convergence_cost, init_interact_info, lookahead_cost)