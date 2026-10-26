#!/usr/bin/env python3
"""Original 4 Pole LP+Fuzz (build 2) vs the Fuzz6 4 Pole in the emulator: block words, base filter, chip-model gain.

usage: fuzz_cmp_lp4.py [MODE]   (cf mode, default 3; images build/eos471_beta2_b2.bin and build/eos471_fuzz6.bin)
"""
import sys, struct, json
sys.path.insert(0, 'tools')
import emu_fuzz as F, emu_origfilt as eot, emu_obxa as eo, eos_filter as ef
b2 = open('build/eos471_beta2_b2.bin', 'rb').read()
f6 = open('build/eos471_fuzz6.bin', 'rb').read()
def find(img, name, off):
    R, m = eot.registry(img)
    cnt = struct.unpack('>I', bytes(R.mu.mem_read(m + off, 4)))[0]
    for k in range(cnt):
        obj = struct.unpack('>I', bytes(R.mu.mem_read(m + 0x200 + 4 * k, 4)))[0]
        vt = struct.unpack('>I', bytes(R.mu.mem_read(obj, 4)))[0]
        nm = R.cstr(R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x10, 4)))[0], [obj])[0])
        if nm == name:
            return k, vt
    raise SystemExit(f'{name} not found')
for off in (0x258, 0x27C):
    try:
        k, vo = find(b2, '4 Pole LP+Fuzz', off); break
    except Exception as e:
        pass
k6, v6 = find(f6, '4 Pole LP+Fuzz', 0x27C)
print(f'build 2: menu {k} vtable {vo:#x}   Fuzz6: menu {k6} vtable {v6:#x}')
O, N = F.E(b2), F.E(f6)
for E_, vt in ((O, vo), (N, v6)):
    E_.mu.mem_write(F.OBJ, struct.pack('>I', vt))
cfo, cfn = F.u32(b2, vo + 0x14), F.u32(f6, v6 + 0x14)
mode = int(sys.argv[1]) if len(sys.argv) > 1 else 3
diff_words = {}
rows = []
for q in range(128):
    O.set_drive(0); N.set_drive(0)
    ro, bo, co = O.run(cfo, [F.OBJ, eo.BLK, mode, q, eo.STRUCT], [ef.NEUTRAL] * 16, 0)
    rn, bn, cn = N.run(cfn, [F.OBJ, eo.BLK, mode, q, eo.STRUCT], [ef.NEUTRAL] * 16, 0)
    d = [i for i in range(10) if bo[i] != bn[i]]
    for i in d: diff_words.setdefault(i, []).append(q)
    rows.append((q, ro, rn, bo[:10], bn[:10], co, cn, d))
print('words that differ (and Q ranges):', {i: (min(v), max(v), len(v)) for i, v in diff_words.items()})
print('return differs at Q:', [r[0] for r in rows if r[1] != r[2]][:20], ' calls differ at Q:', [r[0] for r in rows if r[5] != r[6]][:10])
for q in (0, 16, 32, 47, 48, 49, 64, 80, 96, 112, 127):
    r = rows[q]
    print(f'Q{q:3d} ret {r[1]:#x}/{r[2]:#x} diff {r[7]}')
    print('   orig', ' '.join(f'{w:08x}' for w in r[3]))
    print('   new ', ' '.join(f'{w:08x}' for w in r[4]))

print('\nBase 4 Pole Lowpass at Q/2 (what each LP+Fuzz starts from), words 0,4,5,8:')
kb, vb = find(b2, '4 Pole Low-pass', 0x258)
ks, vs = find(f6, '4 Pole Low-pass', 0x27C)
print(f'build 2 "4 Pole Lowpass" vtable {vb:#x};  Fuzz6 (stock) vtable {vs:#x}')
cfb, cfs = F.u32(b2, vb + 0x14), F.u32(f6, vs + 0x14)
for q in (16, 32, 48, 64, 96, 127):
    O.mu.mem_write(F.OBJ, struct.pack('>I', vb)); N.mu.mem_write(F.OBJ, struct.pack('>I', vs))
    O.set_drive(0); N.set_drive(0)
    _, bb, _ = O.run(cfb, [F.OBJ, eo.BLK, 3, q >> 1, eo.STRUCT], [ef.NEUTRAL] * 16, 0)
    _, bs, _ = N.run(cfs, [F.OBJ, eo.BLK, 3, q >> 1, eo.STRUCT], [ef.NEUTRAL] * 16, 0)
    print(f'Q{q:3d} (base {q>>1:2d})  build2 ' + ' '.join(f'{bb[i]:08x}' for i in (0, 4, 5, 8)) + '   stock ' + ' '.join(f'{bs[i]:08x}' for i in (0, 4, 5, 8)))

import numpy as np, json
fr = np.geomspace(30, 16000, 400)
meas_o = json.load(open('recordings/fr_fix_merged/bands.json')); meas_n = json.load(open('recordings/fz4p48_merged/bands.json'))
print('\nChip model (paired zeros), peak gain of the whole block, orig vs new, vs measured passband (101-320 Hz median) difference')
for cut in (0, 64, 96, 128, 160, 192):
    out = []
    for q in (48, 64, 80, 96, 127):
        r = rows[q]
        go = F.model(r[3] + [0]*6, cut / 255, fr).max(); gn = F.model(r[4] + [0]*6, cut / 255, fr).max()
        bo = [x['level'] for x in meas_o[f'lpfuzz_c{cut}_q{q}'] if 101 <= x['f'] <= 320] if f'lpfuzz_c{cut}_q{q}' in meas_o else None
        out.append(f'Q{q:3d} {go:+5.1f}/{gn:+5.1f} ({gn-go:+4.1f})')
    print(f'cut {cut:3d}: ' + '  '.join(out))
