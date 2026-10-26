#!/usr/bin/env python3
"""Emulator test of tools/build_fuzzob.py (Fuzz filters on the OB-Xa models).

usage: emu_fuzzob.py STOCK.bin BUILD2.bin NEW.bin [--mutate]   (NEW.fuzzob.json from the builder must exist)
 1. The eight E-mu filters whose code moved (vtables at the stock addresses) against EOS 4.70: type, name,
    computeFrames (modes 0/3, q 0..255, two block fills, two base gains), packQ, formatParam, the other slots.
 2. The registry: 27 entries: 4.70's 21 in stock order, 2 Pole LP+Fuzz, 4 Pole LP+Fuzz, 2nd Ord HP+Fuzz,
    2nd Ord BP+Fuzz, Contrary BP+Fuzz, the default; type <-> menu round trips.
 3. 4 Pole LP+Fuzz (menu 22) against build 2's LP+Fuzz: every call as in 1.
 4. The four engine filters against a reference built from build 2's OB-Xa model (BUILD2's vtable): the model at
    q / 2, the program (COPY / SMTH / DZER = the original zlerp law), word 9 and the return value from the LP+Fuzz
    laws, SETMODE(blk, mode, flags) appended when flags; packQ the same without SETMODE; type and name; formatParam
    idx 1 = build 2's LP+Fuzz formatter, other indexes = the OB-Xa model's. computeFrames modes 0/3, q 0..127,
    two fills, two base gains; packQ q 0..127 from a computeFrames start block.
 5. Q 0: each engine filter's drive zero equals its pole (the pair cancels), for every mode / fill / gain.
 6. Coverage: running every menu filter, the LP+Fuzz and the OB-Xa bases never executes or reads a byte of the
    builder's EXTRA pieces outside the engine code placed there.
 --mutate: also flips one byte in each engine section and in each parameter block and checks that 4 fails.
Every call compares the return value, all 16 block words and the SETMODE arguments.
"""
import json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_origfilt as eot       # noqa: E402
import emu_obxa as eo            # noqa: E402
import emu_fuzz as F             # noqa: E402
import eos_filter as ef          # noqa: E402
import build_fuzzob as bf        # noqa: E402
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ   # noqa: E402

BASE = 0x20000
B2_LPF = 0x682FC                   # build 2's LP+Fuzz vtable
GAINS = (0x00FE00FE, 0x00C200C2)
FILLS = (eo.FILL, ef.NEUTRAL)


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


def program(blk, prog, q):
    b = list(blk)
    for op, d, s in prog:
        w = b[s]
        if op == bf.SMTH:
            if (w >> 24) < 0xC0:
                w = (w & 0x00FFFFFF) | 0xC0000000
            if ((w >> 8) & 0xFF) < 0xC0:
                w = (w & 0xFFFF00FF) | 0x0000C000
        elif op == bf.DZER:
            w = F.dzero(w, q, 0)
        b[d] = w
    return b


def level(b, q, gain, goff):
    b = list(b)
    b[9] = (gain - goff[q >> 4]) & 0xFFFFFFFF
    return b, (((q >> 1) * -20) >> 7) & 0xFFFFFFFF


def menu(R, m):
    cnt = struct.unpack('>I', bytes(R.mu.mem_read(m + 0x27C, 4)))[0]
    out = []
    for k in range(cnt):
        obj = struct.unpack('>I', bytes(R.mu.mem_read(m + 0x200 + 4 * k, 4)))[0]
        vt = struct.unpack('>I', bytes(R.mu.mem_read(obj, 4)))[0]
        t = R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x0C, 4)))[0], [obj])[0]
        nm = R.cstr(R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x10, 4)))[0], [obj])[0])
        out.append((t, nm, vt, obj))
    return out


def engine(N, new, B2, b2, info, goff, fails, obj_of):
    n = 0
    for lab, v in info['variants'].items():
        vt, base, prog, sm = v['vtable'], v['base'], [tuple(p) for p in v['prog']], v['setmode']
        obj = F.OBJ                                      # this -> the vtable, in N's memory
        N.mu.mem_write(obj, struct.pack('>I', vt))
        cf, pq, fmt = (u32(new, vt + o) for o in (0x14, 0x18, 0x1C))
        bcf, bpq, bfmt = (u32(b2, base + o) for o in (0x14, 0x18, 0x1C))
        n += 2
        if N.call(u32(new, vt + 0x0C), [obj])[0] != v['type']:
            fails.append(f'{lab}: type')
        if N.cstr(N.call(u32(new, vt + 0x10), [obj])[0]) != v['name']:
            fails.append(f'{lab}: name')
        for gain in GAINS:
            N.gain = B2.gain = gain
            for fill in FILLS:
                N.set_drive(0); B2.set_drive(0)
                for mode in (0, 3):
                    for q in range(128):
                        rb, bb, cb = B2.call_full(bcf, [0, eo.BLK, mode, q >> 1, eo.STRUCT], fill)
                        exp, rexp = level(program(bb, prog, q), q, gain, goff)
                        calls = cb + (((eo.BLK, mode, sm),) if sm else ())
                        got = N.call_full(cf, [obj, eo.BLK, mode, q, eo.STRUCT], fill)
                        n += 1
                        if got != (rexp, tuple(exp), calls):
                            fails.append(f'{lab} cf mode {mode} q {q} gain {gain:#x}: got {[hex(w) for w in got[1][:10]]} '
                                         f'ret {got[0]:#x} {got[2]} want {[hex(w) for w in exp[:10]]} ret {rexp:#x} {calls}')
                        if q == 0:
                            n += 1
                            d, s = next((d, s) for op, d, s in prog if op == bf.DZER)
                            pole = got[1][s] if d != s else bb[s]
                            if got[1][d] != pole:
                                fails.append(f'{lab}: Q 0 zero {got[1][d]:#x} != pole {pole:#x}')
                for q in range(128):
                    start = N.call_full(cf, [obj, eo.BLK, 3, (q * 37 + 11) & 127, eo.STRUCT], fill)[1]
                    # packQ works on the block in place: run the base on the start block (emu_fuzz.E.run sets the
                    # base gain to 0x00FE00FE itself)
                    rb, bb, cb = F.E.run(B2, bpq, [0, eo.BLK, q >> 1, eo.STRUCT], list(start), 0)
                    exp, rexp = level(program(bb, prog, q), q, 0x00FE00FE, goff)
                    got = F.E.run(N, pq, [obj, eo.BLK, q, eo.STRUCT], list(start), 0)
                    n += 1
                    if got[0] != rexp or got[1] != exp or got[2] != cb:
                        fails.append(f'{lab} pq q {q} gain {gain:#x}: got {[hex(w) for w in got[1][:10]]} ret {got[0]:#x} '
                                     f'{got[2]} want {[hex(w) for w in exp[:10]]} ret {rexp:#x} {cb}')
        for idx in range(4):
            for val in (0, 1, 64, 127, 128, 255):
                n += 1
                args = [obj, idx, val, eo.LBUF, eo.VBUF]
                want = B2.text(u32(b2, B2_LPF + 0x1C) if idx == 1 else bfmt, [0, idx, val, eo.LBUF, eo.VBUF])
                if N.text(fmt, args) != want:
                    fails.append(f'{lab} fmt {idx} {val}: {N.text(fmt, args)} != {want}')
    return n


def main():
    stock, b2, new = (open(p, 'rb').read() for p in sys.argv[1:4])
    info = json.load(open(sys.argv[3] + '.fuzzob.json'))
    fails, n = [], 0
    S, B2, N = F.E(stock), F.E(b2), F.E(new)
    goff = [u32(stock, F.GOFF + 4 * k) for k in range(8)]
    # 1
    for vt in eot.VTS:
        n += eot.compare(N, new, vt, S, stock, vt, f'E-mu {vt:#x}', fails)
    print(f'1. E-mu filters vs EOS 4.70: {n} calls; {len(fails)} failures')
    # 2
    f1, n1 = len(fails), n
    Rs, ms = eot.registry(stock)
    Rn, mn = eot.registry(new)
    cnt_s = struct.unpack('>I', bytes(Rs.mu.mem_read(ms + 0x258, 4)))[0]
    ls = []
    for k in range(cnt_s):
        obj = struct.unpack('>I', bytes(Rs.mu.mem_read(ms + 0x200 + 4 * k, 4)))[0]
        vt = struct.unpack('>I', bytes(Rs.mu.mem_read(obj, 4)))[0]
        ls.append((Rs.call(u32(stock, vt + 0x0C), [obj])[0], Rs.cstr(Rs.call(u32(stock, vt + 0x10), [obj])[0])))
    ln = menu(Rn, mn)
    order = info['order']
    want = ls[:21] + [(0x03, '4 Pole LP+Fuzz') if lab == 'lp4' else (info['variants'][lab]['type'],
                                                                       info['variants'][lab]['name']) for lab in order] + [ls[21]]
    n += 1
    if [(t, nm) for t, nm, _, _ in ln] != want:
        fails.append(f'menu {[(hex(t), nm) for t, nm, _, _ in ln]} != {want}')
    if ln[22][2] != info['lpf_vt']:
        fails.append('menu 22 is not the original LP+Fuzz vtable')
    for k, (t, _, _, _) in enumerate(ln[:-1]):
        n += 2
        if Rn.call(eot.TYPE2MENU, [t])[0] != k or Rn.call(eot.MENU2TYPE, [k])[0] != t:
            fails.append(f'type/menu round trip {k} {t:#x}')
    print(f'2. registry: {len(ln)} entries; {len(fails) - f1} failures')
    for k, (t, nm, vt, _) in enumerate(ln):
        if k >= 21:
            print(f'   {k:2d} type {t:#04x} {nm}  vtable {vt:#x}')
    obj_of = {vt: obj for _, _, vt, obj in ln}
    # 3
    f2, n2 = len(fails), n
    n += eot.compare(N, new, info['lpf_vt'], B2, b2, B2_LPF, '4 Pole LP+Fuzz', fails)
    print(f'3. 4 Pole LP+Fuzz vs build 2: {n - n2} calls; {len(fails) - f2} failures')
    # 4 + 5
    f3, n3 = len(fails), n
    n += engine(N, new, B2, b2, info, goff, fails, obj_of)
    print(f'4/5. engine filters vs build 2 OB-Xa + reference: {n - n3} checks; {len(fails) - f3} failures')
    # 6
    f4 = len(fails)
    lo_hi = [(lo, hi) for lo, hi, _ in info['extra']]
    placed = set()
    for lo, hi in lo_hi:
        for a in range(lo, hi):
            if new[a - BASE] != b2[a - BASE]:
                placed.add(a)
    hits = set()
    def hook(mu, a, s, *_):
        for x in range(a, a + s):
            for lo, hi in lo_hi:
                if lo <= x < hi and x not in placed:
                    hits.add(x)
    C = eot.E(new)
    C.mu.hook_add(UC_HOOK_CODE, lambda mu, a, s, _: hook(mu, a, s), begin=0x65C00, end=0x67000)
    C.mu.hook_add(UC_HOOK_MEM_READ, lambda mu, acc, a, s, v, _: hook(mu, a, s), begin=0x65C00, end=0x67000)
    bases = [(lab, [u32(b2, v['base'] + 4 * s) for s in range(11)]) for lab, v in info['variants'].items()]
    runs = [(nm, [u32(new, vt + 4 * s) for s in range(11)], vt) for _, nm, vt, _ in ln] + \
           [(lab, sl, 0) for lab, sl in bases]
    for nm, sl, vt in runs:
        obj = F.OBJ
        C.mu.mem_write(obj, struct.pack('>I', vt))
        for gain in GAINS:
            C.gain = gain
            for fill in FILLS:
                C.set_drive(0)
                for mode in (0, 3):
                    for q in range(0, 256, 3):
                        try:
                            C.call_full(sl[5], [obj, eo.BLK, mode, q, eo.STRUCT], fill)
                        except Exception:
                            pass
    n += 1
    if hits:
        fails.append(f'coverage: {len(hits)} bytes of the EXTRA pieces used: {sorted(hex(x) for x in hits)[:8]}')
    print(f'6. coverage of the reused OB-Xa pieces: {len(fails) - f4} failures')
    print(f'TOTAL {n} checks, {len(fails)} failures')
    for f in fails[:20]:
        print('  FAIL', f)
    if '--mutate' in sys.argv:
        caught = 0
        targets = [(f'section {sec}', a + 4) for sec, a in info['sections'].items()] + \
                  [(f'params {lab}', v['params'] + 14) for lab, v in info['variants'].items()]
        for what, a in targets:
            m = bytearray(new)
            m[a - BASE] ^= 0x01
            Nm = F.E(bytes(m))
            ff = []
            try:
                engine(Nm, bytes(m), B2, b2, info, goff, ff, obj_of)
            except Exception as e:
                ff.append(str(e))
            caught += bool(ff)
            print(f'   mutation {what} at {a:#x}: {"caught" if ff else "MISSED"}')
        print(f'mutations caught {caught}/{len(targets)}')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
