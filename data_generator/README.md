# Data Generator (IRIS Paper Figures & Tables)

Each script regenerates one figure or table from the paper directly from the
AE result tree (`results/_full/`), with **no dependency on any upstream IRIS
development tree**. Figure/table numbers follow the final (camera-ready)
paper.

## Layout

```
data_generator/
├── _lib.py                                            # shared path helpers
├── run_all.sh                                         # rebuild everything
├── output/                                            # generated CSVs/PDFs/TEXs land here
├── section3/
│   ├── table1_relocate_intervals.py                   # §3.1 Table 1
│   └── table2_delayed_teleportations.py               # §3.2 Table 2
├── section5/
│   └── table3_benchmark_counts.py                     # §5.1 Table 3
├── section6/
│   ├── table5_mapper_comparison_2x2.py                # §6.1 Table 5
│   ├── table6_main_2x3_3x3.py                         # §6.1 Table 6
│   ├── table7_qec_logical_cycle.py                    # §6.10 Table 7
│   ├── _build_qec_summary.py                          # (Table 7 LCT helper)
│   ├── figure11_ums_cumulative_teleportation.py       # §6.2 Figure 11
│   ├── figure14_ees_schedule.py                       # §6.5 Figure 14
│   ├── figure15_scaling.py                            # §6.6 Figure 15
│   ├── figure16_w_group_sensitivity.py                # §6.7 Figure 16
│   └── figure19_epr_pair_generation_latency.py        # §6.9 Figure 19
├── section7/
│   └── table8_complexity_scalability.py               # §7   Table 8    (stub if no n=500/800/1100)
├── appendix_d/
│   └── figure24_fidelity_breakdown.py                 # App.D Figure 24
└── appendix_e/
    └── table9_ees_latency_impact.py                   # App.E Table 9
```

## Coverage map

| Section | Item | Generator | Data source |
|---|---|---|---|
| §3.1   | Table 1  | `section3/table1_relocate_intervals.py`       | QuComm Schedule JSONs, F240/n240, 5 benches |
| §3.2   | Table 2  | `section3/table2_delayed_teleportations.py`   | QuComm Tracer CSVs, F240/n240, 5 benches |
| §5.1   | Table 3  | `section5/table3_benchmark_counts.py`         | `bench/<family>/<family>_n<N>.qasm` |
| §6.1   | Table 5  | `section6/table5_mapper_comparison_2x2.py`    | F120 × 4 mappers × 8 benches × 3 variants |
| §6.1   | Table 6  | `section6/table6_main_2x3_3x3.py`             | F180/F240 × ILP × 8 benches × 3 variants |
| §6.2   | Fig 11   | `section6/figure11_ums_cumulative_teleportation.py` | Shor n240 / F240 `results.json` per-block profile |
| §6.4   | Fig 13   | `scripts/plot/fig_13_contrib.py` (run side)   | `scripts/fig_13.sh` UMS-ablation runs |
| §6.5   | Fig 14   | `section6/figure14_ees_schedule.py`           | qaoa_3reg n240 / F240 `schedule.json` (+ EES replay for the IRIS line) |
| §6.6   | Fig 15   | `section6/figure15_scaling.py`                | F120/F180/F240 main sweep |
| §6.7   | Fig 16   | `section6/figure16_w_group_sensitivity.py`    | `fig_16.sh` w/\|G\| sweep (or dataset sweep dirs) |
| §6.9   | Fig 19   | `section6/figure19_epr_pair_generation_latency.py` | qaoa_fc n240 / F240 `schedule.json` replayed at swept EPR latencies |
| §6.10  | Table 7  | `section6/table7_qec_logical_cycle.py`        | QEC runs (`table_7.sh` / dataset) |
| §7     | Table 8  | `section7/table8_complexity_scalability.py`   | qaoa_3reg n=500/800/1100 (run `table_8.sh` first) |
| App.D  | Fig 24   | `appendix_d/figure24_fidelity_breakdown.py`   | qaoa_3reg n32 / `2x2-2x2-3` old-model runs (IRIS-dataset; dataset mode) |
| App.E  | Table 9  | `appendix_e/table9_ees_latency_impact.py`     | extra_opt.json files for IRIS-opt1 |

Figures 1–10 and 20–23 are illustrations (not data-driven). Figures 12
(§6.3, C_R estimator validation), 17 and 18 (§6.8, hardware-parameter
sensitivity) are produced by run-side scripts rather than data_generator:
`scripts/fig_12.sh`, `scripts/fig_17.sh`, `scripts/fig_18.sh`.

## Running

```bash
# Rebuild everything (run after scripts/reproduce_all.sh has populated results/_full/)
bash data_generator/run_all.sh

# Rebuild only one section
bash data_generator/run_all.sh section6

# Run a single script directly
PYTHONPATH=src python data_generator/section6/table6_main_2x3_3x3.py
```

Or use the top-level driver, which also supports extracting everything
directly from the released IRIS-dataset:

```bash
bash scripts/get_data_all.sh --from_dataset     # no re-runs needed
bash scripts/get_data_all.sh --from_results     # from results/_full
```

## Environment overrides

| Variable | Default | Purpose |
|---|---|---|
| `ARTIFACT_ROOT` | parent of `data_generator/` | Artifact root |
| `RESULTS_BASE`  | `$ARTIFACT_ROOT/results/_full` | Where result JSONs live |
| `BENCH_DIR`     | `$ARTIFACT_ROOT/bench` | Where benchmark QASMs live |
| `FOCUS_BENCH`   | `qaoa_fc_n240` | Default case-study benchmark |
| `FOCUS_ARCH`    | `F240` | Default case-study arch |
| `PYTHON`        | conda env binary | Python interpreter |

## Outputs

Each script writes to `data_generator/output/<section>/<name>.{csv,tex,pdf,png}`.
PDFs are produced only when matplotlib is available; CSVs are produced
unconditionally and are the authoritative source of paper numbers.

## Notes

* `figure16_*` writes a "data not available" note when the w/\|G\| sweep is
  missing (`fig_16.sh`, or the pre-computed sweep runs in the IRIS-dataset).
* `figure14_*` and `figure19_*` replay saved schedules (`_early_execution.py`
  and `src/analysis/schedule_rescore.py`); the replays take a few minutes.
* `table7_*` computes the logical-cycle table from the QEC runs
  (`table_7.sh`, or the QEC runs in the IRIS-dataset).
