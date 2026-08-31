#!/usr/bin/env python3
"""Fig 17: Re-CNOT/RELOCATE cost-ratio (alpha) sensitivity.

Stacked RELOCATE/Re-CNOT bars per alpha, normalized to QuComm at the same
alpha. Data: alpha_latency_table.json from scripts/alpha_retime.py (post-hoc
Re-CNOT rewrite, fires for alpha <= 1.5). x points {0.5, 1.0, 1.5, 1.77, 2.0}.
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import setup_rcparams  # noqa: E402

ALPHAS = [0.5, 1.0, 1.5, 1.77, 2.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--table', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    setup_rcparams(font_size=12)
    table = json.load(open(args.table))

    C = {'Qu_REL': '#FF9A00', 'Qu_RC': '#EEFABD',
         'IR_REL': '#0D47A1', 'IR_RC': '#E3F2FD'}
    (fig, ax) = plt.subplots(figsize=(7.4, 2.9))
    xs = list(range(len(ALPHAS)))
    w = 0.38

    qtot = [table[f'{a}|QuComm']['N_REL'] + table[f'{a}|QuComm']['N_ReCNOT']
            for a in ALPHAS]
    for (off, compiler, c_rel, c_rc, lab) in [
            (-w / 2, 'QuComm', C['Qu_REL'], C['Qu_RC'], 'QuComm'),
            (w / 2, 'IRIS', C['IR_REL'], C['IR_RC'], 'IRIS')]:
        rel = [table[f'{a}|{compiler}']['N_REL'] / t
               for (a, t) in zip(ALPHAS, qtot)]
        rc = [table[f'{a}|{compiler}']['N_ReCNOT'] / t
              for (a, t) in zip(ALPHAS, qtot)]
        ax.bar([x + off for x in xs], rel, width=w, facecolor=c_rel,
               edgecolor='black', linewidth=0.8, zorder=3,
               label=f'{lab} (RELOCATE)')
        ax.bar([x + off for x in xs], rc, bottom=rel, width=w,
               facecolor=c_rc, edgecolor='black', linewidth=0.8, zorder=3,
               label=f'{lab} (Re-CNOT)')
    ax.axhline(1.0, linestyle='--', color='#888888', linewidth=1.2, zorder=2)

    ax.set_xlabel('Relative cost of Re-CNOT to RELOCATE')
    ax.set_ylabel('Teleportation Count\nRelative to QuComm')
    ax.set_xticks(xs)
    ax.set_xticklabels(['0.5', '1', '1.5', '1.77\n(default)', '2'])
    ax.set_ylim(0, 1.55)
    ax.set_yticks([0, 0.5, 1.0])
    ax.set_yticklabels(['0', '0.5', '1'])
    ax.legend(fontsize=10.5, loc='upper center', ncol=2,
              labelspacing=0.25, borderpad=0.35, columnspacing=1.2,
              handlelength=1.2, handletextpad=0.4)

    plt.tight_layout()
    fig.savefig(args.output, bbox_inches='tight', pad_inches=0.05)
    fig.savefig(os.path.splitext(args.output)[0] + '.png',
                bbox_inches='tight', pad_inches=0.05, dpi=600)
    plt.close(fig)
    print(f'{args.output} written')


if __name__ == '__main__':
    main()
