"""Check saved mapping layers against the parsed CX stream before reuse."""
from collections import defaultdict


def can_reuse_cached_layers(mapping, layers, program_parser):
    # Declaration-only single-register QASM is the existing cache-loader stub.
    # A real operation can lower to zero CXs and still requires validation.
    if not program_parser.has_multiple_qregs and not program_parser.has_source_operations:
        return True
    program = program_parser()
    if sum(len(layer) for layer in layers) != len(program):
        return False

    # Independent gates may move between layers. The directed gate sequence on
    # each wire must still match the parsed program under the cached placement.
    def gates_by_wire(gates):
        traces = defaultdict(list)
        for control, target in gates:
            gate = (control, target)
            traces[control].append(gate)
            traces[target].append(gate)
        return traces

    if len(set(mapping.values())) != len(mapping):
        return False
    try:
        expected = gates_by_wire((mapping[str(a)], mapping[str(b)]) for a, b in program)
    except KeyError:
        return False
    return expected == gates_by_wire(gate for layer in layers for gate in layer)
