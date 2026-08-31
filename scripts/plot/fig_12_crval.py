#!/usr/bin/env python3
"""Fig 12: C_R estimator validation — grouped bars per scheduling decision,
chosen candidate's estimated (C_R with beta=1) vs realized future cost.
Reads decisions.csv produced by scripts/cr_validation.py. Grayscale-safe.
"""
import argparse
import csv
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--decisions', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    from matplotlib.ticker import MaxNLocator  # noqa: F401
    rows = list(csv.DictReader(open(args.decisions)))

    decisions = []
    seen = {}
    for r in rows:
        key = (r['window'], r['depth'])
        if key not in seen:
            seen[key] = len(decisions)
            decisions.append(None)
        if r['chosen'] == '1':
            decisions[seen[key]] = (float(r['C_R_unweighted']), float(r['realized_R']))
    decisions = [d for d in decisions if d is not None]

    n = len(decisions)
    xs = list(range(n))
    est = [d[0] for d in decisions]
    real = [d[1] for d in decisions]

    setup_rcparams()
    (fig, ax) = plt.subplots(figsize=(5.3, 2.55))
    w = 0.38
    ax.bar([x - w / 2 for x in xs], est, width=w, facecolor=C_QUCOMM,
           edgecolor='black', linewidth=0.8, label='Estimated', zorder=3)
    ax.bar([x + w / 2 for x in xs], real, width=w, facecolor=C_IRIS,
           edgecolor='black', linewidth=0.8, label='Actual', zorder=3)

    ax.set_xlabel('Block ID')
    ax.set_ylabel('Future Teleportation Count', fontsize=11)
    ax.set_xlim(-0.7, n - 0.3)
    ax.set_xticks([0, 5, 10, 15] if n <= 20 else list(range(0, n, 10)))
    top = max(max(est), max(real))
    ax.set_yticks([0, 2, 4, 6, 8] if top <= 9 else [0, 4, 8, 12])
    ax.set_ylim(0, top * 1.15 + 0.5)
    ax.legend(fontsize=11, labelspacing=0.25, borderpad=0.35,
              handlelength=1.4, loc='upper left')

    plt.tight_layout()
    fig.savefig(args.output, bbox_inches='tight', pad_inches=0.05)
    fig.savefig(os.path.splitext(args.output)[0] + '.png',
                bbox_inches='tight', pad_inches=0.05, dpi=600)
    plt.close(fig)
    print(f'{args.output} written; decisions={n}')


if __name__ == '__main__':
    main()
