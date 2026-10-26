#!/usr/bin/env python3
"""Analysis of the measured 4 Pole LP+Fuzz grid (one hardware run, 16 cutoffs x 16 Q, 6 s sweep + 20 s retakes).

usage: lpfuzz_analysis.py RUN_DIR [OUT.png]      (RUN_DIR has bands.json and log.json, e.g. recordings/fr_fix_merged)
Per setting:
  level   passband level (median of the 101-320 Hz bands), dB re the session reference
  rise    level minus the same cutoff's Q 0 level
  peak    the take's sample peak, dBFS; ceiling = the highest peak of the run (the chip's clip point)
  thd     worst THD among the bands within 20 dB of the loudest band
  bass    50 Hz band minus the 101 Hz band (drive-stage bass loss)
  onset   per cutoff, the first Q whose worst THD is above -30 dB (audible fuzz)
"""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

CUTS = list(range(0, 256, 16))
QS = [0, 8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 127]
INK, INK2, GRID, SURF = '#1f1f1e', '#5f5e58', '#e4e3de', '#fcfcfb'


def finite(v):
    return v == v and abs(v) < 150


def analyse(run):
    d = json.load(open(os.path.join(run, 'bands.json')))
    log = {x['tag']: x for x in json.load(open(os.path.join(run, 'log.json')))}
    G = {k: np.full((len(CUTS), len(QS)), np.nan) for k in ('level', 'peak', 'thd', 'bass')}
    for i, c in enumerate(CUTS):
        for j, q in enumerate(QS):
            tag = f'lpfuzz_c{c}_q{q}'
            if tag not in d:
                continue
            b = d[tag]
            pb = [x['level'] for x in b if 101 <= x['f'] <= 320 and finite(x['level'])]
            G['level'][i, j] = np.median(pb) if pb else np.nan
            G['peak'][i, j] = log.get(tag, {}).get('peak_dbfs', np.nan)
            lv = [x['level'] for x in b if finite(x['level'])]
            top = max(lv)
            th = [x['thd'] for x in b if finite(x['level']) and x['level'] > top - 20 and finite(x['thd'])]
            G['thd'][i, j] = max(th) if th else np.nan
            l50 = next((x['level'] for x in b if x['f'] == 50), np.nan)
            l101 = next((x['level'] for x in b if x['f'] == 101), np.nan)
            G['bass'][i, j] = l50 - l101
    G['rise'] = G['level'] - G['level'][:, :1]
    ceiling = np.nanmax(G['peak'])
    onset = []
    for i in range(len(CUTS)):
        k = next((j for j in range(len(QS)) if G['thd'][i, j] > -30), None)
        onset.append(QS[k] if k is not None else None)
    return G, ceiling, onset


def heat(ax, M, title, cmap, vmin, vmax, fmt, label):
    im = ax.imshow(M, origin='lower', aspect='auto', cmap=cmap, vmin=vmin, vmax=vmax,
                   extent=(-0.5, len(QS) - 0.5, -0.5, len(CUTS) - 0.5))
    ax.set_xticks(range(len(QS)), QS, fontsize=7)
    ax.set_yticks(range(len(CUTS)), CUTS, fontsize=7)
    ax.set_xlabel('Q (Fuzz)', color=INK2); ax.set_ylabel('cutoff', color=INK2)
    ax.set_title(title, color=INK, fontsize=10, fontweight='bold')
    for i in range(len(CUTS)):
        for j in range(len(QS)):
            if M[i, j] == M[i, j]:
                ax.text(j, i, fmt.format(M[i, j]), ha='center', va='center', fontsize=5.5, color=INK)
    cb = plt.colorbar(im, ax=ax, fraction=0.04)
    cb.set_label(label, color=INK2)
    cb.outline.set_edgecolor(GRID)


def main():
    run = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(run, 'lpfuzz_analysis.png')
    G, ceil, onset = analyse(run)
    fig, ax = plt.subplots(2, 2, figsize=(15, 11), facecolor=SURF)
    fig.suptitle('4 Pole LP+Fuzz, measured on the E4 (6 s sweep, 20 s retakes at cutoff <= 16 / Q >= 64)',
                 color=INK, fontsize=12, fontweight='bold')
    heat(ax[0, 0], G['rise'], 'Passband level rise from Q 0 (101-320 Hz)', 'Blues', 0, 45, '{:.0f}', 'dB')
    heat(ax[0, 1], G['peak'] - ceil, f'Sample peak re the clip ceiling ({ceil:.1f} dBFS)', 'Reds_r', -30, 0, '{:.0f}', 'dB')
    heat(ax[1, 0], G['thd'], 'Worst THD in the loud bands', 'magma', -70, 0, '{:.0f}', 'dB')
    heat(ax[1, 1], G['bass'], 'Bass: 50 Hz band minus 101 Hz band', 'RdBu', -15, 15, '{:.0f}', 'dB')
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, dpi=110, facecolor=SURF)
    print(out, f'clip ceiling {ceil:.1f} dBFS')
    print('cutoff: Q-0 level, max rise, Q where the peak first reaches the ceiling (within 1 dB), fuzz onset Q (THD > -30),'
          ' THD at Q 127, bass at Q 127')
    for i, c in enumerate(CUTS):
        at = next((QS[j] for j in range(len(QS)) if G['peak'][i, j] >= ceil - 1), None)
        print(f'  {c:3d}: {G["level"][i, 0]:+6.1f}  {np.nanmax(G["rise"][i]):+5.1f}  clip from Q {str(at):>4}'
              f'  fuzz from Q {str(onset[i]):>4}  THD {G["thd"][i, -1]:+6.1f}  bass {G["bass"][i, -1]:+5.1f}')
    json.dump({k: v.tolist() for k, v in G.items()} | {'ceiling': ceil, 'onset': onset, 'cuts': CUTS, 'qs': QS},
              open(os.path.splitext(out)[0] + '.json', 'w'))


if __name__ == '__main__':
    main()
