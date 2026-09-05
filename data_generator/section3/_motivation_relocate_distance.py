"""Motivation: distance (in Local CNOTs) between a RELOCATE and the next
RELOCATE that touches an overlapping qubit.

For a non-local CX(q1, q2), the IRIS scheduler emits a RELOCATE that brings
q1 (or q2) to a peer chip so the CX can fire locally. The dependency-relevant
"next RELOCATE" is therefore whichever of q1 or q2 is RELOCATEd first after
this event. We pair-tag each RELOCATE by looking at the next Local CNOT that
involves q1 (its other operand is the partner q2), then count the Local
CNOTs strictly between this RELOCATE and the earlier of (next RELOCATE on
q1, next RELOCATE on q2). RELOCATEs without a successor on either qubit are
skipped (not counted).

Outputs:
  - per-RELOCATE distances CSV (long form)        -> per_pair_<arch>.csv
  - per-benchmark summary CSV                     -> summary.csv
  - markdown table (Benchmark | Mean)             -> summary_mean.md

Usage:
  python motivation_relocate_distance.py \
      --results-root /path/to/results-tree \
      --output-dir /path/to/out/motivation/relocate_distance \
      [--qubit-counts 240] [--routing QuComm] [--mapping-method ILP] \
      [--routing-variant IRIS4]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gc
import glob
import json
import os
import sys
from collections import defaultdict
from statistics import mean, median


def find_schedule_files(results_root: str,
                        routing: str,
                        cost_dir: str,
                        qubit_counts: list[int],
                        mapping_method: str,
                        routing_variant: str) -> list[str]:
    paths = []
    for n in qubit_counts:
        glob_pat = os.path.join(
            results_root, routing, cost_dir,
            f'*_n{n}', mapping_method, routing_variant, '*',
            'Schedule-*.json',
        )
        for p in glob.glob(glob_pat):
            paths.append(p)
    return sorted(paths)


def load_block_stats(schedule_path: str) -> dict:
    """Load aggregate stats from the sibling results JSON. Returns empty
    dict if the file is not found."""
    sched_dir = os.path.dirname(schedule_path)
    cands = sorted(glob.glob(os.path.join(sched_dir, 'results-*.json')))
    if not cands:
        return {}
    with open(cands[0]) as f:
        rd = json.load(f)
    pbm = rd.get('per_block_metrics') or []
    n_blocks_local = sum(1 for b in pbm if (b.get('relocates') or 0) == 0)
    n_blocks_nonlocal = sum(1 for b in pbm if (b.get('relocates') or 0) > 0)
    return {
        'num_blocks': rd.get('num_blocks'),
        'init_avg_block_size': rd.get('init_avg_block_size'),
        'init_min_block_size': rd.get('init_min_block_size'),
        'init_max_block_size': rd.get('init_max_block_size'),
        'num_local_cnots_total': rd.get('num_local_cnots'),
        'num_relocations_total': rd.get('num_relocations'),
        'num_state_teleportations_total': rd.get('num_state_teleportations'),
        'num_recnots_total': rd.get('num_recnots'),
        'num_channel_releases_total': rd.get('num_channel_releases'),
        'num_evictions_total': rd.get('num_evictions'),
        'num_blocks_local': n_blocks_local,
        'num_blocks_nonlocal': n_blocks_nonlocal,
    }


def analyze(path: str):
    with open(path) as f:
        data = json.load(f)
    ops = data['ops']
    n_ops = len(ops)
    optype = [op['optype'] for op in ops]
    a0 = [op['atom0'] for op in ops]
    a1 = [op['atom1'] for op in ops]
    layer = [int(op['layer_id']) for op in ops]

    # Load sibling per_block_metrics for block-level classification.
    sched_dir = os.path.dirname(path)
    res_cands = sorted(glob.glob(os.path.join(sched_dir, 'results-*.json')))
    block_is_local = {}
    if res_cands:
        with open(res_cands[0]) as rf:
            rd = json.load(rf)
        for b in rd.get('per_block_metrics', []):
            block_is_local[b['block_id']] = (b.get('relocates') or 0) == 0

    pref = [0] * (n_ops + 1)
    pref_reloc = [0] * (n_ops + 1)
    pref_cnot_local = [0] * (n_ops + 1)
    pref_cnot_nonlocal = [0] * (n_ops + 1)
    for k, t in enumerate(optype):
        is_cnot = (t == 'Local CNOT')
        pref[k + 1] = pref[k] + (1 if is_cnot else 0)
        pref_reloc[k + 1] = pref_reloc[k] + (1 if t == 'RELOCATE' else 0)
        if is_cnot:
            if block_is_local.get(layer[k], True):
                pref_cnot_local[k + 1] = pref_cnot_local[k] + 1
                pref_cnot_nonlocal[k + 1] = pref_cnot_nonlocal[k]
            else:
                pref_cnot_local[k + 1] = pref_cnot_local[k]
                pref_cnot_nonlocal[k + 1] = pref_cnot_nonlocal[k] + 1
        else:
            pref_cnot_local[k + 1] = pref_cnot_local[k]
            pref_cnot_nonlocal[k + 1] = pref_cnot_nonlocal[k]

    reloc_idx = [i for i, t in enumerate(optype) if t == 'RELOCATE']

    atom_events = defaultdict(list)
    for k, t in enumerate(optype):
        if t == 'RELOCATE':
            atom_events[a0[k]].append((k, 'RELOC'))
        else:
            atom_events[a0[k]].append((k, 'CNOT', a1[k]))
            atom_events[a1[k]].append((k, 'CNOT', a0[k]))
    atom_idx_list = {a: [e[0] for e in evs] for a, evs in atom_events.items()}

    distances = []
    unpaired = 0
    for i in reloc_idx:
        q1 = a0[i]
        evs = atom_events[q1]
        idxs = atom_idx_list[q1]
        pos = bisect.bisect_right(idxs, i)
        partner = None
        next_reloc_q1 = None
        for j in range(pos, len(evs)):
            ev = evs[j]
            if ev[1] == 'CNOT' and partner is None:
                partner = ev[2]
            elif ev[1] == 'RELOC' and next_reloc_q1 is None:
                next_reloc_q1 = ev[0]
            if partner is not None and next_reloc_q1 is not None:
                break
        if partner is None:
            unpaired += 1
            continue
        evs2 = atom_events.get(partner, [])
        idxs2 = atom_idx_list.get(partner, [])
        pos2 = bisect.bisect_right(idxs2, i)
        next_reloc_q2 = None
        for j in range(pos2, len(evs2)):
            if evs2[j][1] == 'RELOC':
                next_reloc_q2 = evs2[j][0]
                break
        candidates = [x for x in (next_reloc_q1, next_reloc_q2) if x is not None]
        if not candidates:
            unpaired += 1
            continue
        j_idx = min(candidates)
        # Distinct local / non-local blocks in (i, j_idx) requires a scan
        # because block ops are NOT contiguous in the schedule (verified for
        # qaoa_fc / qv: thousands of layer_id inversions).
        # We exclude ops belonging to the *self* block (block of op i, the
        # current RELOCATE) and the *future* block (block of op j_idx, the
        # next overlapping RELOCATE) - those blocks contain the endpoints
        # themselves, so counting them as "between" would double-count.
        block_id_self = layer[i]
        block_id_future = layer[j_idx]
        local_blocks = set()
        nonlocal_blocks = set()
        for m in range(i + 1, j_idx):
            bid = layer[m]
            if bid == block_id_self or bid == block_id_future:
                continue
            if block_is_local.get(bid, True):
                local_blocks.add(bid)
            else:
                nonlocal_blocks.add(bid)
        distances.append({
            'reloc_idx': i,
            'q1': q1,
            'q2': partner,
            'next_reloc_idx': j_idx,
            'next_reloc_atom': q1 if j_idx == next_reloc_q1 else partner,
            'cnots_between': pref[j_idx] - pref[i + 1],
            'relocs_between': pref_reloc[j_idx] - pref_reloc[i + 1],
            'local_cnots_between': pref_cnot_local[j_idx] - pref_cnot_local[i + 1],
            'nonlocal_cnots_between':
                pref_cnot_nonlocal[j_idx] - pref_cnot_nonlocal[i + 1],
            'local_blocks_between': len(local_blocks),
            'nonlocal_blocks_between': len(nonlocal_blocks),
        })

    n_cnot = sum(1 for t in optype if t == 'Local CNOT')
    return {
        'total_ops': n_ops,
        'local_cnots': n_cnot,
        'relocates': len(reloc_idx),
        'unpaired': unpaired,
        'distances': distances,
    }


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--results-root', required=True,
                   help='Trial results root, e.g. .../v3_norm_large/260403_01')
    p.add_argument('--output-dir', required=True,
                   help='Where to write CSV / markdown outputs')
    p.add_argument('--routing', default='QuComm')
    p.add_argument('--cost-dir', default='oee_on_p5_t0p0',
                   help='Cost-model subdirectory under <routing>/')
    p.add_argument('--qubit-counts', default='240',
                   help='Comma-separated qubit counts to include')
    p.add_argument('--mapping-method', default='ILP')
    p.add_argument('--routing-variant', default='IRIS4')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    qubit_counts = [int(x) for x in args.qubit_counts.split(',') if x.strip()]
    paths = find_schedule_files(args.results_root,
                                args.routing,
                                args.cost_dir,
                                qubit_counts,
                                args.mapping_method,
                                args.routing_variant)
    if not paths:
        print('No schedule files found.', file=sys.stderr)
        return 1

    os.makedirs(args.output_dir, exist_ok=True)

    summary_rows = []
    for path in paths:
        parts = path.split('/')
        bench = parts[-5]
        arch = parts[-2]
        result = analyze(path)
        block_stats = load_block_stats(path)
        d = [r['cnots_between'] for r in result['distances']]
        d_reloc = [r['relocs_between'] for r in result['distances']]
        avg_bs = block_stats.get('init_avg_block_size')
        base = {
            'benchmark': bench, 'arch': arch,
            'total_ops': result['total_ops'],
            'local_cnots': result['local_cnots'],
            'relocates': result['relocates'],
            'num_blocks': block_stats.get('num_blocks'),
            'init_avg_block_size': avg_bs,
            'init_min_block_size': block_stats.get('init_min_block_size'),
            'init_max_block_size': block_stats.get('init_max_block_size'),
            'num_local_cnots_total': block_stats.get('num_local_cnots_total'),
            'num_relocations_total': block_stats.get('num_relocations_total'),
            'num_state_teleportations_total': block_stats.get('num_state_teleportations_total'),
            'num_recnots_total': block_stats.get('num_recnots_total'),
            'num_channel_releases_total': block_stats.get('num_channel_releases_total'),
            'num_evictions_total': block_stats.get('num_evictions_total'),
            'num_blocks_local': block_stats.get('num_blocks_local'),
            'num_blocks_nonlocal': block_stats.get('num_blocks_nonlocal'),
        }
        if d:
            mean_dist = mean(d)
            mean_relocs = mean(d_reloc)
            d_lc  = [r['local_cnots_between']     for r in result['distances']]
            d_nlc = [r['nonlocal_cnots_between']  for r in result['distances']]
            d_lb  = [r['local_blocks_between']    for r in result['distances']]
            d_nlb = [r['nonlocal_blocks_between'] for r in result['distances']]
            row = {**base,
                'pairs': len(d), 'unpaired': result['unpaired'],
                'mean': mean_dist, 'median': median(d), 'max': max(d),
                'mean_relocs_between': mean_relocs,
                'mean_local_cnots_between': mean(d_lc),
                'mean_nonlocal_cnots_between': mean(d_nlc),
                'mean_local_blocks_between': mean(d_lb),
                'mean_nonlocal_blocks_between': mean(d_nlb),
                'mean_distance_in_blocks': (mean_dist / avg_bs
                                            if avg_bs else None),
                'pct_le5': sum(1 for c in d if c <= 5) / len(d) * 100,
                'pct_le20': sum(1 for c in d if c <= 20) / len(d) * 100,
                'pct_le50': sum(1 for c in d if c <= 50) / len(d) * 100,
            }
        else:
            row = {**base,
                'pairs': 0, 'unpaired': result['unpaired'],
                'mean': None, 'median': None, 'max': None,
                'mean_relocs_between': None,
                'mean_local_cnots_between': None,
                'mean_nonlocal_cnots_between': None,
                'mean_local_blocks_between': None,
                'mean_nonlocal_blocks_between': None,
                'mean_distance_in_blocks': None,
                'pct_le5': None, 'pct_le20': None, 'pct_le50': None,
            }
        summary_rows.append(row)

        per_pair_path = os.path.join(args.output_dir, f'per_pair_{bench}_{arch}.csv')
        with open(per_pair_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['reloc_idx', 'q1', 'q2', 'next_reloc_idx',
                        'next_reloc_atom', 'cnots_between',
                        'relocs_between', 'local_cnots_between',
                        'nonlocal_cnots_between',
                        'local_blocks_between', 'nonlocal_blocks_between'])
            for r in result['distances']:
                w.writerow([r['reloc_idx'], r['q1'], r['q2'],
                            r['next_reloc_idx'], r['next_reloc_atom'],
                            r['cnots_between'], r['relocs_between'],
                            r['local_cnots_between'],
                            r['nonlocal_cnots_between'],
                            r['local_blocks_between'],
                            r['nonlocal_blocks_between']])
        print(f'  wrote {per_pair_path}  ({len(d)} pairs)')
        gc.collect()

    summary_path = os.path.join(args.output_dir, 'summary.csv')
    fieldnames = ['benchmark', 'arch', 'total_ops', 'local_cnots',
                  'relocates', 'num_blocks',
                  'init_avg_block_size', 'init_min_block_size', 'init_max_block_size',
                  'num_local_cnots_total', 'num_relocations_total',
                  'num_state_teleportations_total', 'num_recnots_total',
                  'num_channel_releases_total', 'num_evictions_total',
                  'num_blocks_local', 'num_blocks_nonlocal',
                  'pairs', 'unpaired',
                  'mean', 'median', 'max',
                  'mean_relocs_between', 'mean_distance_in_blocks',
                  'mean_local_cnots_between', 'mean_nonlocal_cnots_between',
                  'mean_local_blocks_between', 'mean_nonlocal_blocks_between',
                  'pct_le5', 'pct_le20', 'pct_le50']
    with open(summary_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in summary_rows:
            w.writerow({k: ('' if row[k] is None
                            else (f'{row[k]:.2f}' if isinstance(row[k], float)
                                  else row[k]))
                        for k in fieldnames})
    print(f'wrote {summary_path}')

    md_path = os.path.join(args.output_dir, 'summary_mean.md')
    with open(md_path, 'w') as f:
        f.write('## Mean CNOT Distance to Next Overlapping RELOCATE & Avg. Block Size '
                f'({args.routing}/{args.routing_variant}, '
                f'n={",".join(map(str, qubit_counts))})\n\n')
        f.write('| Benchmark | Mean Distance | Avg. Block Size |\n')
        f.write('|---|---:|---:|\n')
        for row in summary_rows:
            mean_str = '-' if row['mean'] is None else f'{row["mean"]:.1f}'
            bs = row.get('init_avg_block_size')
            bs_str = '-' if bs is None else f'{bs:.2f}'
            f.write(f'| {row["benchmark"]} | {mean_str} | {bs_str} |\n')
    print(f'wrote {md_path}')

    full_md_path = os.path.join(args.output_dir, 'summary_full.md')
    with open(full_md_path, 'w') as f:
        f.write('# Full Per-Benchmark Statistics '
                f'({args.routing}/{args.routing_variant}, '
                f'n={",".join(map(str, qubit_counts))})\n\n')
        f.write('## Glossary (used in both tables)\n\n')
        f.write('- **op-index**: position of an op in `Schedule.json` (0-indexed).\n')
        f.write('- **`Local CNOT`** / **`RELOCATE`**: the two `optype` values that appear in the schedule.\n')
        f.write('- **block / `block_id`**: every op carries `layer_id` (a string); `int(layer_id)` is the `block_id` in `per_block_metrics`. (Verified by invariant C7.)\n')
        f.write('- **local block**: a block whose `per_block_metrics[bid].relocates == 0` (executes entirely on one chip).\n')
        f.write('- **non-local block**: a block whose `relocates > 0` (required at least one RELOCATE).\n')
        f.write('- **(i, j) pair**: for each RELOCATE op at index `i`, let `q1=atom0[i]`, let `q2` be the other operand of the next `Local CNOT` (after `i`) that involves `q1`, and let `j = min(next-RELOCATE-on-q1, next-RELOCATE-on-q2)`. RELOCATEs without such a `j` are dropped (`unpaired`).\n')
        f.write('- **between**: strictly between op-indices `i` and `j` (exclusive on both ends).\n\n')
        f.write('All numbers are computed only from `Schedule.json` and `results.json`; ten cross-check invariants (C1..C10) are verified before this table is emitted (see `METHODOLOGY.md` and `verification_log.txt`).\n\n')

        f.write('## Table 1 - Whole-program totals (one row per benchmark)\n\n')
        f.write('| # | Column | Definition | Source |\n')
        f.write('|---|---|---|---|\n')
        f.write('| 1 | Avg. Block Size | mean number of CXs per block in the source program | `results.init_avg_block_size` |\n')
        f.write('| 2 | #Local CNOTs | number of ops in the schedule with `optype=="Local CNOT"` | `results.num_local_cnots` (=== schedule scan, C1) |\n')
        f.write('| 3 | #RELOCATEs | number of ops in the schedule with `optype=="RELOCATE"` (per-hop entries) | `results.num_relocations` (=== schedule scan, C2; === Σ per-block.relocates, C3) |\n')
        f.write('| 4 | #EPR releases | number of entanglement-channel teardowns | `results.num_channel_releases` (=== Σ per-block.releases, C4) |\n')
        f.write('| 5 | #Local blocks | count of blocks with `per_block_metrics[bid].relocates == 0` | `per_block_metrics` |\n')
        f.write('| 6 | #Non-local blocks | count of blocks with `relocates > 0` | `per_block_metrics` (1 + 2 + ... covered fully, C10) |\n\n')
        f.write('| Benchmark | Avg. Block Size | #Local CNOTs | #RELOCATEs | #EPR releases | #Local blocks | #Non-local blocks |\n')
        f.write('|---|---:|---:|---:|---:|---:|---:|\n')
        for row in summary_rows:
            def cell(v, fmt='{}'):
                return '-' if v is None else fmt.format(v)
            f.write(
                f'| {row["benchmark"]} '
                f'| {cell(row.get("init_avg_block_size"), "{:.2f}")} '
                f'| {cell(row.get("num_local_cnots_total"))} '
                f'| {cell(row.get("num_relocations_total"))} '
                f'| {cell(row.get("num_channel_releases_total"))} '
                f'| {cell(row.get("num_blocks_local"))} '
                f'| {cell(row.get("num_blocks_nonlocal"))} |\n'
            )

        f.write('\n## Table 2 - Per-pair averages BETWEEN a RELOCATE and the next overlapping RELOCATE\n\n')
        f.write('Every average below is taken over the **same set of paired (i, j) samples** for the benchmark.\n\n')
        f.write('| # | Column | Definition |\n')
        f.write('|---|---|---|\n')
        f.write('| A | pairs | number of (i, j) samples (RELOCATEs that produced a paired follow-up) |\n')
        f.write('| B | Avg #operations | mean over pairs of: total ops in `(i, j)` (`Local CNOT` + `RELOCATE`) |\n')
        f.write('| C | Avg #teleportations | mean over pairs of: # `RELOCATE` ops in `(i, j)` (each per-hop entry is one state teleportation) |\n')
        f.write('| D | Avg #local CNOTs | mean over pairs of: # `Local CNOT` ops in `(i, j)` |\n')
        f.write('| E | Avg #local blocks | mean over pairs of: # distinct **local** block_ids touched by any op in `(i, j)` |\n')
        f.write('| F | Avg #non-local blocks | mean over pairs of: # distinct **non-local** block_ids touched by any op in `(i, j)` |\n\n')
        f.write('**Op-count identity.** B = C + D for every pair by construction (every op is either a RELOCATE or a Local CNOT; rounded benchmark means may differ by ≤ 0.1).\n\n')
        f.write('**Block counts vs op counts.** E + F is a *distinct-block* count: a block is counted whenever any single op of it lies in `(i, j)`. Block ops are interleaved in the schedule (e.g., qaoa_fc has 8,586 `layer_id` inversions, qv has 11,827), so a gap that contains only a few ops of many different blocks pushes E + F up. There is no clean closed-form for E + F in terms of B and `Avg. Block Size` - the two are genuinely different quantities and should be read independently.\n\n')
        f.write('| Benchmark | A: pairs | B: #operations | C: #teleportations | D: #local CNOTs | E: #local blocks | F: #non-local blocks |\n')
        f.write('|---|---:|---:|---:|---:|---:|---:|\n')
        for row in summary_rows:
            mean_d = row.get("mean")
            mean_r = row.get("mean_relocs_between")
            ops = (mean_d + mean_r) if (mean_d is not None and mean_r is not None) else None
            f.write(
                f'| {row["benchmark"]} '
                f'| {cell(row.get("pairs"))} '
                f'| {cell(ops, "{:.1f}")} '
                f'| {cell(mean_r, "{:.1f}")} '
                f'| {cell(mean_d, "{:.1f}")} '
                f'| {cell(row.get("mean_local_blocks_between"), "{:.1f}")} '
                f'| {cell(row.get("mean_nonlocal_blocks_between"), "{:.1f}")} |\n'
            )

        f.write('\n## Table 3 - Per-pair derived ratios\n\n')
        f.write('All derived from Table 2 columns.\n\n')
        f.write('| # | Column | Formula | Reads as |\n')
        f.write('|---|---|---|---|\n')
        f.write('| G | blocks between same-qubit relocations | `E + F` | total distinct blocks (any kind) touched in `(i, j)` |\n')
        f.write('| H | teleportations / block | `C / G` | average # `RELOCATE` ops per touched block - small when most blocks are local CX work |\n')
        f.write('| I | local block ratio | `E / G` | share of touched blocks that are local-only |\n')
        f.write('| J | teleportations / non-local block | `C / F` | average per-hop entries per non-local block - proxy for multi-hop chain length |\n')
        f.write('| K | #EPR releases (total) | `results.num_channel_releases` | program-wide channel teardowns (Table 1 col 4) |\n')
        f.write('| L | EPR releases / non-local block | `K / #non-local blocks` | rate at which non-local blocks trigger a channel teardown |\n\n')
        f.write('| Benchmark | G: blocks between | H: tport/block | I: local-block ratio | J: tport/non-local block | K: #EPR releases | L: EPR / non-local block |\n')
        f.write('|---|---:|---:|---:|---:|---:|---:|\n')
        # Note: derive G/H/I/J from the same 1-decimal-rounded Table 2 values
        # the table actually displays, so the ratios reproduce by hand from
        # the printed numbers.
        for row in summary_rows:
            e_raw = row.get("mean_local_blocks_between")
            f_raw = row.get("mean_nonlocal_blocks_between")
            c_raw = row.get("mean_relocs_between")
            e = round(e_raw, 1) if e_raw is not None else None
            f_ = round(f_raw, 1) if f_raw is not None else None
            c = round(c_raw, 1) if c_raw is not None else None
            g = (e + f_) if (e is not None and f_ is not None) else None
            h = (c / g) if (c is not None and g not in (None, 0)) else None
            i_ = (e / g * 100) if (e is not None and g not in (None, 0)) else None
            j_ = (c / f_) if (c is not None and f_ not in (None, 0)) else None
            k_ = row.get("num_channel_releases_total")
            nl_blocks = row.get("num_blocks_nonlocal")
            l_ = (k_ / nl_blocks) if (k_ is not None and nl_blocks not in (None, 0)) else None
            f.write(
                f'| {row["benchmark"]} '
                f'| {cell(g, "{:.1f}")} '
                f'| {cell(h, "{:.2f}")} '
                f'| {cell(i_, "{:.1f}%")} '
                f'| {cell(j_, "{:.2f}")} '
                f'| {cell(k_)} '
                f'| {cell(l_, "{:.4f}")} |\n'
            )
    print(f'wrote {full_md_path}')

    print()
    print(f'{"benchmark":<22} {"arch":<10} {"RELOC":>6} {"pairs":>6} '
          f'{"mean":>8} {"med":>5} {"<=50":>6} {"#blocks":>8} {"avgBS":>6}')
    print('-' * 96)
    for row in summary_rows:
        bs = row.get('init_avg_block_size')
        bs_str = '-' if bs is None else f'{bs:.2f}'
        nb = row.get('num_blocks')
        nb_str = '-' if nb is None else f'{nb}'
        if row['mean'] is None:
            print(f'{row["benchmark"]:<22} {row["arch"]:<10} '
                  f'{row["relocates"]:>6} {row["pairs"]:>6} '
                  f'{"-":>8} {"-":>5} {"-":>6} {nb_str:>8} {bs_str:>6}')
        else:
            print(f'{row["benchmark"]:<22} {row["arch"]:<10} '
                  f'{row["relocates"]:>6} {row["pairs"]:>6} '
                  f'{row["mean"]:>8.1f} {row["median"]:>5.0f} '
                  f'{row["pct_le50"]:>5.1f}% {nb_str:>8} {bs_str:>6}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
