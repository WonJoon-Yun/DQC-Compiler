#!/usr/bin/env python3
"""Unit test for EES post-condition assertions.

Verifies that:
  - ``pipeline_optimization`` (the main EES pass) accepts a valid input
    and does not raise the post-condition AssertionError.
  - ``qucomm_parallel_schedule`` likewise validates its output.
  - Injecting an obvious violation (qubit collision) into the post-condition
    helper triggers a violation as expected (sanity check on the verifier).
"""
from __future__ import annotations

import sys
from pathlib import Path

CHIPLET_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = CHIPLET_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from router.optim.early_execution import (  # noqa: E402
    _verify_placed_pipeline,
    pipeline_optimization,
    qucomm_parallel_schedule,
)


def _row_relocate(t, q, src, dst, bid=0, dur=0.01):
    return {"Time": t, "CNOT": False, "SIdx": q, "TIdx": q,
            "SPos": src, "SNextPos": dst, "TPos": src, "TNextPos": src,
            "BlockID": bid, "_dur": dur, "_optype": "RELOCATE"}


def _row_local_cnot(t, qa, qb, pos, bid=0, dur=0.001):
    return {"Time": t, "CNOT": True, "SIdx": qa, "TIdx": qb,
            "SPos": pos, "SNextPos": pos, "TPos": pos, "TNextPos": pos,
            "BlockID": bid, "_dur": dur, "_optype": "Local CNOT"}


def test_pipeline_optimization_valid_input():
    A, B = (0, 0), (0, 1)
    pipe = [
        _row_relocate(0, 0, A, B, bid=0),
        _row_local_cnot(1, 0, 1, B, bid=0),
        _row_relocate(2, 2, A, B, bid=1),
        _row_local_cnot(3, 2, 3, B, bid=1),
    ]
    init_ch = {(A, B): 0, (B, A): 0}
    windows, early = pipeline_optimization(
        pipe, init_ch, min_comm_value=-100, max_comm_value=100,
        debug=False,
    )
    assert windows, "pipeline_optimization returned no windows"
    print(f"  pipeline_optimization OK: {len(windows)} windows, {len(early)} hosts w/ early ops")


def test_qucomm_parallel_schedule_valid_input():
    A, B = (0, 0), (0, 1)
    pipe = [
        _row_relocate(0, 0, A, B, bid=0),
        _row_local_cnot(1, 0, 1, B, bid=0),
        _row_relocate(2, 2, A, B, bid=1),
        _row_local_cnot(3, 2, 3, B, bid=1),
    ]
    init_ch = {(A, B): 0, (B, A): 0}
    placed = qucomm_parallel_schedule(
        pipe, init_ch, min_comm_value=-100, max_comm_value=100,
        link_epr_capacity=5, debug=False,
    )
    assert placed, "qucomm_parallel_schedule returned empty"
    print(f"  qucomm_parallel_schedule OK: {len(placed)} rows")


def test_verifier_catches_injected_violation():
    A, B = (0, 0), (0, 1)
    bad = [
        _row_relocate(0, 0, A, B),
        _row_local_cnot(0, 0, 1, A),
    ]
    violations = _verify_placed_pipeline(
        bad, {(A, B): 0, (B, A): 0}, -100, 100,
    )
    assert any(v.startswith("(a)qubit-collision") for v in violations), \
        f"verifier missed injected qubit collision; got {violations}"
    print(f"  verifier sanity OK: caught {len(violations)} violation(s)")


def test_verifier_catches_link_cap():
    A, B = (0, 0), (0, 1)
    # 6 simultaneous moves on link {A,B} at t=0 -> exceed cap=5
    bad = [_row_relocate(0, q, A, B) for q in range(6)]
    init_ch = {(A, B): 0, (B, A): 0}
    violations = _verify_placed_pipeline(
        bad, init_ch, -100, 100, link_epr_capacity=5,
    )
    assert any(v.startswith("(e)link-cap") for v in violations), \
        f"verifier missed link-cap violation; got {violations}"
    print(f"  link-cap sanity OK: caught link-cap violation")


if __name__ == "__main__":
    print("Running EES post-condition tests...")
    test_pipeline_optimization_valid_input()
    test_qucomm_parallel_schedule_valid_input()
    test_verifier_catches_injected_violation()
    test_verifier_catches_link_cap()
    print("ALL TESTS PASSED")
