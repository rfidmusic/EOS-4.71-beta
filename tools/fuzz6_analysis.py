#!/usr/bin/env python3
"""Analysis of the measured Fuzz6 grid (menu 21-26, switch 0) against the original 4 Pole LP+Fuzz.

usage: fuzz6_analysis.py FUZZ6_RUN LPFUZZ_RUN [OUT.png] [--fuzzob]   (--fuzzob: the FuzzOB set, menu 21-25)   (merged runs, e.g. recordings/fz6_merged recordings/fr_fix_merged)
Same measures as lpfuzz_analysis.py (level, rise, peak, thd, bass, onset; THD from 63 Hz up: the sweep-start bands
are unreliable when the sweep was played off-rate), per variant, on the Fuzz6 grid
(cutoff 0..240, Q 0..127). The original LP+Fuzz is read at the same cutoffs / Q values ('lpfuzz' tags).
Writes OUT.png (rise and THD heatmaps per variant) and OUT.json.
"""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lpfuzz_analysis as L       # noqa: E402

CUTS = [0, 32, 64, 96, 128, 160, 192, 240]
QS = [0, 16, 32, 48, 64, 80, 96, 112, 127]
VARIANTS = [('lpfuzz', 'original 4 Pole LP+Fuzz'), ('fz2p', '2 Pole LP+Fuzz'), ('fz4p', '4 Pole LP+Fuzz'),
            ('fz6p', '6 Pole LP+Fuzz'), ('fzhp2', '2nd Ord HP+Fuzz'), ('fzbp2', '2nd Ord BP+Fuzz'),
            ('fzcbp', 'Contrary BP+Fuzz')]
FUZZOB = [('lpfuzz', 'original 4 Pole LP+Fuzz'), ('fob2p', '2 Pole LP+Fuzz'), ('fob4p', '4 Pole LP+Fuzz (orig. code)'),
          ('fobhp2', '2nd Ord HP+Fuzz'), ('fobbp2', '2nd Ord BP+Fuzz'), ('fobcbp', 'Contrary BP+Fuzz')]


def analyse(run, name):
    d = json.load(open(os.path.join(run, 'bands.json')))
    log = {x['tag']: x for x in json.load(open(os.path.join(run, 'log.json')))}
    G = {k: np.full((len(CUTS), len(QS)), np.nan) for k in ('level', 'peak', 'thd', 'bass')}
    for i, c in enumerate(CUTS):
        for j, q in enumerate(QS):
            b = d.get(f'{name}_c{c}_q{q}')
            if b is None:
                continue
            ok = [x for x in b if L.finite(x['level'])]
            pb = [x['level'] for x in ok if 101 <= x['f'] <= 320]
            top = max(x['level'] for x in ok)
            G['level'][i, j] = np.median(pb) if pb else np.nan
            G['peak'][i, j] = log.get(f'{name}_c{c}_q{q}', {}).get('peak_dbfs', np.nan)
            th = [x['thd'] for x in ok if x['f'] >= 63 and x['level'] > top - 20 and L.finite(x['thd'])]
            G['thd'][i, j] = max(th) if th else np.nan
            l50 = next((x['level'] for x in b if x['f'] == 50), np.nan)
            l101 = next((x['level'] for x in b if x['f'] == 101), np.nan)
            G['bass'][i, j] = l50 - l101
    # loudest band level, for HP/BP where the 101-320 Hz passband is not the passband
    G['top'] = np.full_like(G['level'], np.nan)
    for i, c in enumerate(CUTS):
        for j, q in enumerate(QS):
            b = d.get(f'{name}_c{c}_q{q}')
            if b:
                G['top'][i, j] = max(x['level'] for x in b if L.finite(x['level']))
    G['rise'] = G['top'] - G['top'][:, :1]
    return G


def main():
    global VARIANTS
    if '--fuzzob' in sys.argv:
        sys.argv.remove('--fuzzob')
        VARIANTS = FUZZOB
    fz, lp = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(fz, 'fuzz6_analysis.png')
    R = {n: analyse(lp if n == 'lpfuzz' else fz, n) for n, _ in VARIANTS}
    ceil = np.nanmax([np.nanmax(R[n]['peak']) for n, _ in VARIANTS])
    L.CUTS, L.QS = CUTS, QS
    fig, ax = plt.subplots(2, len(VARIANTS), figsize=(4.2 * len(VARIANTS), 9), facecolor=L.SURF)
    fig.suptitle(('FuzzOB' if VARIANTS is FUZZOB else 'Fuzz6 (switch 0)') + ' on the E4 vs the original 4 Pole LP+Fuzz: loudest-band rise from Q 0, and worst THD',
                 color=L.INK, fontsize=12, fontweight='bold')
    for k, (n, title) in enumerate(VARIANTS):
        L.heat(ax[0, k], R[n]['rise'], title, 'Blues', 0, 45, '{:.0f}', 'dB')
        L.heat(ax[1, k], R[n]['thd'], 'THD', 'magma', -70, 0, '{:.0f}', 'dB')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out, dpi=90, facecolor=L.SURF)
    print(out, f'clip ceiling {ceil:.1f} dBFS (highest take peak)')
    print('per variant and cutoff: loudest band at Q0 (dB re ref), max rise, Q where peak first within 1 dB of the ceiling,'
          ' fuzz onset Q (THD > -30), THD at Q127, peak at Q127')
    for n, title in VARIANTS:
        G = R[n]
        print(f'{title}')
        for i, c in enumerate(CUTS):
            at = next((QS[j] for j in range(len(QS)) if G['peak'][i, j] >= ceil - 1), None)
            on = next((QS[j] for j in range(len(QS)) if G['thd'][i, j] > -30), None)
            print(f'  cut {c:3d}: Q0 {G["top"][i, 0]:+6.1f}  rise {np.nanmax(G["rise"][i]):+5.1f}  clip from Q {str(at):>4}'
                  f'  fuzz from Q {str(on):>4}  THD127 {G["thd"][i, -1]:+6.1f}  peak127 {G["peak"][i, -1]:+6.1f}')
    json.dump({n: {k: v.tolist() for k, v in R[n].items()} for n, _ in VARIANTS} | {'ceiling': ceil, 'cuts': CUTS, 'qs': QS},
              open(os.path.splitext(out)[0] + '.json', 'w'))


if __name__ == '__main__':
    main()
