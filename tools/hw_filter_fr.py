#!/usr/bin/env python3
"""Filter responses on the E4 with the sine-sweep sample: one sweep per filter type / cutoff / Q.

Preset 000 voice 0 (Test Suite.E4B), key 77 (F4) = 20 s log sweep 20 Hz-20 kHz at -12 dBFS, held until the
sample ends (hw_freqresp.play). Reference: Swept EQ (menu 8) gain 64 = flat, at the start and the end.
Raw takes are saved as OUTDIR/<tag>.npy and logged in OUTDIR/log.json; existing takes are skipped (resumable).
Analyse with lpfuzz_fr_analyze.py OUTDIR. Quantum inputs 19/20 only.

usage: hw_filter_fr.py OUTDIR TYPES CUTS QS [--fast]   (comma lists of menu indexes / cutoff values / Q values)
  e.g. hw_filter_fr.py recordings/fr 21 0,64,128,192,255 0,32,64,96,127
  --fast: the 6 s sweep (testsignals/sweep_20Hz-20kHz_6s_-12dBFS.wav, loaded on key 81 = A4) instead of the
          20 s sweep on key 77; analyse with lpfuzz_fr_analyze using T = 6
  --fuzz8: Fuzz8 test firmware names for menu 21-28 (fz2p fz4p fz6p fzhp2 fzhp4 fzbp2 fzbp4 fzcbp)
  --fuzz6: Fuzz6 test firmware names for menu 21-26 (fz2p fz4p fz6p fzhp2 fzbp2 fzcbp)
  --fuzzob: FuzzOB test firmware names for menu 21-25 (fob2p fob4p fobhp2 fobbp2 fobcbp; 22 = the original LP+Fuzz)
  --sw N: set parameter 195 (the Fuzz test switch) to N first (default: leave it)
"""
import json, math, os, sys, time
import numpy as np, mido, sounddevice as sd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eos_remote as er          # noqa: E402
import hw_freqresp as fr         # noqa: E402
import hw_burst_test as hb       # noqa: E402
from hw_freqresp import play, FILT_CORD_AMTS, REF_TYPE, REF_Q, NAMES   # noqa: E402

NAMES = {**NAMES, 21: 'lpfuzz'}
FUZZ8 = {21: 'fz2p', 22: 'fz4p', 23: 'fz6p', 24: 'fzhp2', 25: 'fzhp4', 26: 'fzbp2', 27: 'fzbp4', 28: 'fzcbp'}
FUZZ6 = {21: 'fz2p', 22: 'fz4p', 23: 'fz6p', 24: 'fzhp2', 25: 'fzbp2', 26: 'fzcbp'}
FUZZOB = {21: 'fob2p', 22: 'fob4p', 23: 'fobhp2', 24: 'fobbp2', 25: 'fobcbp'}


def main():
    out = sys.argv[1]
    types, cuts, qs = ([int(v) for v in a.split(',')] for a in sys.argv[2:5])
    if '--fast' in sys.argv:
        fr.KEY, fr.DUR = 81, 6.5
    if '--fuzz8' in sys.argv:
        NAMES.update(FUZZ8)
    if '--fuzz6' in sys.argv:
        NAMES.update(FUZZ6)
    if '--fuzzob' in sys.argv:
        NAMES.update(FUZZOB)
    os.makedirs(out, exist_ok=True)
    dev = hb.device()
    e = er.Eos()
    e.out.send(mido.Message('program_change', channel=0, program=0)); time.sleep(0.5)
    e.set(223, 0); e.set(225, 0)
    for c in FILT_CORD_AMTS:
        e.set(c, 0)
    e.set(41, 0)
    if '--sw' in sys.argv:
        e.set(195, int(sys.argv[sys.argv.index('--sw') + 1])); time.sleep(0.1)
        print('switch (parameter 195) =', e.get([195]), flush=True)
    sweep_s = 6.0 if '--fast' in sys.argv else 20.0
    # warm-up: the first note after the setup above can come out low (3.4 dB in the A/B run); discard it
    e.set(82, REF_TYPE); e.set(83, 128); e.set(84, REF_Q); time.sleep(0.2)
    play(e, dev)
    logp = os.path.join(out, 'log.json')
    log = json.load(open(logp)) if os.path.exists(logp) else []

    def run(tag, ft, fv, q):
        p = os.path.join(out, f'{tag}.npy')
        if os.path.exists(p):
            return
        e.set(82, ft); time.sleep(0.15); e.set(83, fv); e.set(84, q); time.sleep(0.2)
        got = e.get([82, 83, 84])
        for attempt in range(3):           # CoreAudio can refuse an open once (PortAudio -9986): retry
            try:
                x = play(e, dev)
                break
            except sd.PortAudioError as err:
                print(f'{tag}: audio open failed ({err}), retrying', flush=True)
                time.sleep(5)
        else:
            raise SystemExit(f'{tag}: audio input failed 3 times')
        np.save(p, x.astype(np.float32))
        pk = round(20 * math.log10(float(np.abs(x).max()) + 1e-12), 1)
        log.append(dict(tag=tag, type=ft, cut=fv, q=q, params=got, peak_dbfs=pk, sweep_s=sweep_s))
        json.dump(log, open(logp, 'w'), indent=1)
        print(f'{tag:22s} {got}  peak {pk} dBFS', flush=True)

    run('ref_start', REF_TYPE, 128, REF_Q)   # (after the discarded warm-up take)
    for ft in types:
        for cut in cuts:
            for q in qs:
                run(f'{NAMES.get(ft, f"t{ft}")}_c{cut}_q{q}', ft, cut, q)
    run('ref_end', REF_TYPE, 128, REF_Q)
    e.close()


if __name__ == '__main__':
    main()
