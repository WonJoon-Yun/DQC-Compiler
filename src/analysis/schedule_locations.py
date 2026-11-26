"""Replay physical atom locations in emitted and post-processed flat-pool schedules."""
from collections import Counter
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


def validate_channels(rows, schedule, *, original_times=False):
    """At a shared timestamp, completed hops return their slots before new reservations."""
    events = []
    link_events = []
    for row in rows:
        src = row["SPos"]
        if row["_optype"] == "RELOCATE":
            dst = row["SNextPos"]
            reservations = [((dst, src), (src, dst), 1)]
        elif row["_optype"] == "Re-CNOT":
            dst = row["TPos"]
            reservations = [(edge, edge, 0) for edge in ((src, dst), (dst, src))]
        else:
            continue
        start = row["_start"] if original_times else row["Time"]
        end = row["_end"] if original_times else start + 1
        if end <= start:
            raise ValueError(f"Invalid channel interval in block {row['BlockID']}")
        link = tuple(sorted((src, dst)))
        link_events.append((start, 1, link, row["BlockID"]))
        link_events.append((end, -1, link, row["BlockID"]))
        for debit, credit, floor in reservations:
            # At equal starts, admit permanent moves before temporary gate reservations.
            events.append((start, 1 if floor else 2, debit, -1, debit, floor, row["BlockID"]))
            events.append((end, 0, credit, 1, debit, -floor, row["BlockID"]))
    if not events:
        return
    recorded = schedule.get("initial_directional_channels")
    if recorded is not None:
        balances = {(tuple(src), tuple(dst)): n for src, dst, n in recorded}
    else:
        # The original buffer designer passed the uniform grid channels through.
        config = schedule.get("args_snapshot") or {}
        nx, ny = config.get("numchipletsx"), config.get("numchipletsy")
        capacity = config.get("num_communication_per_link")
        if capacity is None:
            capacity = config.get("num_communication_qubits")
        if nx is None or ny is None or capacity is None:
            raise ValueError("Cannot recover initial directional channels without capacities and grid geometry")
        balances = {((x, y), (x + dx, y + dy)): capacity for x in range(nx) for y in range(ny)
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < nx and 0 <= y + dy < ny}
    in_flight_moves = Counter()
    for time, phase, edge, delta, debit, move_delta, block in sorted(events):
        if edge not in balances:
            raise ValueError(f"Unknown directional channel {edge} in block {block}")
        in_flight_moves[debit] += move_delta
        balances[edge] += delta
        floor = int(in_flight_moves[edge] > 0)
        if phase and balances[edge] < floor:
            raise ValueError(f"block {block}, time {time}: directional channel {edge} "
                             f"has {balances[edge]} slots, requires at least {floor}")
    pairs = (schedule.get("args_snapshot") or {}).get("num_communication_per_link")
    if pairs is None:
        return
    occupancy = Counter()
    for time, step, link, block in sorted(link_events):
        occupancy[link] += step
        if occupancy[link] > pairs:
            raise ValueError(f"block {block}, time {time}: link {link} carries {occupancy[link]} "
                             f"inter-chip operations, has {pairs} interconnect pairs")
