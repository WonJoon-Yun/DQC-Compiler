import math
import re
from pathlib import Path

from qiskit import qasm2
from qiskit.circuit import Barrier
from qiskit.circuit.library import (
    CPhaseGate, CXGate, ECRGate, GlobalPhaseGate, PhaseGate, RZGate, RZZGate, SGate, SXGate,
    XGate, get_standard_gate_name_mapping,
)
from qiskit.converters import circuit_to_dag


_CX = CXGate()


# Use Qiskit's constructors only for names that the source and its includes do
# not declare. Registering them unconditionally can replace valid gate bodies.
_EXTENSIONS = {item.name: item for item in qasm2.LEGACY_CUSTOM_INSTRUCTIONS if item.builtin}
for _name, _gate in get_standard_gate_name_mapping().items():
    if _gate.num_qubits == 2:
        _EXTENSIONS[_name] = qasm2.CustomInstruction(
            _name, len(_gate.params), 2, _gate.base_class, builtin=True)


# QASM2 supports quoted include names and line comments between tokens.
_QUOTED = r'''(?:"[^"\r\n]*"|'[^'\r\n]*')'''
_SPACE = r'(?:\s|//[^\r\n]*(?:\r?\n|$))*'
_DIRECTIVE = re.compile(
    rf'//[^\r\n]*|{_QUOTED}|\b(?:gate|opaque)\b{_SPACE}(?P<name>\w+)'
    rf'|\binclude\b{_SPACE}(?P<include>{_QUOTED}){_SPACE};|(?P<delimiter>[;{{}}])')


def _prepare_source(path, contents):
    """Inline physical includes before feeding their expressions to Qiskit 0.46.3.

    The pinned expression reader's next_token skips the first include frame.
    Keep qelib1.inc virtual, exactly as in qasm2.load, and retain source locations.
    """
    search_dirs = (*qasm2.LEGACY_INCLUDE_PATH, path.parent)
    declared = set()
    chunks = []
    origins = []
    next_line = 1

    def emit(text, file, line, column):
        nonlocal next_line
        if text:
            origins.append((next_line, file, line, column))
            chunks.append(text + '\n')
            next_line += text.count('\n') + 1

    def expand(file, source, ancestors):
        start, line, column, depth, statement_start = 0, 1, 0, 0, 0
        for token in _DIRECTIVE.finditer(source):
            if token['name']:
                declared.add(token['name'])
            if token['delimiter']:
                delimiter = token['delimiter']
                if delimiter in '{}':
                    depth += 1 if delimiter == '{' else -1
                statement_start = token.end()
            if not token['include']:
                continue
            include = token['include'][1:-1]
            prefix = source[start:token.start()]
            include_line = line + prefix.count('\n')
            loc = f'{file}:{include_line}'
            previous = re.sub(r'//[^\r\n]*', '', source[statement_start:token.start()])
            if depth or previous.strip():
                raise qasm2.QASM2ParseError(f'{loc}: include must be a top-level statement')
            statement_start = token.end()
            if include == 'qelib1.inc':
                continue
            child = next((d / include for d in search_dirs if (d / include).is_file()), None)
            if child is None:
                raise qasm2.QASM2ParseError(f'{loc}: cannot find include {include!r} in the include search path')
            child = child.resolve()
            if child in ancestors:
                raise qasm2.QASM2ParseError(f'{loc}: recursive include of {child}')
            emit(prefix, file, line, column)
            expand(child, child.read_text(encoding='utf-8'), ancestors | {child})
            line += source.count('\n', start, token.end())
            start = token.end()
            column = start - (source.rfind('\n', 0, start) + 1)
        emit(source[start:], file, line, column)

    expand(path, contents, {path.resolve()})
    return ''.join(chunks), declared, origins


def _load_circuit(filepath):
    path = Path(filepath)
    contents = path.read_text(encoding='utf-8')
    source, declared, origins = None, None, []
    # Every released input takes the normal file-loader path. A spelling other
    # than the canonical qelib include needs lexical inspection (comments may match).
    if contents.count('include') != contents.count('include "qelib1.inc";'):
        if any(t['include'] and t['include'][1:-1] != 'qelib1.inc' for t in _DIRECTIVE.finditer(contents)):
            source, declared, origins = _prepare_source(path, contents)
    enabled = {}
    while True:
        try:
            options = dict(include_path=qasm2.LEGACY_INCLUDE_PATH, custom_classical=qasm2.LEGACY_CUSTOM_CLASSICAL,
                           custom_instructions=enabled.values())
            return qasm2.load(path, **options) if source is None else qasm2.loads(source, **options)
        except qasm2.QASM2ParseError as exc:
            missing = re.search(r"'(\w+)' is not defined in this scope", str(exc))
            if missing and missing[1] in _EXTENSIONS and missing[1] not in enabled:
                if declared is None:
                    declared = set()
                    if 'gate' in contents or 'opaque' in contents:
                        declared = {t['name'] for t in _DIRECTIVE.finditer(contents) if t['name']}
                if missing[1] not in declared:
                    enabled[missing[1]] = _EXTENSIONS[missing[1]]
                    continue
            location = re.match(r'<input>:(\d+),(\d+): (.*)', exc.args[0])
            if location and origins:
                output_line, col = int(location[1]), int(location[2])
                first, file, line, offset = next(item for item in reversed(origins) if item[0] <= output_line)
                col += offset if output_line == first else 0
                raise qasm2.QASM2ParseError(f'{file}:{line + output_line - first},{col}: {location[3]}') from exc
            raise


def _lower(operation, wires):
    """Expand the operation's own definition, retaining its ordering and parameters."""
    if operation.condition is not None:
        raise ValueError('classical conditions cannot be represented by the interaction stream')
    if isinstance(operation, Barrier) or (len(wires) == 1 and hasattr(operation, '__array__')):
        yield operation, wires
        return
    if isinstance(operation, CXGate) and operation.ctrl_state == 1:
        yield operation, wires
        return

    # QFT and QAOA use many distinct angles. Generate their exact definitions
    # directly to avoid constructing a Qiskit definition circuit for every gate.
    if isinstance(operation, CPhaseGate) and operation.ctrl_state == 1:
        half_angle = operation.params[0] / 2
        positive_phase = PhaseGate(half_angle)
        yield positive_phase, (wires[0],)
        yield _CX, wires
        yield PhaseGate(-half_angle), (wires[1],)
        yield _CX, wires
        yield positive_phase, (wires[1],)
        return
    if isinstance(operation, ECRGate):
        # Exact one-CX standard equivalence, including the global phase.
        yield GlobalPhaseGate(-math.pi / 4), ()
        yield SGate(), (wires[0],)
        yield SXGate(), (wires[1],)
        yield _CX, wires
        yield XGate(), (wires[0],)
        return
    if isinstance(operation, RZZGate):
        yield _CX, wires
        yield RZGate(operation.params[0]), (wires[1],)
        yield _CX, wires
        return

    definition = operation.definition
    if definition is None:
        raise ValueError(f'opaque operation {operation.name!r} has no unitary definition')
    if definition.global_phase:
        yield GlobalPhaseGate(definition.global_phase), ()
    for instruction in definition.data:
        child_wires = tuple(wires[definition.find_bit(q).index] for q in instruction.qubits)
        yield from _lower(instruction.operation, child_wires)


def lower_two_qubit_gate(operation):
    """Yield (instruction, local wires) in one-qubit/CX order, retaining barriers and global phase."""
    if operation.num_qubits != 2:
        raise ValueError(f'expected a two-qubit operation, got {operation.name!r}')
    yield from _lower(operation, (0, 1))


class ProgramParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.parse()

    def _native_operations(self, operation, qargs):
        if len(qargs) <= 1 or isinstance(operation, Barrier):
            yield operation, qargs
            return
        if len(qargs) > 2:
            raise ValueError(
                f'{self.filepath}: unsupported {len(qargs)}-qubit operation '
                f'{operation.name!r} on qubits {list(qargs)}. Decompose it into two-qubit gates first.'
            )
        try:
            for native_op, local_wires in lower_two_qubit_gate(operation):
                yield native_op, tuple(qargs[i] for i in local_wires)
        except ValueError as exc:
            raise ValueError(
                f'{self.filepath}: cannot lower {operation.name!r} on qubits {list(qargs)}: {exc}'
            ) from exc

    def parse(self):
        qc = _load_circuit(self.filepath)
        self.num_qubits = qc.num_qubits
        self.has_multiple_qregs = len(qc.qregs) > 1
        self.has_source_operations = bool(qc.data)
        self.list_2q_gates = []
        self.num_1q_gates = 0
        for node in circuit_to_dag(qc).topological_op_nodes():
            qargs = tuple(qc.find_bit(q).index for q in node.qargs)
            for native_op, wires in self._native_operations(node.op, qargs):
                if len(wires) == 1:
                    self.num_1q_gates += 1
                elif isinstance(native_op, CXGate):
                    self.list_2q_gates.append(wires)
        self.num_2q_gates = len(self.list_2q_gates)

    def to_native_circuit(self):
        """Reread the QASM and emit native instructions in source order, including classical operands."""
        source = _load_circuit(self.filepath)
        native = source.copy_empty_like()
        for instruction in source.data:
            qargs = tuple(source.find_bit(q).index for q in instruction.qubits)
            for operation, wires in self._native_operations(instruction.operation, qargs):
                if isinstance(operation, GlobalPhaseGate):
                    native.global_phase += operation.params[0]
                else:
                    native.append(operation, list(wires), instruction.clbits)
        return native

    def __call__(self):
        return self.list_2q_gates
