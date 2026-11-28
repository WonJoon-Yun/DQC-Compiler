# Issue #1 · Atom locations and channel evictions

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

- [x] **Item 4. Reserve directional channels when overlapping blocks or advancing moves.**
  - **a. QuComm.** In QFT180, routing blocks 340, 344, 345 and 346 in order returns two slots before consuming them. The parallel merger saw disjoint atoms and scheduled the two consumers first. The completed balance on `(0,1) → (0,2)` fell from 1 to −1 at 662.64048 ms with no move in flight. Across the full schedule the interval minimum was −2. Shor120 isolates the same constraint from atom placement. Its 15,309 archived operations pass location replay. The paired baseline reproduces every timestamp and dependency, with minimum −1. The correction raises the minimum to +1 while retaining all 1,751 moves, 13,558 local CNOTs and 3,084 block-end channel snapshots. The merger now replays debits at start and credits at finish for the entire candidate group. It delays block 116 by two ticks relative to block 115 and keeps the legal overlap of 187 and 188. [Recorded witness](revision/issue1-qft180-merge.json) · [Merger regressions](tests/test_qucomm_channel_merge.py) · [Paired QuComm results](revision/issue1-channel-reroutes.tsv)
  - **b. IRIS early execution.** All 33 BV240 routing epochs entered EES with at least one slot in every direction. Only epoch 24 became invalid. EES moved four hops from ticks 0, 3, 11 and 19 to tick 0. Its end-of-tick check saw a net change of zero. At the start, two consumers took two slots from an opening balance of one. The retimer now checks the proposed start and every intervening tick. Atoms 84 and 125 return slots at the end of tick 0. Atoms 47 and 48 use them at tick 3. BV240 retains all 239 CNOTs and 258 moves. Its raw latency increases from 288.02096 to 289.04460 ms and its postprocessed latency from 279.84392 to 280.86756 ms. Both minima improve from −1 to +1. BV120 and QAOA32 retain their raw and postprocessed timings. [EES regressions](tests/test_ees_directional.py) · [Paired EES results](revision/issue1-ees-channel-reroutes.tsv)
  - **c. Postprocessing.** A separate two-block example starts with one slot in the direction that the second hop needs. Its original two cycles are feasible. The legacy postprocessor reports one cycle by borrowing the first hop’s return at the start of that same cycle. Strict replay keeps the two verified cycles and records why it rejected the candidate. With three starting slots, the one-cycle schedule passes. The historical replay option retains the archived timing and records the violation. The verifier, timing script and Figure 14 use the same result selection. [Postprocessing regressions](tests/test_postprocess_channels.py)
  - **d. Coverage.** Replay each scored schedule from its initial atom positions and directional balances. Check every operation interval, each atom’s ordered gates and hops, the recorded closing state, and each postprocessed cycle. QuComm BV120 retains every operation time. IRIS-noEES BV120 and QAOA32 retain minima of 1 and 3 and raw times of 116.50684 and 57.96256 ms. A second planning-window size (`K1=2`) passes QuComm BV120, QuComm QAOA-3reg350, IRIS BV120 and IRIS QAOA32. [Independent interval verifier](src/analysis/schedule_locations.py)
  - **e. Link capacity.** Each flat-pool link has five interconnect pairs (`num_communication_per_link`). Of the 72 archived schedules, only the nine QV schedules exceed this number. Their peak link occupancy is 10/11/10 for QuComm, 8/12/11 for IRIS-noEES and 15/18/20 for IRIS at 120/180/240 qubits. The verifier now rejects a schedule that starts an inter-chip operation on a full link. The executable scheduler delays that operation until a pair is free, and latency rescoring replays the same limit. The limit applies after routing, so teleport counts and gate order do not change. In six paired QV reroutes with and without the limit, raw latency increases by 0.03% to 1.97%. All 72 reroutes have a peak of at most five. [Archived peaks](revision/issue1-archive-links.tsv) · [Reroute peaks](revision/issue1-reroute-links.tsv) · [Link regressions](tests/test_link_concurrency.py)

- [x] **Item 5. Determine the scope of benchmark and paper revisions.**
  - **a. Archived schedules.** Replaying the 72 archived main schedules finds 52 with negative directional balances, 10 that exhaust the last slot, and 10 that remain positive. Counts of negative, zero and positive minima are 12/6/6 for QuComm, 20/2/2 for IRIS-noEES and 20/2/2 for IRIS. Each of the 52 negative cases also reaches a negative completed-move balance. Archived operation logs include the original location errors and omitted moves. [Archived per-schedule results](revision/issue1-archive-channels.tsv)
  - **b. Reroute the main suite.** Each of the 72 MinCut QuComm, IRIS-noEES and IRIS configurations was rerouted at `c646806` from its archived mapping and layers. Each passes location, directional-channel and per-link replay, preserves its input gate order and block-end states, and has a raw minimum of +1. All 24 IRIS postprocessed schedules pass strict replay with a minimum of +1. Strict postprocessing keeps the original cycles in 18 of them, and the published runs used the parallelized result in all 24. In each configuration IRIS and IRIS-noEES have the same teleport counts, because EES changes only operation times. [Reroute peaks](revision/issue1-reroute-links.tsv) · [EES result selection](revision/issue1-ees-selection.tsv)
  - **c. Compare IRIS with QuComm.** Tables 5 (ILP rows) and 6 give 24 main configurations. Over these configurations, the geometric mean of the IRIS/QuComm `T_eff` ratio changes from 0.659 to 0.699. The geometric mean of the latency ratio changes from 0.494 to 0.500. IRIS has a lower `T_eff` and a lower latency than QuComm in each configuration. The largest rerouted `T_eff` ratio is 0.976 for BV180, and the largest latency ratio is 0.694 for BV180. Tables 5, 6 and 9 have 186 cells that change. [Per-configuration results](revision/issue1-performance.tsv) · [Geometric means](revision/issue1-performance-summary.tsv) · [Changed table cells](revision/issue1-table-changes.tsv) · [Table script](revision/issue1_revised_tables.py)
  - **d. Remaining work.** Update the paper aggregates, rankings and figures from these tables. The QFT rows in these tables use the published 16,380-CX workload to isolate scheduling. The corrected parser's QFT results are in the parser PR. Other mappers and hardware models need separate validation. [Parser issue](https://github.com/WonJoon-Yun/DQC-Compiler/issues/2)

## Reproduce

From the repository root in the artifact environment, point the commands at the extracted dataset. The archive check succeeds when all archived outcomes, including the known failures, match the manifest.

```sh
python revision/issue1_replay_archive.py ../IRIS-dataset
python revision/issue1_archive_channels.py ../IRIS-dataset > archive-channels.tsv
diff -u revision/issue1-archive-channels.tsv archive-channels.tsv
python -m unittest discover -s tests -p 'test_*.py'
python tests/test_ees_postcondition.py
python revision/issue1_channel_witness.py ../IRIS-dataset/MinCut/QuComm/qft_n180-S42C5-2x3
python revision/issue1_qft180_admission.py ../IRIS-dataset/MinCut/QuComm/qft_n180-S42C5-2x3
python revision/issue1_link_concurrency.py ../IRIS-dataset > archive-links.tsv
diff -u revision/issue1-archive-links.tsv archive-links.tsv
```

To rebuild the item 5 comparison, pass the worker reports and artifacts of the main-suite reroutes. The script replays every IRIS schedule with strict and historical postprocessing, rebuilds Tables 5, 6 and 9 for both sides and writes the IRIS/QuComm ratios.

```sh
python revision/issue1_revised_tables.py --dataset ../IRIS-dataset --reroutes <worker results> \
    --out "$(mktemp -d)/tables"
```

To see the failing diagnostic directly, run the following command. The MinCut case is labeled `IRIS/F120/ILP/bv_n120` and identifies atom 119 in block 8.

```sh
python tests/verify_extra_opt.py --root ../IRIS-dataset --variant IRIS --arch F120 --bench bv_n120
```

To repeat the paired QuComm QFT180 measurement, populate a fresh output directory with the archived mapper inputs using the artifact’s cache importer. It restores the configuration keys that the compiler checks before reusing the mapping. The compiler regenerates every routing block and the executable schedule. Running the same commands from each revision in its own fresh output directory gives the before and after cases.

```sh
dataset=$(cd ../IRIS-dataset && pwd)
export RESULTS_DIR=$(mktemp -d)
export BENCH_DIR="$RESULTS_DIR/bench"
export FIGURES_DIR="$RESULTS_DIR/figures"
python scripts/seed_from_dataset.py --dataset "$dataset" --results "$RESULTS_DIR" \
    --bench-dir "$BENCH_DIR" --benches qft_n180 --archs F180
bash scripts/run_qucomm.sh qft_n180 F180 ILP
python tests/verify_extra_opt.py --root "$RESULTS_DIR" --variant QuComm
```
