# IRIS — Artifact Evaluation Package

This repository contains the IRIS compiler, our implementation of the QuComm
baseline, and the scripts that regenerate the tables and figures in the paper. 
The benchmark circuits, mapping results, DQC schedules, and raw results are archived on Zenodo as the IRIS-dataset.

Two reproduction workflows are supported:

* **Data-only** (under an hour): regenerate the tables and figures directly
  from the released results, without re-running the compiler.
* **Full re-run** (about 7 days on a 160-core server): re-run the
  routing/scheduling experiments and regenerate everything from the new
  results.

---

## 1. Requirements

* x86-64/Arm Linux (tested on Ubuntu 22.04), MacOS (tested on Apple Silicon)
* `conda` (Miniconda/Anaconda); `gcc` + `make` for the METIS C bindings
* ≥ 16 GB RAM (≥ 32 GB recommended for `F240` and large-scale runs)
* ~40 GB free disk for a full results sweep
* Optional: many cores (the runners fan out with `JOBS=$(nproc)`)

## 2. Setup

```bash
wget https://zenodo.org/records/22152933/files/IRIS-dataset.tar
tar -xf IRIS-dataset.tar

bash setup.sh
conda activate iris-ae
```

The tar is about 1.4 GB and unpacks to `./IRIS-dataset/`. `setup.sh` creates
the `iris-ae` conda env from `environment.yml` (METIS via the conda-forge
`metis=5.1.0` package, required by `pymetis`) and then copies the benchmarks
and mapping caches from `./IRIS-dataset` (also accepts `../IRIS-dataset`,
`./IRIS-dataset.tar`, `DATASET=/path`, or `DOWNLOAD_DATASET=1` to fetch it).

---

## 3. Reproduction workflows
### 3.1 Data-only workflow (Less than an hour)
```bash
bash scripts/get_data_all.sh --from_dataset
```

### 3.2 Full re-run workflow (About 7 days on 160 cores)
```bash
RESULTS_DIR=$PWD/results/_full bash scripts/reproduce_all.sh
bash scripts/get_data_all.sh --from_results
```

### 3.3 Importing benchmarks and mapping results

The benchmark circuits and the mapping results come from the IRIS-dataset
(several benchmark families use random angles or graphs, so the circuits are
copied rather than regenerated). Download the dataset from Zenodo
([zenodo.org/records/22152933](https://zenodo.org/records/22152933),
DOI `10.5281/zenodo.22152933`) **into the repository root**:

```bash
wget https://zenodo.org/records/22152933/files/IRIS-dataset.tar
tar -xf IRIS-dataset.tar
bash scripts/ensure_dataset.sh
```

The last command copies the benchmarks and mapping caches (it is also run
automatically by `setup.sh` and `reproduce_all.sh`); `./IRIS-dataset/` is
git-ignored.

`ensure_dataset.sh` (also run automatically by `setup.sh` and
`reproduce_all.sh`) finds the dataset at `./IRIS-dataset`, `../IRIS-dataset`,
`$DATASET`, or unpacks `./IRIS-dataset.tar`, then calls
`scripts/seed_from_dataset.py`, which does two things:

1. **Benchmarks** — copies `IRIS-dataset/bench/<family>/*.qasm` to
   `bench/<family>/`.
2. **Mapping results** — for every run in `IRIS-dataset/index.json`, unpacks
   `mapping.json.gz` / `layers.json.gz` / `compile_time.json.gz` into the
   mapping-cache location `src/run.py` checks — the same directory layout
   as the dataset itself:

   ```
   results/_full/<Mapping>/<Scheduling>/<bench>-<archdir>/
       mapping.json  layers.json  compile_time.json
   ```

   Mapping is the most expensive compilation stage as DQC architecture scales, 
   so the runners start from the released mapping results and re-run the scheduling stage. 
   The scheduler is deterministic (fixed seed), so the re-run metrics can be
   compared against the dataset's `results.json` directory by directory.

### 3.4 Outputs

Each experiment compiles three variants: `QuComm` (baseline), `IRIS-opt0`
(UMS), and `IRIS-opt1` (UMS + EES); the dataset names them `QuComm`,
`IRIS-noEES`, and `IRIS`. Runs are written to `results/_full/` in the same
layout as the dataset. Tables and figures are written to
`data_generator/output/` and `figures/`.

### 3.5 Sanity check (About 3 minutes)

```bash
make smoke
make tests
```

`make smoke` compiles one benchmark with all three variants; `make tests`
runs the EES post-condition tests and the schedule verifier.

---

## 4. What maps to what

Figure/table numbers follow the final (camera-ready) paper. Figures 1–10 and
20–23 are illustrations and have no data here.

| Paper artifact | Generator (`data_generator/`)                         | Experiment script (`scripts/`) |
|----------------|-------------------------------------------------------|--------------------------------|
| Table 1 / 2    | `section3/table1_relocate_intervals.py`, `table2_*`   | (from `results/_full/`)        |
| Table 3        | `section5/table3_benchmark_counts.py`                 | `seed_from_dataset.py` (bench) |
| Table 5        | `section6/table5_mapper_comparison_2x2.py`            | `table_5.sh`                   |
| Table 6        | `section6/table6_main_2x3_3x3.py`                     | `table_6.sh`                   |
| Table 7        | `section6/table7_qec_logical_cycle.py`                | `table_7.sh`                   |
| Table 8        | `section7/table8_complexity_scalability.py`           | `table_8.sh`                   |
| Table 9        | `appendix_e/table9_ees_latency_impact.py`             | (from `results/_full/`)        |
| Figure 11      | `section6/figure11_ums_cumulative_teleportation.py`   | `fig_11.sh`                    |
| Figure 12      | `scripts/plot/fig_12_crval.py`                        | `fig_12.sh`                    |
| Figure 13      | `scripts/plot/fig_13_contrib.py`                      | `fig_13.sh`                    |
| Figure 14      | `section6/figure14_ees_schedule.py`                   | `fig_14.sh`                    |
| Figure 15      | `section6/figure15_scaling.py`                        | `fig_15.sh`                    |
| Figure 16      | `section6/figure16_w_group_sensitivity.py`            | `fig_16.sh`                    |
| Figure 17      | `scripts/plot/fig_17_alpha.py`                        | `fig_17.sh`                    |
| Figure 18      | `scripts/plot/fig_18_commbudget.py`                   | `fig_18.sh`                    |
| Figure 19      | `section6/figure19_epr_pair_generation_latency.py`    | `fig_19.sh`                    |
| Figure 24      | `appendix_d/figure24_fidelity_breakdown.py`           | (from the IRIS-dataset)        |

Architectures: `F120/F180/F240` (40-qubit chips), `F500/F800/F1100`
(180-qubit chips), and explicit `S<qubits/chip>C<EPR/link>-<rows>x<cols>`
specs (e.g. `S46C5-2x2`). Mappers: `ILP` (Min-Cut), `GCP-ILP` (GCP-E),
`OEE-ILP` (sOEE), `WBCP`.

---

## 5. Customization

Scripts support standard environment-variable overrides:

| Variable | Default | Effect |
|---|---|---|
| `DATASET` | auto-detected | dataset location |
| `RESULTS_DIR` | `results/` | where runs are written/read |
| `BENCH_DIR` | `bench/` | benchmark QASM location |
| `FIGURES_DIR` | `figures/` | rendered PDFs |
| `JOBS` | `nproc` | parallel fan-out |
| `MODE=quick` | `full` | `reproduce_all.sh` smoke subset |
| `FORCE=1` | off | re-run experiments whose results already exist |

Per-script flags are documented in each script header. New benchmarks are
OpenQASM 2 files under `bench/<family>/`; new architectures use the
`S<qubits/chip>C<EPR/link>-<rows>x<cols>` spec. A single (benchmark,
architecture, mapper) combination runs with all three variants via
`bash scripts/run_all_variants.sh <bench> <arch> <mapper>`.

---

## 6. Directory layout

```
DQC-Compiler/
├── setup.sh  environment.yml     # environment
├── src/                          # the IRIS compiler (run.py = entry point)
├── scripts/                      # experiment runners (reproduce_all.sh, fig_*.sh, table_*.sh)
├── data_generator/               # table/figure generation (output/ holds the results)
├── bench/                        # benchmark circuits (copied from the IRIS-dataset)
├── results/                      # per-run outputs
├── figures/                      # rendered figures
├── tests/                        # EES post-condition tests + schedule verifier
└── notebooks/quick_start.ipynb   # Hands-on experience
```
