Dear Reviewer @A8,

Thank you for taking the time to evaluate our artifact, and we apologize for the inconvenience.

Please update the repository and run:

```bash
git pull origin main
conda activate iris-ae

# Table 2 reproduction (~1 hour)
bash revision/table2.sh

# Figure 16 reproduction (~2 hours)
JOBS=32 bash revision/run_figure16_missing_data.sh
bash revision/plot_figure16.sh
```

- **Table 2:** We identified an issue in the data-collection path. After fixing it, rerunning the five benchmarks in parallel took approximately 52 minutes on our laptop (10-core M1 Max, macOS). The reproduced values exactly match Table 2.

- **Figure 16:** Eight QASM inputs for `qaoa_5reg`, `qaoa_7reg`, and `xorr` were omitted although their mappings and layers were included. We added a workflow that reruns the 150 affected schedules from the released mappings and layers, applies EES as post-processing, and stores the results in `results/_full`.
