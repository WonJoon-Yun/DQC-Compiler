"""Gate and circuit parsing utilities."""
from typing import Any, List, Mapping, Optional, Tuple
from .types import Qubit
def _bit_index(bit: Any) -> Optional[int]:
    for attr in ("index", "_index"):
        if hasattr(bit, attr):
            value = getattr(bit, attr)
            if value is not None:
                return int(value)
    return None
def _iter_circuit_gates(circuit: Any) -> List[Any]:
    if hasattr(circuit, "topological_order") and callable(circuit.topological_order):
        return list(circuit.topological_order())
    return list(circuit)
def _gate_qubits(gate: Any) -> Tuple[Qubit, ...]:
    """Extract qubit ids from multiple gate representations."""
    if hasattr(gate, "atom0") and hasattr(gate, "atom1"):
        return (int(gate.atom0), int(gate.atom1))
    if hasattr(gate, "qargs") and gate.qargs is not None:
        qbs = []
        for qubit in gate.qargs:
            idx = _bit_index(qubit)
            if idx is not None:
                qbs.append(int(idx))
        if qbs:
            return tuple(qbs)
    if hasattr(gate, "qubits") and gate.qubits is not None:
        qbs = []
        for qubit in gate.qubits:
            idx = _bit_index(qubit)
            if idx is not None:
                qbs.append(int(idx))
        if qbs:
            return tuple(qbs)
    if isinstance(gate, Mapping):
        if "atom0" in gate and "atom1" in gate:
            return (int(gate["atom0"]), int(gate["atom1"]))
        if "qubits" in gate and isinstance(gate["qubits"], (list, tuple)):
            qbs = []
            for q in gate["qubits"]:
                if isinstance(q, int):
                    qbs.append(int(q))
                    continue
                idx = _bit_index(q)
                if idx is not None:
                    qbs.append(int(idx))
            if qbs:
                return tuple(qbs)
    if isinstance(gate, (list, tuple)):
        if len(gate) >= 2 and isinstance(gate[0], int) and isinstance(gate[1], int):
            return (int(gate[0]), int(gate[1]))
        if len(gate) >= 2 and _bit_index(gate[0]) is not None and _bit_index(gate[1]) is not None:
            return (int(_bit_index(gate[0])), int(_bit_index(gate[1])))
        if len(gate) >= 2 and isinstance(gate[1], (list, tuple)):
            qbs = gate[1]
            if len(qbs) == 0:
                return ()
            if len(qbs) == 1:
                first = qbs[0]
                idx = first if isinstance(first, int) else _bit_index(first)
                if idx is None:
                    raise TypeError(f"Unsupported gate format for qubit extraction: {gate!r}")
                return (int(idx),)
            first = qbs[0]; second = qbs[1]; idx0 = first if isinstance(first, int) else _bit_index(first); idx1 = second if isinstance(second, int) else _bit_index(second)
            if idx0 is not None and idx1 is not None:
                return (int(idx0), int(idx1))
    raise TypeError(f"Unsupported gate format for qubit extraction: {gate!r}")