#!/usr/bin/env python3
"""Merge the fast (6 s sweep) grid with the 20 s retakes into one analysed set for filter_fr_report.py.

Each take is analysed (lpfuzz_fr_analyze.analyse) with its own sweep length (log 'sweep_s', default 20) and
expressed relative to its own run's flat Swept-EQ reference (ref_end if present, else ref_start). The 20 s take
is used wherever the 6 s sweep is unreliable (cutoff <= SLOW_CUT and Q >= SLOW_Q; see recordings/ab_sweep.png),
the 6 s take everywhere else. Writes OUT/log.json and OUT/bands.json (levels already relative: ref = 0 dB), and
OUT/source.json (which take each setting came from).

usage: filter_fr_merge.py OUT FASTDIR SLOWDIR [--rate R]
  --rate R: the E4 played the sweeps at R x their rate (0.9194 = E4 on its 44.1 kHz fallback clock, recorded at
            48 kHz): the analysis follows a sweep of length T/R from 20R to 20000R Hz (bands stay in real Hz)
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lpfuzz_fr_analyze as A     # noqa: E402

SLOW_CUT, SLOW_Q = 16, 64
RATE = float(sys.argv[sys.argv.index('--rate') + 1]) if '--rate' in sys.argv else 1.0


def analysed(d):
    log = json.load(open(os.path.join(d, 'log.json')))
    cache = os.path.join(d, 'bands_T.json' if RATE == 1.0 else f'bands_T_r{RATE}.json')
    have = json.load(open(cache)) if os.path.exists(cache) else {}
    for r in log:
        if r['tag'] in have or not os.path.exists(os.path.join(d, r['tag'] + '.npy')):
            continue
        A.T = float(r.get('sweep_s', 20.0)) / RATE
        A.F1, A.F2 = 20.0 * RATE, 20000.0 * RATE
        have[r['tag']] = A.analyse(np.load(os.path.join(d, r['tag'] + '.npy')), A.ideal())
    json.dump(have, open(cache, 'w'))
    ref = have.get('ref_end') or have['ref_start']
    rl = {b['f']: b['level'] for b in ref}
    rel = {t: [dict(b, level=round(b['level'] - rl.get(b['f'], 0), 2)) for b in bs] for t, bs in have.items()}
    return {r['tag']: r for r in log}, rel


def main():
    out, fd, sd_ = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    flog, fb = analysed(fd)
    slog, sb = analysed(sd_)
    log, bands, src = [], {}, {}
    for tag, r in flog.items():
        if tag.startswith('ref') or tag not in fb:
            continue
        use_slow = r['cut'] <= SLOW_CUT and r['q'] >= SLOW_Q and tag in sb
        bands[tag] = sb[tag] if use_slow else fb[tag]
        log.append(dict(slog[tag] if use_slow else r))
        src[tag] = '20 s' if use_slow else '6 s'
    zero = [dict(b, level=0.0) for b in fb['ref_start']]
    bands['ref_start'] = zero
    log.insert(0, dict(tag='ref_start', type=8, cut=128, q=64))
    json.dump(log, open(os.path.join(out, 'log.json'), 'w'), indent=1)
    json.dump(bands, open(os.path.join(out, 'bands.json'), 'w'))
    json.dump(src, open(os.path.join(out, 'source.json'), 'w'), indent=1)
    print(f'{out}: {len(bands) - 1} settings ({sum(v == "20 s" for v in src.values())} from 20 s retakes)')


if __name__ == '__main__':
    main()
