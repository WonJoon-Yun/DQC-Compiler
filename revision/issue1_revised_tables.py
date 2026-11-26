"""Rebuild Tables 5, 6 and 9 from the validated main-suite reroutes and compare IRIS with QuComm.

Each reroute directory holds one worker report (<case>.<job>.json) and one artifact
(<case>.<job>.tar.gz with schedule.json, results.json, resource_capacity_epochs.json).
The published side uses the dataset with historical EES replay, as the paper did.
The rerouted side replaces the 72 MinCut QuComm, IRIS-noEES and IRIS runs and uses
strict EES replay. Every other run is shared, so only main-suite rows can change.
A configuration named with --pending keeps its published runs and is reported as not ready.

  python revision/issue1_revised_tables.py --dataset ../IRIS-dataset --reroutes <worker results> \
      --pending qv_n240--F240 --out <fresh dir>
"""
import argparse
import csv
import gzip
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("QuComm", "IRIS-noEES", "IRIS")
ARCH_DIRS = {"F120": "S40C5-2x2", "F180": "S42C5-2x3", "F240": "S40C5-3x3"}
BENCHES = ("bv", "qaoa_3reg", "qaoa_fc", "qft", "qugan", "qv", "shor", "vqe")
CONFIGS = [(arch, f"{b}_n{arch[1:]}") for arch in ARCH_DIRS for b in BENCHES]
NOT_READY = "not ready"
REPLACED = ("schedule.json.gz", "results.json.gz", "resource_capacity_epochs.json.gz")
TABLES = {
    "table5": ("section6", "table5_mapper_comparison_2x2"),
    "table6": ("section6", "table6_main_2x3_3x3"),
    "table9": ("appendix_e", "table9_ees_latency_impact"),
}


def load_reroutes(directory, pending):
    reports = {}
    for path in sorted(directory.glob("*.json")):
        report = json.loads(path.read_text())
        case = report["case_id"]
        _, bench, arch = case.split("--")
        if (arch, bench) in pending:
            continue
        if report.get("status") != "passed":
            raise SystemExit(f"{case}: worker status {report.get('status')}")
        if case in reports:
            raise SystemExit(f"{case}: more than one report")
        reports[case] = (report, path.with_suffix(".tar.gz"))
    commits = {r["compiler_commit"] for r, _ in reports.values()}
    expected = {f"{v}--{b}--{a}" for v in VARIANTS for a, b in CONFIGS if (a, b) not in pending}
    if set(reports) != expected or len(commits) != 1:
        raise SystemExit(f"Need every main case outside --pending from one commit; missing "
                         f"{sorted(expected - set(reports))}, commits {sorted(commits)}")
    return reports, commits.pop()


def build_root(dataset, reports, root):
    root.mkdir(parents=True)
    for entry in dataset.iterdir():
        if entry.name != "MinCut":
            (root / entry.name).symlink_to(entry)
    (root / "MinCut").mkdir()
    for entry in (dataset / "MinCut").iterdir():
        if entry.name not in VARIANTS:
            (root / "MinCut" / entry.name).symlink_to(entry)
    for case, (report, artifact) in reports.items():
        variant, bench, arch = case.split("--")
        name = f"{bench}-{ARCH_DIRS[arch]}"
        source, target = dataset / "MinCut" / variant / name, root / "MinCut" / variant / name
        target.mkdir(parents=True)
        for entry in source.iterdir():
            if entry.name not in REPLACED:
                (target / entry.name).symlink_to(entry)
        with tarfile.open(artifact) as tar:
            for member in ("schedule.json", "results.json", "resource_capacity_epochs.json"):
                data = tar.extractfile(member).read()
                (target / f"{member}.gz").write_bytes(gzip.compress(data, mtime=0))
        results = json.loads(gzip.decompress((target / "results.json.gz").read_bytes()))
        if results["num_state_teleportations"] != report["raw"]["num_state_teleportations"]:
            raise SystemExit(f"{case}: artifact disagrees with its worker report")
    for variant in VARIANTS:
        for entry in (dataset / "MinCut" / variant).iterdir():
            target = root / "MinCut" / variant / entry.name
            if not target.exists():
                target.symlink_to(entry)


def extra_opt(base, cache, runs, historical):
    def one(rel):
        schedule = base / rel / "schedule.json.gz"
        out = cache / rel / "extra_opt.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(ROOT / "scripts/apply_extra_opt.py"), "--schedule", str(schedule),
               "--arch", rel.name.rsplit("-", 2)[-2] + "-" + rel.name.rsplit("-", 1)[-1], "--out", str(out)]
        if historical:
            cmd.append("--historical-replay")
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        return rel, json.loads(out.read_text())
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        return dict(pool.map(one, runs))


def run_tables(base, cache, out):
    out.mkdir(parents=True)
    env = {**os.environ, "RESULTS_BASE": str(base), "BENCH_DIR": str(base / "bench"),
           "EXTRA_OPT_CACHE": str(cache), "PYTHONPATH": str(ROOT / "src"), "MPLBACKEND": "Agg"}
    for section, name in TABLES.values():
        subprocess.run([sys.executable, str(ROOT / "data_generator" / section / f"{name}.py")],
                       check=True, capture_output=True, env=env)
        shutil.copy(ROOT / "data_generator/output" / section / f"{name}.csv", out / f"{name}.csv")


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def compare(published, rerouted, pending, out):
    rows = []
    for key, (_, name) in TABLES.items():
        old, new = read_csv(published / f"{name}.csv"), read_csv(rerouted / f"{name}.csv")
        assert len(old) == len(new)
        for a, b in zip(old, new):
            label = {k: a[k] for k in a if not k.endswith(("seconds", "T_eff", "speedup"))}
            assert label == {k: b[k] for k in label}
            if (a.get("arch", "F120"), a["bench"]) in pending:
                rows.extend(dict(table=key, row=" ".join(label.values()), metric=metric, published=a[metric],
                                 rerouted=NOT_READY, delta_percent="") for metric in a if metric not in label)
                continue
            if a == b:
                continue
            for metric in [k for k in a if k not in label]:
                if a[metric] != b[metric]:
                    x, y = float(a[metric]), float(b[metric])
                    rows.append(dict(table=key, row=" ".join(label.values()), metric=metric,
                                     published=a[metric], rerouted=b[metric],
                                     delta_percent=f"{100 * (y - x) / x:.2f}" if x else ""))
    with (out / "comparison.tsv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def geomean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


def main_rows(directory):
    cells = defaultdict(dict)
    for row in read_csv(directory / "table5_mapper_comparison_2x2.csv"):
        if row["mapper"] == "ILP":
            cells[("F120", row["bench"])][row["variant"]] = row
    for row in read_csv(directory / "table6_main_2x3_3x3.csv"):
        cells[(row["arch"], row["bench"])][row["variant"]] = row
    return cells


def summarize(published, rerouted, pending, out):
    """IRIS (EES on) against QuComm per main configuration, and the geometric mean over ready configurations."""
    old, new = main_rows(published), main_rows(rerouted)
    fields = ("arch", "bench", "metric", "published_QuComm", "published_IRIS", "published_ratio",
              "rerouted_QuComm", "rerouted_IRIS", "rerouted_ratio")
    rows, ratios = [], defaultdict(list)
    for config in CONFIGS:
        for metric in ("T_eff", "L_seconds"):
            row = dict(zip(fields, (*config, metric)))
            for side, cells in (("published", old), ("rerouted", new)):
                if side == "rerouted" and config in pending:
                    row.update({f"{side}_{k}": NOT_READY for k in ("QuComm", "IRIS", "ratio")})
                    continue
                qucomm, iris = float(cells[config]["QuComm"][metric]), float(cells[config]["IRIS-opt1"][metric])
                ratio = iris / qucomm
                row.update({f"{side}_QuComm": cells[config]["QuComm"][metric],
                            f"{side}_IRIS": cells[config]["IRIS-opt1"][metric], f"{side}_ratio": f"{ratio:.4f}"})
                if config not in pending:
                    ratios[(side, metric)].append(ratio)
            rows.append(row)
    with (out / "performance.tsv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = ["metric\tpublished_IRIS/QuComm\trerouted_IRIS/QuComm\tconfigs\tnot_ready"]
    for metric in ("T_eff", "L_seconds"):
        a, b = ratios[("published", metric)], ratios[("rerouted", metric)]
        lines.append(f"{metric}\t{geomean(a):.4f}\t{geomean(b):.4f}\t{len(b)}\t"
                     f"{' '.join(f'{bench}-{arch}' for arch, bench in sorted(pending)) or 'none'}")
    (out / "summary.tsv").write_text("\n".join(lines) + "\n")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--reroutes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pending", nargs="*", default=[], metavar="BENCH--ARCH",
                    help="main configurations whose reroutes are not finished, for example qv_n240--F240")
    args = ap.parse_args()
    pending = {tuple(reversed(p.split("--"))) for p in args.pending}
    if not pending <= set(CONFIGS):
        raise SystemExit(f"unknown --pending configuration in {args.pending}")
    dataset, out = args.dataset.resolve(), args.out.resolve()
    if out.exists():
        raise SystemExit(f"{out} exists; choose a fresh output directory")
    reports, commit = load_reroutes(args.reroutes.resolve(), pending)
    build_root(dataset, reports, out / "root")
    iris = [Path("MinCut/IRIS") / f"{b}-{ARCH_DIRS[a]}" for v, b, a in (c.split("--") for c in reports) if v == "IRIS"]
    held = [Path("MinCut/IRIS") / f"{b}-{ARCH_DIRS[a]}" for a, b in sorted(pending)]
    others = [p.parent.relative_to(dataset) for m in ("GCP-E", "sOEE", "WBCP")
              for p in (dataset / m / "IRIS").glob("*-S40C5-2x2/schedule.json.gz")]
    shared = extra_opt(dataset, out / "cache-published", iris + held + others, historical=True)
    for rel in others + held:
        target = out / "cache-rerouted" / rel / "extra_opt.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(out / "cache-published" / rel / "extra_opt.json", target)
    strict = extra_opt(out / "root", out / "cache-rerouted", iris, historical=False)
    run_tables(dataset, out / "cache-published", out / "published")
    run_tables(out / "root", out / "cache-rerouted", out / "rerouted")
    changed = compare(out / "published", out / "rerouted", pending, out)
    lines = summarize(out / "published", out / "rerouted", pending, out)
    with (out / "ees-selection.tsv").open("w") as f:
        f.write("run\tpublished_selection\tpublished_errors\trerouted_selection\trerouted_violations\n")
        for rel in sorted(iris + held):
            errors = sorted({v.split(":")[0] + (" location" if "tracked on" in v else " channel")
                             for v in shared[rel].get("violations") or []})
            rerouted = (f"{strict[rel]['selection']}\t{len(strict[rel].get('violations') or [])}" if rel in strict
                        else f"{NOT_READY}\t{NOT_READY}")
            f.write(f"{rel.name}\t{shared[rel]['selection']}\t{', '.join(errors) or 'none'}\t{rerouted}\n")
    print(f"compiler {commit}: {len(changed)} changed or not-ready table cells")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
