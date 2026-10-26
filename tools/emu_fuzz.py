#!/usr/bin/env python3
"""Emulator test of tools/build_fuzz.py.

usage: emu_fuzz.py STOCK.bin NEW.bin       (NEW.fuzz.json from the builder)
 1. E-mu filters: 0x65C00-0x67F98, the eight E-mu vtables and the table 0x6875C are byte-identical to EOS 4.70, and
    their methods behave as in 4.70 (tools/emu_origfilt.compare).
 2. Registry: 30 entries (STOCK's 21, the eight Fuzz variants, the default); type <-> menu round-trips.
 3. Each Fuzz variant against a Python reference of its recipe (patches/fuzz/fuzz.s): the stock filter run in STOCK
    with q / 2 (or q, switch bit 4), then the program; for switch values 0..31, q 0..127, computeFrames modes 0 / 3,
    and packQ from a block left by computeFrames at another q. Return value, all 16 block words and the SETMODE calls
    must match. formatParam: index 1 -> "Fuzz" / "%d", other indexes as the stock filter. type / name via `this`.
 4. Chip model with the chip's real pairing (pole 0 alone, zero 1 / pole 4, zero 5 / pole 8; tools/fuzz_model.py):
    transparent drive at Q 0 (and the expected Q-0 response), drive gain rising with Q (chip_checks).
"""
import json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_origfilt as eot       # noqa: E402
import emu_obxa as eo            # noqa: E402
import eos_filter as ef          # noqa: E402

BASE, GAINBASE, SW = 0x20000, 0x10004D7C, 0x100003E4
OBJ = 0x10011800
FILT, TABLE = (0x65C00, 0x67F98), (0x6875C, 0x6879C)
EMU_VTS = (0x68878, 0x688A4, 0x688D0, 0x688FC, 0x68928, 0x689D8, 0x68A04, 0x68A30)
DPF = (0x71, 0x60, 0x80, 0x50)
GOFF = 0x6871C


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


class E(eot.E):
    def run(self, fn, args, blk, sw):
        mu = self.mu
        mu.mem_write(GAINBASE, struct.pack('>I', 0x00FE00FE))
        mu.mem_write(SW, struct.pack('>I', sw))
        mu.mem_write(eo.BLK, b''.join(struct.pack('>I', w) for w in blk))
        sp = eo.STACK - 0x200
        mu.mem_write(sp, struct.pack('>' + 'I' * (len(args) + 1), eo.RET, *args))
        mu.reg_write(eo.UC_M68K_REG_A7, sp)
        self.calls = []
        mu.emu_start(fn, eo.RET, count=20000)
        r = mu.reg_read(eo.UC_M68K_REG_D0) & 0xffffffff
        return r, list(struct.unpack('>16I', mu.mem_read(eo.BLK, 64))), tuple(self.calls)


def dzero(pole, q, sw):
    if sw & 2:                                              # switch bit 1: new law
        dF = (q * 0x6F) >> 7
        out = 0
        for sh in (16, 0):
            h = (pole >> sh) & 0xFFFF
            F = min(0xE0, (h & 0xFF) + dF)
            out |= ((h & 0xFF00) | F) << sh
        return out
    out = 0
    for sh in (24, 16, 8, 0):
        a = (pole >> sh) & 0xFF
        t = (0xFFE0FFE0 >> sh) & 0xFF
        p = (t - a) * q
        p = ((p + (1 << 15)) & 0xFFFF) - (1 << 15)          # muls.w uses the low words
        quo = int(p / 127)                                  # divs.w: truncates toward zero
        quo = ((quo + (1 << 15)) & 0xFFFF) - (1 << 15)      # ext.l of the quotient word
        out = (out << 8) | ((quo + a) & 0xFF)
    return out


def prog(blk, v, q, sw):
    b = list(blk)
    last = 0
    for op, d, s in v['prog']:
        w = b[s]
        if op == 1:
            if (w & 0xFF) > 0xDF:
                w = (w & 0xFFFFFF00) | 0xDF
        elif op == 3:
            w |= 0xFF00FF00
        elif op == 4:
            if sw & 1:                                      # switch bit 0: fixed pole
                F = DPF[(sw >> 2) & 3]
                w = (0xC000 | F) * 0x10001
            elif v['flags'] & 1:                            # smooth: X at least 0xC0 in both frames
                if (w >> 24) < 0xC0:
                    w = (w & 0x00FFFFFF) | 0xC0000000
                if ((w >> 8) & 0xFF) < 0xC0:
                    w = (w & 0xFFFF00FF) | 0x0000C000
            last = w
        elif op == 5:
            w = dzero(last, q, sw)
        elif op == 6:
            w = 0xFFCFFFCF
        b[d] = w
    return b


def level(b, q, goff):
    b = list(b)
    b[9] = (0x00FE00FE - goff[q >> 4]) & 0xFFFFFFFF
    return b, (((q >> 1) * -20) >> 7) & 0xFFFFFFFF


def model(block, morph, freqs):
    """|H| in dB with the chip's pairing when the zeros are on: pole 0 alone, zero 1 / pole 4, zero 5 / pole 8."""
    import numpy as np
    import fuzz_model as fm
    s = 2j * np.pi * np.asarray(freqs, float)
    p0, w0 = fm.P(block[0], morph, s)
    h = (w0 * w0 / p0) * (fm.P(block[1], morph, s)[0] / fm.P(block[4], morph, s)[0]) \
        * (fm.P(block[5], morph, s)[0] / fm.P(block[8], morph, s)[0])
    return 20 * np.log10(np.abs(h))


def model_zeros_off(block, morph, freqs):
    import numpy as np
    import fuzz_model as fm
    s = 2j * np.pi * np.asarray(freqs, float)
    h = np.ones_like(s)
    for i in (0, 4, 8):
        p, w = fm.P(block[i], morph, s)
        h *= w * w / p
    return 20 * np.log10(np.abs(h))


def chip_checks(S, N, stock, new, info, fails):
    """Switch 0 (the LP+Fuzz design), cutoffs 0, 64, 128, 192, 255 (morph = cutoff / 255).
    Q 0: the drive pair cancels exactly (zero word == pole word; BP2: its drive is the stock band-pass pair).
    HP2 / BP2 / CBP: the response equals the stock filter's. LP: pole 0 is the stock pole (high-frame F capped) and
    the response equals the variant's with its drive pair neutral (the stand-alone low-pass, plus 6-pole's peak
    pair), as the original LP+Fuzz at Q 0.
    Q 0..127: the drive pair's low-frequency gain wz^2 / wp^2 never falls as Q rises (cutoff <= 192), and is at
    least +20 dB at Q 127 for cutoff <= 128."""
    import numpy as np
    import fuzz_model as fm
    freqs = [40 * 2 ** (i / 3) for i in range(26)]
    n = 0
    pair = {'lp2': (1, 4), 'lp4': (1, 4), 'lp6': (1, 4), 'hp2': (5, 8), 'bp2': (5, 8), 'cbp': (1, 4)}
    for v in info['variants']:
        vt, base = v['vtable'], v['base']
        N.mu.mem_write(OBJ, struct.pack('>I', vt))
        cf, bcf = u32(new, vt + 0x14), u32(stock, base + 0x14)
        z, p = pair[v['label']]
        for cut in (0, 64, 128, 192, 255):
            m = cut / 255
            blk0 = N.run(cf, [OBJ, eo.BLK, 3, 0, eo.STRUCT], [ef.NEUTRAL] * 16, 0)[1]
            sb = S.run(bcf, [0, eo.BLK, 3, 0, eo.STRUCT], [ef.NEUTRAL] * 16, 0)[1]
            n += 2
            hv = model(blk0, m, freqs)
            if v['label'] == 'bp2':                      # the stock band-pass pair is the drive: Q 0 = stock
                pass
            elif blk0[z] != blk0[p]:
                fails.append(f'{v["name"]} cut {cut}: drive pair not transparent at Q 0 ({blk0[z]:#x} / {blk0[p]:#x})')
            if v['label'] in ('hp2', 'cbp', 'bp2'):      # target: the stock filter (zeros on)
                hs = model(sb, m, freqs)
            else:                                        # LP: the variant with its drive pair neutral (pole 0 alone,
                tb = list(blk0)                          # plus 6-pole's peak pair) = the original LP+Fuzz at Q 0
                tb[z] = tb[p] = ef.NEUTRAL
                hs = model(tb, m, freqs)
                n += 1
                sp = S.run(bcf, [0, eo.BLK, 3, 0, eo.STRUCT], [ef.NEUTRAL] * 16, 0)[1][0]
                if (sp & 0xFF) > 0xDF:
                    sp = (sp & 0xFFFFFF00) | 0xDF
                if blk0[0] != sp:
                    fails.append(f'{v["name"]} cut {cut}: pole 0 {blk0[0]:#x} is not the stock pole {sp:#x}')
            dev = float(np.max(np.abs(hv - hs)))
            if dev > 0.01:
                fails.append(f'{v["name"]} cut {cut}: Q 0 response differs from the target by {dev:.2f} dB')
            prev = -1e9
            for q in range(0, 128, 4):
                b = N.run(cf, [OBJ, eo.BLK, 3, q, eo.STRUCT], [ef.NEUTRAL] * 16, 0)[1]
                _, wz = fm.P(b[z], m, 0j)
                _, wp = fm.P(b[p], m, 0j)
                g = 40 * np.log10(wz / wp)
                n += 1
                if cut <= 192 and g < prev - 0.01:
                    fails.append(f'{v["name"]} cut {cut}: drive gain falls at Q {q} ({prev:.1f} -> {g:.1f} dB)')
                prev = g
            b = N.run(cf, [OBJ, eo.BLK, 3, 127, eo.STRUCT], [ef.NEUTRAL] * 16, 0)[1]
            g = 40 * np.log10(fm.P(b[z], m, 0j)[1] / fm.P(b[p], m, 0j)[1])
            n += 1
            if cut <= 128 and g < 20:
                fails.append(f'{v["name"]} cut {cut}: drive only {g:.1f} dB at Q 127')
    return n


def main():
    stock, new = (open(p, 'rb').read() for p in sys.argv[1:3])
    info = json.load(open(sys.argv[2] + '.fuzz.json'))
    fails, n = [], 0
    # 1
    n += 3
    if new[FILT[0] - BASE:FILT[1] - BASE] != stock[FILT[0] - BASE:FILT[1] - BASE]:
        fails.append('filter code differs from 4.70')
    if any(new[v - BASE:v + 0x2C - BASE] != stock[v - BASE:v + 0x2C - BASE] for v in EMU_VTS):
        fails.append('E-mu vtables differ from 4.70')
    if new[TABLE[0] - BASE:TABLE[1] - BASE] != stock[TABLE[0] - BASE:TABLE[1] - BASE]:
        fails.append('table 0x6875C differs')
    S, N = E(stock), E(new)
    goff = [u32(stock, GOFF + 4 * k) for k in range(8)]
    for vt in EMU_VTS:
        n += eot.compare(N, new, vt, S, stock, vt, f'E-mu {vt:#x}', fails)
    print(f'1. E-mu filters vs 4.70: {n} checks; {len(fails)} failures')
    f1 = len(fails)
    # 2
    Rs, ms = eot.registry(stock)
    Rn, mn = eot.registry(new)
    def menu(R, m, off):
        cnt = struct.unpack('>I', bytes(R.mu.mem_read(m + off, 4)))[0]
        out = []
        for k in range(cnt):
            obj = struct.unpack('>I', bytes(R.mu.mem_read(m + 0x200 + 4 * k, 4)))[0]
            vt = struct.unpack('>I', bytes(R.mu.mem_read(obj, 4)))[0]
            t = R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x0C, 4)))[0], [obj])[0]
            nm = R.cstr(R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x10, 4)))[0], [obj])[0])
            out.append((t, nm))
        return out
    ls, ln = menu(Rs, ms, 0x258), menu(Rn, mn, 0x27C)
    want = ls[:21] + [(v['type'], v['name']) for v in info['variants']] + [ls[21]]
    n += 1
    if ln != want:
        fails.append(f'menu {ln} != {want}')
    for k, (t, _) in enumerate(ln[:-1]):
        n += 2
        if Rn.call(eot.TYPE2MENU, [t])[0] != k or Rn.call(eot.MENU2TYPE, [k])[0] != t:
            fails.append(f'type/menu round trip {k} {t:#x}')
    print(f'2. registry: {len(ln)} entries; {len(fails) - f1} failures')
    for k, (t, nm) in enumerate(ln):
        if k >= 20:
            print(f'   {k:2d} type {t:#04x} {nm}')
    f2, n2 = len(fails), n
    # 3
    for v in info['variants']:
        vt, base = v['vtable'], v['base']
        N.mu.mem_write(OBJ, struct.pack('>I', vt))
        cf, pq, fmt = (u32(new, vt + o) for o in (0x14, 0x18, 0x1C))
        bcf, bpq, bfmt = (u32(stock, base + o) for o in (0x14, 0x18, 0x1C))
        n += 2
        if N.call(u32(new, vt + 0x0C), [OBJ])[0] != v['type'] or N.cstr(N.call(u32(new, vt + 0x10), [OBJ])[0]) != v['name']:
            fails.append(f'{v["name"]}: type/name')
        for sw in range(32):
            for mode in (0, 3):
                for q in range(128):
                    qb = q if sw & 16 else q >> 1
                    init = [ef.NEUTRAL] * 16
                    S.set_drive(0); N.set_drive(0)
                    rb, bb, cb = S.run(bcf, [0, eo.BLK, mode, qb, eo.STRUCT], init, sw)
                    exp, rexp = level(prog(bb, v, q, sw), q, goff)
                    calls = cb + (((eo.BLK, mode, v['setmode']),) if v['setmode'] else ())
                    got = N.run(cf, [OBJ, eo.BLK, mode, q, eo.STRUCT], init, sw)
                    n += 1
                    if got != (rexp, exp, calls):
                        fails.append(f'{v["name"]} cf sw {sw} mode {mode} q {q}: got {[hex(w) for w in got[1][:10]]} '
                                     f'ret {got[0]:#x} {got[2]} want {[hex(w) for w in exp[:10]]} ret {rb:#x} {calls}')
            for q in range(0, 128, 3):
                q0 = (q * 37 + 11) & 127
                start = N.run(cf, [OBJ, eo.BLK, 3, q0, eo.STRUCT], [ef.NEUTRAL] * 16, sw)[1]
                qb = q if sw & 16 else q >> 1
                rb, bb, _ = S.run(bpq, [0, eo.BLK, qb, eo.STRUCT], start, sw)
                exp, rexp = level(prog(bb, v, q, sw), q, goff)
                got = N.run(pq, [OBJ, eo.BLK, q, eo.STRUCT], start, sw)
                n += 1
                if got[:2] != (rexp, exp):
                    fails.append(f'{v["name"]} pq sw {sw} q {q} (from q {q0}): got {[hex(w) for w in got[1][:10]]} '
                                 f'want {[hex(w) for w in exp[:10]]}')
        for idx in range(4):
            for val in (0, 64, 127):
                n += 1
                args = [OBJ, idx, val, eot.LBUF, eot.VBUF]
                got = N.text(fmt, args)[1:]
                want = ('Fuzz', str(val)) if idx == 1 else S.text(bfmt, [0, idx, val, eot.LBUF, eot.VBUF])[1:]
                if got != want:
                    fails.append(f'{v["name"]} formatParam {idx} {val}: {got} != {want}')
    print(f'3. Fuzz variants vs the reference: {n - n2} checks; {len(fails) - f2} failures')
    f3, n3 = len(fails), n
    n += chip_checks(S, N, stock, new, info, fails)
    print(f'4. chip model (pole 0 alone, zero 1 / pole 4, zero 5 / pole 8): {n - n3} checks; {len(fails) - f3} failures')
    print(f'{n} checks; {len(fails)} failures')
    for f in fails[:12]:
        print('  ' + f)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
