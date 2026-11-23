# Issue 3 · Preserve qubit identities across OpenQASM registers

The four-qubit GHZ example in [issue #3](https://github.com/WonJoon-Yun/DQC-Compiler/issues/3) reproduces on `896e8da`. The parser counts all three CX gates in both register layouts. It assigns the wrong operands when the qubits span two registers. The ILP mapper therefore receives a circuit that uses only two logical identities.

| Revision and register layout | Directed CX operands before mapping | Logical keys in the ILP mapping |
|---|---|---|
| `896e8da`, `a[2], b[2]` | (0,1), (1,0), (0,1) | 0, 1 |
| `896e8da`, `q[4]` | (0,1), (1,2), (2,3) | 0, 1, 2, 3 |
| This fix, either layout | (0,1), (1,2), (2,3) | 0, 1, 2, 3 |

## TODO and verification methodology

- [x] **Problem item 1 — Resolve operands in the whole circuit.** The parser now uses Qiskit's `qc.find_bit(qubit).index`. The register-local index previously mapped `a[0]` and `b[0]` to 0.
  - a. Parse the reported GHZ circuit and the same gates in a single register. Compare circuit width, total CX count and the operands of each CX.
  - b. Repeat with registers of different sizes and an unused wire. In `a[3], b[2]`, the gates `cx b[0],a[0]` and `cx a[0],b[1]` must use (3,0) and (0,4).
  - c. Run ILP mapping on the reported 2×1 topology. The published version reproduced the exact map `{"1": 2, "0": 0}`. The fixed split and flat inputs both produced `{"0": 2, "1": 3, "2": 0, "3": 1}`. Four distinct logical identities and the directed CX sequence are the regression criteria.
- [x] **Problem item 2 — Reject mapping caches that contain aliased interactions.** For multiple quantum registers, the cache reader projects the parsed logical gates through the cached placement and compares the directed gate sequence on each physical wire. Gates on disjoint wires may change order.
  - a. Seed a cache with all four keys and the old aliased layers. Confirm that the mapper rebuilds it and produces the expected three layers. Removing the timing file from the cache must also trigger a rebuild.
  - b. Check the replacement mapping, layers and timing files in both the existing flat cache and the mapper output directory. Run again and verify that the repaired cache is reused.
  - c. Verify reuse for valid multi-register layers, including reordered independent gates, and for a declaration-only single-register loader stub. The Figure 16 loaders rely on stored layers.
- [x] **Problem item 3 — Check the released programs for regressions.**
  - a. Enumerate all 51 original QASM files under `bench/` in the [released dataset](https://zenodo.org/records/22152933). All 51 use a single quantum register.
  - b. Compare the width, one-qubit instruction count, two-qubit interaction count and complete ordered list of directed operand pairs for each file against `896e8da`.
  - c. All 51 matched on this register-index change. The totals were 844,245 one-qubit instructions and 636,422 interactions under the original gate-accounting rules. The split-register GHZ provides the positive test for the defect.
- [ ] **Evidence gap — Recover the eight original Figure 16 circuits if their register structure needs auditing.** The supplied loader stubs contain declarations only. Validation on the original circuits requires the missing QASM sources.

## Reproduce

Activate the repository's `iris-ae` environment and run from the repository root. The first command exercises only the parser.

```bash
python tests/test_parser.py ParserTests.test_ghz_register_layout ParserTests.test_register_offsets_include_unused_qubits
```

The following check stops after ILP mapping. It uses the GHZ fixtures from the regression tests and requires a working CBC solver.

```bash
PYTHONPATH=src:tests python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from hardware import Hardware
from hyperparameters import HyperParameters
from mapper import Mapper
from parser import ProgramParser
from test_parser import FLAT_GHZ, HEADER, SPLIT_GHZ

for label, body in [('split', SPLIT_GHZ), ('flat', FLAT_GHZ)]:
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'ghz.qasm'
        path.write_text(HEADER + body)
        parsed = ProgramParser(str(path))
        args = HyperParameters(name=label, results_dir=directory, mapping_method='ILP',
                               num_qubits=4, numchipletsx=2, numchipletsy=1,
                               system_qubits_per_chip=4, num_communication_per_link=2)
        mapping, layers = Mapper(args, Hardware(args), parsed()).compile()
        print(label, parsed(), mapping, layers)
        assert parsed() == [(0, 1), (1, 2), (2, 3)]
        assert set(map(int, mapping)) == {0, 1, 2, 3}
PY
```

Run `python tests/test_parser.py` for the full register and cache regression suite. Its CLI cases exercise the small GHZ circuit with the trivial mapper and IRIS4.
