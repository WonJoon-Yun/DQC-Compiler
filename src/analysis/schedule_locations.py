"""Replay physical atom locations in emitted and post-processed flat-pool schedules."""
import gzip
import json
from types import SimpleNamespace

from hardware import Hardware


def read_schedule(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as source:
        return json.load(source)


def initial_locations(schedule):
    if "initial_atom_positions" in schedule:
        return {int(atom): tuple(chip) for atom, chip in schedule["initial_atom_positions"].items()}
    # Version 1 archives name physical atoms by their index in the flat pool.
    config = schedule.get("args_snapshot") or {}
    keys = ("numchipletsx", "numchipletsy", "system_qubits_per_chip", "num_communication_per_link")
    if any(config.get(key) is None for key in keys):
        raise ValueError("Cannot recover initial atom locations without flat-pool geometry or initial_atom_positions")
    hardware = Hardware(SimpleNamespace(**{key: int(config[key]) for key in keys}))
    return {atom: tuple(slot[:2]) for atom, slot in hardware.qubit_idx_to_physical_idx.items()}


def pipeline_rows(ops):
    starts = sorted({op["original_start_time"] for op in ops})
    cycle = {start: i for i, start in enumerate(starts)}
    rows, chips = [], set()
    for op in ops:
        kind = op["optype"]
        src, dst = tuple(op["pos0"]), tuple(op["pos1"])
        chips.update((src, dst))
        gate = kind in ("Local CNOT", "Re-CNOT")
        if not gate and kind != "RELOCATE":
            if kind != "Transfer" or src != dst:
                raise ValueError(f"Unsupported flat-pool schedule operation {kind!r} on {src}, {dst}")
        atom = int(op["atom0"])
        if kind == "RELOCATE" and atom != int(op["atom1"]):
            raise ValueError(f"RELOCATE names two different physical atoms: {atom}, {op['atom1']}")
        start = op["original_start_time"]
        duration = float(op.get("original_duration", 0))
        rows.append({
            "Time": cycle[start], "CNOT": gate, "BlockID": int(op["layer_id"]),
            "SIdx": atom, "TIdx": int(op["atom1"]) if gate else atom,
            "SPos": src, "SNextPos": src if gate else dst,
            "TPos": dst if gate else src, "TNextPos": dst if gate else src,
            "_optype": kind, "_dur": duration, "_start": start,
            "_end": op.get("original_end_time", start + duration),
        })
    return rows, {(a, b): 0 for a in chips for b in chips if a != b}


def validate_locations(rows, initial, *, original_times=False):
    """Reject the first unexplained position or overlapping use of a physical atom."""
    positions = dict(initial)
    available = {}
    for row in sorted(rows, key=lambda r: r["Time"]):
        start = row["_start"] if original_times else row["Time"]
        end = row["_end"] if original_times else start + 1
        atom = row["SIdx"]
        operands = [(atom, row["SPos"])]
        if row["CNOT"]:
            operands.append((row["TIdx"], row["TPos"]))
        for qubit, chip in operands:
            label = f"block {row['BlockID']}, time {start}, {row['_optype']}, atom {qubit}"
            if qubit not in positions:
                raise ValueError(f"{label}: missing initial position")
            if positions[qubit] != chip:
                raise ValueError(f"{label}: scheduled on {chip}, tracked on {positions[qubit]}")
            if qubit in available and start < available[qubit] - 1e-12:
                raise ValueError(f"{label}: previous operation ends at {available[qubit]}")
            available[qubit] = end
        if row["_optype"] == "RELOCATE":
            positions[atom] = row["SNextPos"]
