#!/usr/bin/env python3
"""Fig 18: communication-qubit budget sweep — teleportation count and latency
of IRIS relative to QuComm across comm budgets C=2..6 on a 2x2 DQC.

Reads the dataset-layout tree (<root>/MinCut/<Scheduling>/<bench>-S<S>C<C>-2x2/)
produced by scripts/fig_18.sh — the same layout as the IRIS-dataset, so
--root can also point directly at the dataset (gzipped results are handled).
"""
import argparse
import glob
import gzip
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import setup_rcparams  # noqa: E402

C_QUCOMM = '#FFC107'
C_IRIS = '#00C1D4'


def _load_json(path):
    if path.endswith('.gz'):
        return json.loads(gzip.decompress(open(path, 'rb').read()))
    return json.load(open(path))


def load_budget(root, sched, c, bench, compute):
    arch = f'S{compute + 2 * c}C{c}-2x2'
    run_dir = os.path.join(root, 'MinCut', sched, f'{bench}-{arch}')
    for pat in ('results*.json', 'results*.json.gz', '**/results-*.json'):
        g = sorted(glob.glob(os.path.join(run_dir, pat), recursive=True))
        if g:
            d = _load_json(g[0])
            return (d['num_state_teleportations'] + d['num_gate_teleportations'],
                    d['total_execution_time'] * 1000.0)
    raise SystemExit(f'no results under {run_dir}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True,
                    help='results tree or IRIS-dataset root (dataset layout)')
    ap.add_argument('--bench', required=True)
    ap.add_argument('--compute', type=int, required=True)
    ap.add_argument('--iris-sched', default='IRIS',
                    help='dataset scheduling dir for the IRIS side')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    setup_rcparams()
    plt.rcParams['font.family'] = 'Times New Roman'
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42

    cs = [2, 3, 4, 5, 6]
    qu = [load_budget(args.root, 'QuComm', c, args.bench, args.compute)
          for c in cs]
    ir = [load_budget(args.root, args.iris_sched, c, args.bench, args.compute)
          for c in cs]

    # x = 100 * C / (compute + C): percentage of communication qubits
    xr = [100.0 * c / (args.compute + c) for c in cs]
    rel_teff = [i[0] / q[0] for (i, q) in zip(ir, qu)]
    rel_lat = [i[1] / q[1] for (i, q) in zip(ir, qu)]

    (fig, ax) = plt.subplots(figsize=(5, 2.052))
    ax.axhline(1.0, color='#12372A', linestyle='--', linewidth=1.8,
               alpha=0.9, zorder=2)
    ax.plot(xr, rel_teff, marker='P', markersize=8.5, markeredgewidth=0.8,
            linestyle='-', linewidth=1.5, color='#52057B',
            label=r'$T_{eff}$', zorder=4)
    ax.plot(xr, rel_lat, marker='H', markersize=8.5, markeredgewidth=0.8,
            linestyle='-', linewidth=1.5, color='#FEA82F',
            label='Latency', zorder=4)
    ax.set_xlabel('Percentage of Communication Qubits')
    ax.set_ylabel('Rel. Performance')
    ax.set_yticks([0, 0.5, 1.0])
    ax.set_yticklabels(['0', '0.5', '1'])
    ax.set_ylim(0, 1.3)
    ax.set_xticks([6, 8, 10, 12, 14, 16])
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    ax.legend(loc='upper center', ncol=2, bbox_to_anchor=(0.5, 1.02),
              frameon=False, fontsize=12, handlelength=1.0,
              handletextpad=0.3, columnspacing=0.8, borderaxespad=0.0)

    plt.tight_layout()
    fig.savefig(args.output, bbox_inches='tight', pad_inches=0.05)
    fig.savefig(os.path.splitext(args.output)[0] + '.png',
                bbox_inches='tight', pad_inches=0.05, dpi=600)
    plt.close(fig)
    print(f'{args.output} written;',
          'QuComm Teff', [v[0] for v in qu],
          'IRIS Teff', [v[0] for v in ir])


if __name__ == '__main__':
    main()
