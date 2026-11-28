"""Tabulate distributed QFT results for the released QASM inputs.

The root uses the scripts/run_*.sh layout: <root>/MinCut/<variant>/qft_n<size>-<arch>/.
The script verifies every schedule, checks that the scheduled two-qubit gates equal the
parser's directed CX count, and runs the IRIS postprocessing step for the IRIS rows.

  python revision/issue2_distributed_qft.py --results <root> --qasm <released bench dir> \
      > revision/issue2-distributed-qft.tsv
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parser import ProgramParser

SIZES = {120: "S40C5-2x2", 180: "S42C5-2x3", 240: "S40C5-3x3"}
VARIANTS = ("QuComm", "IRIS-noEES", "IRIS")
RE_CNOT_WEIGHT = 1.77
FIELDS = ("variant", "benchmark", "parser_cx", "num_local_cnots", "num_gate_teleportations",
          "num_state_teleportations", "T_eff", "raw_ms", "postprocessed_ms", "postprocess_selection")


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


def postprocess(schedule, arch):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "extra_opt.json"
        run([sys.executable, str(ROOT / "scripts/apply_extra_opt.py"),
             "--schedule", str(schedule), "--arch", arch, "--out", str(out)])
        return json.loads(out.read_text())


def rows(root, parser_cx):
    for variant in VARIANTS:
        run([sys.executable, str(ROOT / "tests/verify_extra_opt.py"), "--root", str(root),
             "--variant", variant, "--stop_on_fail"])
        for size, arch in SIZES.items():
            run_dir = root / "MinCut" / variant / f"qft_n{size}-{arch}"
            result = json.loads((run_dir / "results.json").read_text())
            local, remote = result["num_local_cnots"], result["num_gate_teleportations"]
            if local + remote != parser_cx[size]:
                raise SystemExit(f"{run_dir}: {local} + {remote} scheduled gates, parser emits {parser_cx[size]}")
            moves = result["num_state_teleportations"]
            row = dict(variant=variant, benchmark=f"qft_n{size}", parser_cx=parser_cx[size],
                       num_local_cnots=local, num_gate_teleportations=remote, num_state_teleportations=moves,
                       T_eff=f"{moves + RE_CNOT_WEIGHT * remote:.2f}",
                       raw_ms=f"{1000 * result['total_execution_time']:.5f}",
                       postprocessed_ms="", postprocess_selection="")
            if variant == "IRIS":
                extra = postprocess(run_dir / "schedule.json", arch)
                row.update(postprocessed_ms=f"{extra['wall_time_ms_extra']:.5f}",
                           postprocess_selection=extra["selection"])
            yield row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--qasm", type=Path, required=True, help="directory holding qft/qft_n<size>.qasm")
    args = ap.parse_args()
    out = csv.DictWriter(sys.stdout, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    out.writeheader()
    parser_cx = {size: ProgramParser(str(args.qasm / "qft" / f"qft_n{size}.qasm")).num_2q_gates for size in SIZES}
    out.writerows(rows(args.results, parser_cx))


if __name__ == "__main__":
    main()
