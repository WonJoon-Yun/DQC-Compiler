"""Overlap routed blocks only when their directional channel reservations fit."""
from collections import Counter, defaultdict
from itertools import chain


def _channel_events(rows):
    events = defaultdict(list)
    seen = set()
    for row in rows:
        tick = row['Time']
        if row['CNOT']:
            src, dst = row['SPos'], row['TPos']
            key = (tick, row['BlockID'], 'gate', row['SIdx'], row['TIdx'])
            if src != dst and key not in seen:
                events[tick].append(('gate', src, dst))
                seen.add(key)
            continue
        # Several gate rows can describe the same physical atom moving once.
        for side in ('S', 'T'):
            src, dst = row[side + 'Pos'], row[side + 'NextPos']
            key = (tick, row['BlockID'], row[side + 'Idx'], src, dst)
            if src != dst and key not in seen:
                events[tick].append(('move', src, dst))
                seen.add(key)
    return events


def _closing_balances(opening, group, block, delay):
    """Return the closing state, or None if the proposed overlap exhausts a link."""
    balances = opening.copy()
    for tick in sorted(group.keys() | {t + delay for t in block}):
        credits = Counter()
        remote_holds = Counter()
        for kind, src, dst in chain(group.get(tick, ()), block.get(tick - delay, ())):
            if kind == 'move':
                if balances[dst, src] < 2:
                    return None
                balances[dst, src] -= 1
                credits[src, dst] += 1
            else:
                # A remote CNOT holds one slot in each direction for this tick.
                remote_holds[src, dst] += 1
                remote_holds[dst, src] += 1
        for (u, v), count in remote_holds.items():
            # A gate may transiently use the last slot, but a concurrent move
            # debiting that same direction must still leave its reserved unit.
            floor = 1 if credits[v, u] else 0
            if balances[u, v] - count < floor:
                return None
        for edge, count in credits.items():
            balances[edge] += count
    return balances


class ChannelAwareBlockMerger:
    def __init__(self, initial_channels):
        self.groups = []
        self._opening = dict(initial_channels)
        self._closing = self._opening
        self._events = {}
        self._atoms = set()
        self._last_tick = -1

    def append(self, rows, *, allow_overlap=True):
        if not rows:
            return
        atoms = {row[key] for row in rows for key in ('SIdx', 'TIdx')}
        events = _channel_events(rows)
        closing = None
        if allow_overlap and self.groups and self._atoms.isdisjoint(atoms):
            # Test the entire group: a late new move can spend a slot needed
            # by an already placed block later in the same group.
            for delay in range(self._last_tick + 1):
                closing = (_closing_balances(self._opening, self._events, events, delay)
                           if events else self._closing)
                if closing is not None:
                    break

        if closing is None:
            delay = 0
            closing = _closing_balances(self._closing, {}, events, delay)
            if closing is None:
                raise ValueError(f"Routed block {rows[0]['BlockID']} exceeds directional "
                                 "channel capacity even when scheduled alone")
            self._opening = self._closing
            self.groups.append([])
            self._events = defaultdict(list)
            self._atoms = set()
            self._last_tick = -1

        self._closing = closing
        self._atoms.update(atoms)
        for tick, uses in events.items():
            self._events[tick + delay].extend(uses)
        self._last_tick = max(self._last_tick, max(row['Time'] for row in rows) + delay)
        if delay:
            rows = [dict(row, Time=row['Time'] + delay) for row in rows]
        self.groups[-1].extend(rows)
