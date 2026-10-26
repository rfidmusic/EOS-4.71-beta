#!/usr/bin/env python3
"""Chip model for the Fuzz variants: which way do paired pole/zero sections scale when the zeros are on?

Two candidates for a block written with the zeros on (SETMODE 0xC0):
  'stage'  every stage scaled on its own (tools/eos_filter.py / sim_filters.py, the measured stage law):
           pole  w0^2 / (s^2 + b s + w0^2),   zero  (s^2 + b s + w0^2) / wn^2
  'paired' sections (0,1) and (4,5) are one ratio Z(s) / P(s) without scaling (patches/lpfuzz/lpfuzz.s, v5 notes);
           the unpaired pole 8 is scaled as a pole; word 9 is the gain (not modelled)
The block comes from the image's own filter code in Unicorn (NEW image, menu order of build_origfilt.py).
usage: fuzz_model.py NEW.bin MEASURED_BANDS.json      (bands.json of a hardware grid run with lpfuzz_* tags)
Prints, for LP+Fuzz, the passband level change from Q 0 to each Q at each cutoff: measured, and both models.
"""
import json, math, os, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_origfilt as eot        # noqa: E402
import emu_obxa as eo             # noqa: E402
import eos_filter as ef           # noqa: E402
import sim_filters as sf          # noqa: E402

BASE = 0x20000
WN = 2 * math.pi * 8060.0


def poly(word, morph):
    """(b, w0) of a stage word at the cutoff morph, with the measured stage law's f0 and damping."""
    xs, fs_ = [], []
    for hi in (True, False):
        x, f = ef.half(word, hi)
        xs.append(x); fs_.append(f)
    x = xs[0] + (xs[1] - xs[0]) * morph
    f = fs_[0] + (fs_[1] - fs_[0]) * morph
    f0 = 1398.5 * 2 ** ((f - 0x80) / 31.42)
    return sf.damping(x) * 2 * math.pi, 2 * math.pi * f0


def P(word, morph, s):
    b, w = poly(word, morph)
    return s * s + b * s + w * w, w


def response(block, morph, model, freqs):
    s = 2j * math.pi * np.asarray(freqs, float)
    h = np.ones_like(s)
    for p, z in ((0, 1), (4, 5)):
        pp, wp = P(block[p], morph, s)
        zz, wz = P(block[z], morph, s)
        if model == 'paired':
            h *= zz / pp
        else:
            h *= (wp * wp / pp) * (zz / WN ** 2)
    pp, wp = P(block[8], morph, s)
    h *= wp * wp / pp
    return 20 * np.log10(np.abs(h) + 1e-30)


def blocks(img, vt, cuts, qs):
    E = eot.E(img)
    E.gain = 0x00FE00FE
    cf = struct.unpack('>I', img[vt + 0x14 - BASE:vt + 0x18 - BASE])[0]
    out = {}
    for q in qs:
        E.set_drive(0)
        _, blk, calls = E.call_full(cf, [0, eo.BLK, 3, q, eo.STRUCT], ef.NEUTRAL)
        out[q] = (list(blk), calls)
    return out


def main():
    img = open(sys.argv[1], 'rb').read()
    meas = json.load(open(sys.argv[2]))
    info = json.load(open(sys.argv[1] + '.origfilt.json'))
    vl = info['vtlist']
    lpf = struct.unpack('>H', img[vl + 2 * 29 - BASE:vl + 2 * 29 + 2 - BASE])[0] * 2 + 0x60000
    QS = [0, 32, 64, 96, 127]
    bl = blocks(img, lpf, None, QS)
    print('LP+Fuzz: passband level change from Q 0 (dB), at 101-320 Hz;  measured | stage model | paired model')
    for c in (0, 32, 64, 96, 128, 160, 192, 224):
        m = c / 255
        row = []
        for q in QS[1:]:
            tag, tag0 = f'lpfuzz_c{c}_q{q}', f'lpfuzz_c{c}_q0'
            def band(t):
                v = [b['level'] for b in meas.get(t, []) if 101 <= b['f'] <= 320 and b['level'] == b['level']]
                return float(np.median(v)) if v else float('nan')
            mv = band(tag) - band(tag0)
            f = [101, 127, 160, 202, 254, 320]
            st = np.median(response(bl[q][0], m, 'stage', f)) - np.median(response(bl[0][0], m, 'stage', f))
            pa = np.median(response(bl[q][0], m, 'paired', f)) - np.median(response(bl[0][0], m, 'paired', f))
            row.append(f'Q{q:3d} {mv:+6.1f} | {st:+6.1f} | {pa:+6.1f}')
        print(f'cut {c:3d}: ' + '   '.join(row))


if __name__ == '__main__':
    main()
