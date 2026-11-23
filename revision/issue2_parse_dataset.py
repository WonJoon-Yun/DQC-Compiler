"""Recompile released QASMs at the parser stage and validate their CX traces.

Run with the pinned iris-ae Python. Each output is a compressed Qiskit QPY
circuit so that very small rotation angles survive serialization.
"""
import argparse
import csv
import gzip
from pathlib import Path
import sys

from qiskit import QuantumCircuit, qpy, transpile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from parser import ProgramParser


def cx_by_wire(pairs, width):
    traces = [[] for _ in range(width)]
    for control, target in pairs:
        traces[control].append((control, target))
        traces[target].append((control, target))
    return traces


def basis_counts(circuit):
    pairs = []
    one_qubit = 0
    for inst in circuit.data:
        if len(inst.qubits) == 1:
            one_qubit += 1
        elif inst.operation.name == "cx":
            pairs.append(tuple(circuit.find_bit(q).index for q in inst.qubits))
        elif inst.operation.name != "barrier":
            raise ValueError(f"Non-basis operation in compiled circuit: {inst.operation.name}")
    return pairs, one_qubit


def same_serialized_instructions(original, restored):
    if (original.qregs != restored.qregs or original.cregs != restored.cregs or
            original.global_phase != restored.global_phase or len(original.data) != len(restored.data)):
        return False
    # QPY must preserve the actual instruction sequence, even on independent
    # wires. A circuit-level DAG isomorphism test permits independent reordering.
    for before, after in zip(original.data, restored.data):
        if (before.operation != after.operation or before.operation.params != after.operation.params or
                before.qubits != after.qubits or before.clbits != after.clbits):
            return False
    return True


def basis_translation(source):
    return transpile(source, basis_gates=["u", "cx"], optimization_level=0,
                     routing_method="none", seed_transpiler=17)


def exact_zero_cp(inst):
    return inst.operation.name == "cp" and inst.operation.params[0] == 0


def compile_one(path, inputs, output):
    relative = path.relative_to(inputs)
    source = QuantumCircuit.from_qasm_file(str(path))
    source_counts = source.count_ops()
    # Published baseline 896e8da uses these four weights on the complete released input set.
    previous_weights = {"cx": 1, "rzz": 2, "cp": 1, "swap": 3}
    old_cx = sum(previous_weights[inst.operation.name] for inst in source.data
                 if len(inst.qubits) == 2 and inst.operation.name != "barrier")
    old_one = sum(len(inst.qubits) == 1 for inst in source.data)
    reference = basis_translation(source)
    expected, expected_one = basis_counts(reference)
    reference_traces = cx_by_wire(expected, source.num_qubits)
    del reference
    zero_cp = sum(exact_zero_cp(inst) for inst in source.data)
    cx_without_zero_cp = len(expected)
    if zero_cp:
        filtered = source.copy_empty_like()
        for inst in source.data:
            if not exact_zero_cp(inst):
                filtered.append(inst.operation, inst.qubits, inst.clbits)
        cx_without_zero_cp = basis_translation(filtered).count_ops().get("cx", 0)
        if cx_without_zero_cp != len(expected) - 2 * zero_cp:
            raise ValueError(f"{relative}: unexpected CX count after removing exact CP(0)")
    parsed = ProgramParser(str(path))
    native = parsed.to_native_circuit()
    stored = output / relative.with_suffix(".qpy.gz")
    stored.parent.mkdir(parents=True, exist_ok=True)
    tmp = stored.with_suffix(".tmp")
    try:
        with gzip.open(tmp, "wb", compresslevel=3) as stream:
            qpy.dump(native, stream)
        with gzip.open(tmp, "rb") as stream:
            (restored,) = qpy.load(stream)
        if not same_serialized_instructions(native, restored):
            raise ValueError(f"QPY round trip changed {relative}")
        actual, native_one = basis_counts(restored)
        if (len(actual) != len(expected) or parsed.num_2q_gates != len(expected) or
                native_one != expected_one or parsed.num_1q_gates != expected_one or
                cx_by_wire(parsed(), source.num_qubits) != reference_traces or
                cx_by_wire(actual, source.num_qubits) != reference_traces):
            raise ValueError(f"{relative}: parser, native artifact, and independent reference disagree")
        tmp.replace(stored)
    finally:
        tmp.unlink(missing_ok=True)
    return (str(relative), source.num_qubits, source_counts.get("cp", 0), old_cx,
            parsed.num_2q_gates, len(expected), old_one, parsed.num_1q_gates,
            zero_cp, cx_without_zero_cp, str(stored.relative_to(output)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inputs", required=True, type=Path, help="Released dataset bench directory")
    ap.add_argument("--output", required=True, type=Path, help="Native QPY output directory")
    ap.add_argument("--report", required=True, type=Path, help="Write the verified per-circuit TSV")
    args = ap.parse_args()
    paths = sorted(args.inputs.glob("*/*.qasm"))
    if not paths:
        ap.error("no QASM files found under inputs")
    rows = []
    for path in paths:
        row = compile_one(path, args.inputs, args.output)
        rows.append(row)
        print(f"{row[0]}: {row[3]} -> {row[4]} CX", flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(("source_qasm", "qubits", "source_cp", "prior_modeled_cx",
                         "parser_cx", "reference_cx", "prior_one_qubit_instructions",
                         "one_qubit_instructions", "source_exact_zero_cp",
                         "reference_cx_without_exact_zero_cp", "native_qpy_gz"))
        writer.writerows(rows)


if __name__ == "__main__":
    main()
