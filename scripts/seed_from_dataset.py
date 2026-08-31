#!/usr/bin/env python3
"""Import benchmarks and mapping caches from the published IRIS-dataset.

Get the dataset from Zenodo (https://zenodo.org/records/22152933,
DOI 10.5281/zenodo.22152933) and unpack it:  tar -xf IRIS-dataset.tar

Copies, from the unpacked IRIS-dataset directory:

  1. Benchmarks:  IRIS-dataset/bench/<family>/*.qasm  ->  bench/<family>/
  2. Mapping caches: for every base run in the dataset index, the exact
     mapper outputs (mapping.json / layers.json / compile_time.json) into

       <results>/<Mapping>/<Scheduling>/<bench>-<archdir>/

     — the same directory layout as the dataset itself. The run scripts
     invoke src/run.py with --flat_output, which reads the mapping cache
     from (and writes all outputs to) exactly that directory. With the
     cache in place the (nondeterministic, slow) ILP mapper is skipped and
     every scheduling run reproduces the dataset's results exactly — the
     router is deterministic given the same mapping (seed 42).

The dataset's compile_time.json predates the cache-validation keys, so the
OEE-config fields are filled in here (all dataset runs used oee_on_p5_t0p0,
i.e. use_oee_refine=True, oee_max_passes=5, oee_tol=0.0).

Usage:
  python scripts/seed_from_dataset.py --dataset /path/to/IRIS-dataset
  python scripts/seed_from_dataset.py --dataset ../IRIS-dataset \
      --results results/_full --benches bv_n120,qft_n120 --archs F120
"""
import argparse
import gzip
import json
import re
import shutil
import sys
from pathlib import Path

AE_ROOT = Path(__file__).resolve().parent.parent

# Flat-pool arch dirs (S<S>C<C>-<X>x<Y>) are handled generically; old-model
# dirs (e.g. 2x2-2x2-3, Fig 24) are not imported.
FLATPOOL_RE = re.compile(r"^S\d+C\d+-\d+x\d+$")
# results are stored in the dataset's own layout <Mapping>/<Scheduling>/<bench>-<archdir>/;
# every scheduling dir gets the same mapper output (mapping is scheduler-independent)
SCHED_DIRS = ("QuComm", "IRIS-noEES", "IRIS")
BASE_SCHEDS = {"QuComm": 0, "IRIS": 1, "IRIS-noEES": 2}  # source preference order
# OEE config of all dataset runs (source path component: oee_on_p5_t0p0)
CACHE_KEYS = {"use_oee_refine": True, "oee_max_passes": 5, "oee_tol": 0.0}


def gunzip_to(src: Path, dst: Path) -> None:
    dst.write_bytes(gzip.decompress(src.read_bytes()))


def copy_benchmarks(dataset: Path, bench_dir: Path, dry: bool) -> int:
    n = 0
    for qasm in sorted((dataset / "bench").glob("*/*.qasm")):
        dst = bench_dir / qasm.parent.name / qasm.name
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(qasm, dst)
        n += 1
    return n


def _write_cache(src: Path, cache: Path, dry: bool) -> None:
    ct = json.loads(gzip.decompress((src / "compile_time.json.gz").read_bytes()))
    for k, v in CACHE_KEYS.items():
        ct.setdefault(k, v)
    ct.setdefault("cost", ct.get("cost_static_oee", ct.get("cost_ilp")))
    if not dry:
        cache.mkdir(parents=True, exist_ok=True)
        gunzip_to(src / "mapping.json.gz", cache / "mapping.json")
        gunzip_to(src / "layers.json.gz", cache / "layers.json")
        (cache / "compile_time.json").write_text(json.dumps(ct))


def seed_caches(dataset: Path, results: Path, benches, archs, dry: bool):
    index = json.loads((dataset / "index.json").read_text())
    # Each run cache comes from ITS OWN dataset dir (mapper outputs can differ
    # per scheduling run); scheduling dirs the dataset lacks (e.g. IRIS-noEES
    # under GCP-E/sOEE/WBCP) fall back to the preferred sibling's mapping.
    own, sources, sweeps, skipped = {}, {}, [], 0
    for run in index:
        if not FLATPOOL_RE.match(run["arch_dir"]):
            skipped += 1  # old-model architecture (e.g. Fig 24's 2x2-2x2-3)
            continue
        if benches and run["bench"] not in benches:
            continue
        if archs and run["arch_dir"] not in archs and _preset_name(run["arch_dir"]) not in archs:
            continue
        if run["scheduling"] not in BASE_SCHEDS:
            # -bw/-lh/-memtrace sweep runs (Fig 16 / Table 8): import 1:1
            sweeps.append(run)
            continue
        key = (run["mapping"], run["bench"], run["arch_dir"])
        own[key + (run["scheduling"],)] = dataset / run["path"]
        rank = BASE_SCHEDS[run["scheduling"]]
        if key not in sources or rank < sources[key][0]:
            sources[key] = (rank, dataset / run["path"])

    seeded = 0
    for (mapping, bench, arch_dir), (_, fallback) in sorted(sources.items()):
        for sched in SCHED_DIRS:
            src = own.get((mapping, bench, arch_dir, sched), fallback)
            _write_cache(src, results / mapping / sched / f"{bench}-{arch_dir}", dry)
            seeded += 1
    for run in sweeps:
        cache = results / run["mapping"] / run["scheduling"] / f"{run['bench']}-{run['arch_dir']}"
        _write_cache(dataset / run["path"], cache, dry)
        seeded += 1
    return len(sources) + len(sweeps), seeded, skipped


# artifact arch preset <-> dataset arch dir (for the --archs filter convenience)
_PRESET_BY_DIR = {
    "S40C5-2x2": "F120", "S42C5-2x3": "F180", "S40C5-3x3": "F240",
    "S180C18-2x2": "F500", "S180C18-2x3": "F800", "S180C18-3x3": "F1100",
}


def _preset_name(arch_dir: str) -> str:
    return _PRESET_BY_DIR.get(arch_dir, arch_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True, type=Path,
                    help="Path to the unpacked IRIS-dataset directory")
    ap.add_argument("--results", type=Path, default=AE_ROOT / "results/_full",
                    help="Results root the run scripts will use (default: results/_full)")
    ap.add_argument("--bench-dir", type=Path, default=AE_ROOT / "bench",
                    help="Where to copy the .qasm benchmarks (default: bench/)")
    ap.add_argument("--benches", default="", help="Comma list, e.g. bv_n120,qft_n120 (default: all)")
    ap.add_argument("--archs", default="", help="Comma list, e.g. F120,F240 (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dataset = args.dataset.expanduser().resolve()
    if not (dataset / "index.json").is_file():
        print(f"error: {dataset} does not look like IRIS-dataset (no index.json)", file=sys.stderr)
        return 2

    benches = {b for b in args.benches.split(",") if b}
    archs = {a for a in args.archs.split(",") if a}

    nq = copy_benchmarks(dataset, args.bench_dir, args.dry_run)
    nmap, ncache, nskip = seed_caches(dataset, args.results, benches, archs, args.dry_run)

    tag = "[dry-run] " if args.dry_run else ""
    print(f"{tag}benchmarks copied : {nq} .qasm -> {args.bench_dir}")
    print(f"{tag}mapper outputs    : {nmap} (mapping,bench,arch) tuples")
    print(f"{tag}caches imported   : {ncache} run dirs -> {args.results}")
    if nskip:
        print(f"note: {nskip} dataset runs use old-model architectures (e.g. Fig 24's 2x2-2x2-3); "
              f"their mappings were not imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
