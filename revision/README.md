# AE revision workflows

## Table 2

Run the five 240-qubit QuComm schedules on the F240 (3x3) architecture and
derive the delayed-teleportation percentage and average wait directly from the
new tracer files:

```bash
bash revision/table2.sh
```

The generated table is copied to
`revision/table2_delayed_teleportations.csv`. The workflow is resume-safe and
checks the final CSV against the released reference.

## Figure 16 data-only reproduction

The released Figure 16 data contains all 598 sweep runs, including:

- `qaoa_5reg_n120`, `qaoa_5reg_n180`, `qaoa_5reg_n240`
- `qaoa_7reg_n120`, `qaoa_7reg_n180`, `qaoa_7reg_n240`
- `xorr_n120`, `xorr_n180`

Render the complete figure from the released data with:

```bash
bash revision/plot_figure16.sh
```

The CSV, PDF, and PNG are copied to `revision/`. The plotting overlay always
contains 598 runs and prints how many came from fresh reruns versus the released
data fallback.

## Figure 16 missing-input scheduling rerun

The released dataset contains the exact `mapping.json`, `layers.json`, and
`compile_time.json` for all Figure 16 runs, but it does not contain the eight
QASM inputs listed above. The files under `revision/missing_qasm/` are explicitly
cache-only loader stubs: they declare the correct logical-qubit count but do not
claim to reconstruct the original circuits. The released `layers.json` remains
the complete scheduling input.

Run or resume the 150 affected scheduling sweeps with:

```bash
bash revision/run_figure16_missing_data.sh
bash revision/plot_figure16.sh
```

By default, the runner writes into `results/_full`, the same result tree used
by `scripts/reproduce_all.sh`. This fills the missing Figure 16 directories in
place, and the plotting script automatically prefers those fresh results.
Set `RESULTS_DIR=/another/path` only when an isolated smoke or diagnostic run
is desired.

Before starting, the runner checks that every sweep directory has the released
mapping, layers, and compile-time cache and that the mapping size matches the
declared qubit count. It refuses to proceed with an incomplete cache. A full run
is long; completed results are skipped when the command is resumed.

For a small smoke test:

```bash
SCHEDS=IRIS-bw2 BENCH_FILTER=xorr_ JOBS=2 \
  RESULTS_DIR="$PWD/results/_figure16_missing_smoke" \
  bash revision/run_figure16_missing_data.sh
```
