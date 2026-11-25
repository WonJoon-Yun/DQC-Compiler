# Issue 2 · Two-qubit gates missing from the interaction stream

The reported CZ omission is reproducible at the published revision `896e8da`. In the four-qubit example, the parser emits `0→1, 2→3`. Replacing only the CZ with a CX restores the middle interaction. The discrepancy exists before mapping or scheduling. The reporter's suggested rejection would expose an unsupported input. This fix can compile the reported CZ and preserve its single-qubit operations. [Original report and QASM](https://github.com/WonJoon-Yun/DQC-Compiler/issues/2)

## TODO and verification methodology

- [x] **Item 1. Preserve defined two-qubit operations.**
  - **a. Reproduce the failure.** Compare the reported circuit against the circuit with only its middle gate changed to CX. The corrected parser emits `0→1, 1→2, 2→3` for both. The CZ case contains five H gates, including the two target H gates from its decomposition. Both circuits retain four measurements. [Regression test](tests/test_parser.py)
  - **b. Check the gate semantics.** Compare the native circuit matrix with the source up to global phase, then compare one-qubit counts and the ordered, directed CX stream with a Qiskit 0.46.3 reference. All 24 standard two-qubit names were exercised. Tests cover custom and parameterized include definitions, reversed global operands, zero-CX definitions and a very small nonzero CP angle. All 50 supported cases passed. The largest phase-aligned matrix-entry error was `1.214e-15`. [Gate audit](revision/issue2-gate-audit.tsv)
  - **c. Check the failure boundary.** Opaque two-qubit input, raw three-qubit CCX and raw three-qubit CSWAP each produced a diagnostic with the gate and operands. A separately decomposed Fredkin input used 8 CX and 9 single-qubit instructions and matched the CSWAP matrix. A separate regression covers classically conditional two-qubit gates. [Audit script](revision/issue2_gate_audit.py)

- [x] **Item 2. Recompile the released inputs and check cached layers.**
  - **a. Establish the cost convention.** Compare to a routing-disabled, optimization-level-zero `u,cx` translation. CP uses two directed CX and three phase gates. RZZ uses two directed CX and one RZ. SWAP uses forward, reverse and forward CX. The source definition determines the cost of an explicitly declared gate. For example, bare ECR uses one CX and its exported QASM definition uses four. Both implement the same matrix. The audit records alternative level-zero translations where applicable. [Gate-by-gate comparison](revision/issue2-gate-audit.tsv)
  - **b. Validate each released source.** All 51 QASMs agreed with the reference on one-qubit instruction counts and directed CX order on every wire. The generated circuits also passed an ordered QPY write/read comparison including parameters and operands. All 68,055 additional CXs came from CP in the five QFT circuits. The other 46 CX counts were unchanged. One-qubit instruction counts, including existing one-wire directives and measurements, rose from 844,245 to 1,120,428. Full matrix comparisons were performed on the small gate fixtures. [Per-circuit report](revision/issue2-parser-dataset.tsv)
  - **c. Test the released caches.** The released QFT120 cache has 7,320 interactions and fails the comparison to the corrected 14,460-CX trace. The BV120 control matches at 119. The check allows reordering of gates on disjoint wires and keeps the existing declaration-only loader-stub behavior. [Cache regressions](tests/test_two_qubit_cache.py)

- [ ] **Item 3. Measure distributed results on the released QFT inputs.**
  - **a. Account for literal zero angles.** The five released QFT inputs contain 39,970 literal `cp(0)` operations. Level-zero lowering leaves two CXs per occurrence, and the parser keeps every occurrence. The smallest positive angle in these QFT inputs is π/2⁴¹. [Released inputs](https://zenodo.org/records/22152933)
  - **b. Compile the released QASM unchanged.** Every instruction in the released QASM is compiled, including each literal `cp(0)`. For QFT180 this gives 32,490 logical CXs.
  - **c. Measure physical outcomes.** QFT120, QFT180 and QFT240 are the only QFT inputs with published runs. Each was routed with QuComm, IRIS-noEES and IRIS from a fresh MinCut ILP mapping, which all three variants share. The runs use this branch merged with PR #5 at `c646806`, whose scheduling fixes make the schedules pass the issue #1 checks. All 9 schedules pass location, directional-channel and per-link occupancy replay. In every run the scheduled local CNOTs equal the parser's directed CX count, and no run uses a remote CNOT. IRIS uses 17%, 30% and 31% fewer state teleports than QuComm and has 45%, 46% and 39% lower latency. Eight Figure 16 entries have declaration-only loaders in place of source QASM and are outside the 51-circuit audit. [Per-run results](revision/issue2-distributed-qft.tsv) · [Tabulation script](revision/issue2_distributed_qft.py)
  - **d. Update the paper aggregates.** Put these three corrected-parser QFT rows in place of the published-workload QFT rows of the PR #5 reroutes. Over the 23 ready main configurations, the geometric-mean IRIS/QuComm `T_eff` ratio changes from 0.690 to 0.704 and the latency ratio from 0.503 to 0.501. The QFT rows use a fresh MinCut ILP mapping, and the other rows use the archived mappings. QV240 is not ready, so the 24-configuration values wait for its IRIS-noEES and IRIS reroutes. [PR #5 per-configuration results](https://github.com/WonJoon-Yun/DQC-Compiler/blob/65d0cc0d50c0557d650b1289a5f280aa180021ea/revision/issue1-performance.tsv)

| Input | Published modeled interactions | Native CX | Literal CP(0) |
|---|---:|---:|---:|
| QFT100 | 5,100 | 10,050 | 1,711 |
| QFT120 | 7,320 | 14,460 | 3,081 |
| QFT150 | 11,400 | 22,575 | 5,886 |
| QFT180 | 16,380 | 32,490 | 9,591 |
| QFT240 | 29,040 | 57,720 | 19,701 |
| All 51 released sources | 636,422 | 704,477 | 39,970 |

The distributed rows below use the same scheduler for both workloads. The published-workload rows come from the PR #5 reroute of the archived mapping and its 7,320, 16,380 and 29,040 interactions. IRIS latency is the postprocessed value.

| Input | Workload | QuComm state teleports | IRIS state teleports | QuComm ms | IRIS ms |
|---|---|---:|---:|---:|---:|
| QFT120 | Published | 988 | 698 | 1,540.86 | 854.14 |
| QFT120 | Corrected parser | 1,058 | 876 | 2,224.10 | 1,214.54 |
| QFT180 | Published | 3,978 | 2,282 | 3,664.21 | 2,170.37 |
| QFT180 | Corrected parser | 3,134 | 2,196 | 4,473.74 | 2,399.59 |
| QFT240 | Published | 7,302 | 4,580 | 4,782.71 | 2,965.63 |
| QFT240 | Corrected parser | 6,978 | 4,806 | 6,752.25 | 4,138.78 |

- [x] **Item 4. Compare parser CXs with the single-chip scheduler counter.**
  - **a. Run the compiler on each fixture.** Use one chip with three compute qubits, a fresh trivial mapping and IRIS4. All 24 standard gate names compiled. Across the 46 standalone cases with a nonempty CX stream, the reference and parser each counted 94 CXs. The completed schedule contained the same directed CNOTs in the same order for every case. The per-run `num_local_cnots` agreed in all 46 cases and summed to 94. Both teleportation counters stayed at zero. [Single-chip results](revision/issue2-single-chip.tsv)
  - **b. Compare representative costs.** CZ yielded 1 local CNOT, CP(π/4) and CP(0) each yielded 2, SWAP yielded 3 and externally decomposed CSWAP yielded 8. The exported ECR definition yielded 4 and the bare ECR spelling yielded 1.
  - **c. Check the limits of the measurement.** The mapper rejected four standalone fixtures with empty CX streams. Each yielded 1 local CNOT after appending a primitive CX, matching the measured 1-CNOT control. Their measured increments were all zero. The standalone counters are blank in the table. The CLI rejected raw CCX, raw CSWAP and an opaque operation before producing a schedule. [Reproduction script](revision/issue2_single_chip.py)

## Reproduce

Run from the repository root in the pinned `iris-ae` environment. The last command expects the released dataset in a sibling directory and writes the reconstructed QPY files and comparison table under `results/`.

```sh
python tests/test_parser.py ParserTests.test_reported_cz_between_two_cx_gates
python tests/test_two_qubit_cache.py
python revision/issue2_gate_audit.py
python revision/issue2_single_chip.py
python revision/issue2_parse_dataset.py --inputs ../IRIS-dataset/bench \
  --output results/issue2/native --report results/issue2/circuits.tsv
```

To repeat the distributed QFT runs, check out a merge of this branch with PR #5. The commands below route the released inputs into a fresh result tree and then tabulate them. A different CBC build can return a different optimal mapping.

```sh
export BENCH_DIR=$(cd ../IRIS-dataset/bench && pwd) RESULTS_DIR=$(mktemp -d)
for run in F120:qft_n120 F180:qft_n180 F240:qft_n240; do
  for script in run_qucomm run_iris_opt0 run_iris_opt1; do
    bash scripts/$script.sh ${run#*:} ${run%%:*} ILP
  done
done
python revision/issue2_distributed_qft.py --results "$RESULTS_DIR" --qasm "$BENCH_DIR" > distributed-qft.tsv
diff -u revision/issue2-distributed-qft.tsv distributed-qft.tsv
```

`ProgramParser(path)()` supplies the directed CX stream to the mapper. `ProgramParser(path).to_native_circuit()` exposes the full lowered circuit. The parser can represent zero-CX circuits. The existing mapper still requires a nonempty interaction stream.
