# Issue #1 — Atom locations and channel evictions

At `896e8da`, the reported IRIS and QuComm schedules contain operations that use an atom on a different chip from its last recorded location. Independent replay reproduced both counts in the report. The counts describe schedules with at least one inconsistent operation. Inferring the missing hop sequence or its time requires tracing the router. [Original report and replay scripts](https://github.com/WonJoon-Yun/DQC-Compiler/issues/1) · [Published dataset](https://zenodo.org/records/22152933)

## TODO and verification methodology

- [x] **Item 1. Confirm the reported failures and check atom locations in the verifier.**
  - **a.** Replay the archived MinCut BV120 schedule from its flat-pool placement. Atom 119 finishes a layer-7 CNOT on `(0,0)` and starts a layer-8 CNOT on `(0,1)` with no intervening relocation.
  - **b.** Inspect the saved 118-operation QAOA-3reg n32 baseline. Atoms 35 and 67 undergo consecutive CNOTs on `(0,0)` and `(0,1)`. The verifier at `896e8da` accepts that schedule. The new verifier tracks each atom's position and availability during execution, including after IRIS early-execution postprocessing. New schedules record their initial placement.
  - **c.** Check all 72 compressed schedules against the SHA-256 digests, operation counts, relocation counts and first errors in the manifest. The issue reporter's replay independently reproduces IRIS **22/24** and QuComm **10/24**. Replaying IRIS-noEES adds **22/24**. The data-only reproduction path retains historical timings and records location errors in its sidecar. [Archive manifest](revision/issue1-archive-audit.tsv) · [Replay utility](revision/issue1_replay_archive.py)

- [x] **Item 2. Pass the executed IRIS state between blocks.**
  - **a.** Compare the forecast and executed paths of BV120 atom 119 at the end of block 7. The forecast ends on `(0,1)` and the executed path ends on `(0,0)`. The following block previously started from the forecast.
  - **b.** In the five-atom regression, run one and two blocks. Reconstruct the paths and channel balances from their actual operations, then compare the next block's initial state and pending gates with those paths and balances.
  - **c.** Replay BV120, BV240 and QAOA32 after the state handoff change. The tested IRIS variants preserve each atom's directed CNOT sequence and have zero inconsistent locations. BV120 state teleports change from 60 to 61, BV240 from 262 to 258, and QAOA32 remains at 22. [Block-boundary regression](tests/test_block_boundary_state.py) · [Representative results](revision/issue1-representatives.tsv)

- [x] **Item 3. Emit physical QuComm evictions and charge each hop once.**
  - **a.** For a saturated link in a three-chip, one-gate case, trace the victim in the eviction log and output schedule. The original gate-only rows could omit a moved spectator. The issue identifies this omission correctly. A victim that already appears in a gate row requires a separate duplication check.
  - **b.** Test inactive and active victims, two consecutive evictions, and a free-link control. Check exactly one relocation per physical hop and order the next hop that needs the released slot after the eviction. The minimal saturated case emits three state teleports, including the eviction.
  - **c.** Apply the published metric `T_eff = state_teleportations + 1.77 × gate_teleportations`. Charging the eviction as a state teleport accounts for the physical hop. Adding the release counter again would charge it twice. QuComm QFT180 changes from 3,974 to 3,978 state teleports, VQE180 from 1,998 to 1,999, and the BV120 control stays at 73. [Eviction regressions](tests/test_eviction_schedule.py) · [Metric definition](data_generator/_lib.py)

- [ ] **Item 4. Enforce directional channel capacity during cross-block overlap.**
  - **a.** Replay the published and revised QuComm QFT180 schedules. At 662.64048 ms, direction `(0,1) → (0,2)` reaches `5 + 27 − 33 = −1` after grouping all hops with the same completion time. No operation spans this boundary. The QuComm BV120 control stays nonnegative.
  - **b.** Inspect the first 75 merged groups. Disjoint atom sets can share a directional channel. For recorded blocks 115–116, a two-tick delay gives a minimum post-debit balance of 1. The control pair 187–188 accepts zero delay. Both pairs retain five hops and nine CNOTs. [Recorded merge trace](revision/issue1-qft180-merge.json) · [Offline admission experiment](revision/issue1_qft180_admission.py)
  - **c.** Pending. Apply the admission check in the production block merger and validate all QFT180 blocks, including minimum balance and the resulting latency. Current QFT180 timings cannot establish a physically admissible execution.

- [ ] **Item 5. Determine the scope of any benchmark or paper revisions.**
  - **a.** Nine representative before/after pairs have been checked, including six of the 72 main configurations. Every pair uses the same mapping and gate layers on both sides. All nine revised schedules pass location replay. The representative table records raw timings before postprocessing. [Paired measurements](revision/issue1-representatives.tsv)
  - **b.** Pending. Recompile the other 66 main configurations after resolving channel capacity and agreeing on the parser input. The QFT180 routing comparison here used the archived 16,380-interaction input. Parser work for issue #2 gives 32,490 CX with unoptimized basis lowering. The measured routing times here apply to the former input. [Parser issue](https://github.com/WonJoon-Yun/DQC-Compiler/issues/2)
  - **c.** Pending. Recompute aggregates, rankings and affected figures from validated schedules. Other mapping methods and hardware models also need separate coverage before generalizing the results.

## Reproduce

From the repository root in the artifact environment, point the commands at the extracted dataset. The archive check succeeds when all archived outcomes, including the known failures, match the manifest.

```sh
python revision/issue1_replay_archive.py ../IRIS-dataset
python -m unittest discover -s tests -p 'test_*.py'
python tests/test_ees_postcondition.py
python revision/issue1_channel_witness.py ../IRIS-dataset/MinCut/QuComm/qft_n180-S42C5-2x3
python revision/issue1_qft180_admission.py ../IRIS-dataset/MinCut/QuComm/qft_n180-S42C5-2x3
```

To see the failing diagnostic directly, run the following command. The MinCut case is labeled `IRIS/F120/ILP/bv_n120` and identifies atom 119 in block 8.

```sh
python tests/verify_extra_opt.py --root ../IRIS-dataset --variant IRIS --arch F120 --bench bv_n120
```
