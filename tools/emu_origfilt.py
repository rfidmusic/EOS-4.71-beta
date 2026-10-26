#!/usr/bin/env python3
"""Emulator test of tools/build_origfilt.py.

usage: emu_origfilt.py STOCK.bin BUILD2.bin NEW.bin      (NEW.origfilt.json from the builder must exist)
 1. The eight E-mu filters in NEW (through their vtables at the stock addresses) against EOS 4.70 (STOCK):
    type, name, computeFrames (modes 0/3, q 0..255, block filled with 0xA5 or neutral, base gain 0x00FE00FE or
    0x00C200C2), packQ (q 0..127), formatParam (indexes 0..3, values 0/64/128/255), and the remaining slots.
 2. The eight OB-Xa entries in NEW (their new vtables) against build 2's OB-Xa models (BUILD2, stock vtable
    addresses): the same calls; type and name must be the new ones.
 3. The registry: NEW's manager (0x6842C, malloc stubbed) must list 31 filters: STOCK's 21 in stock order, the eight
    OB-Xa models, 4 Pole LP+Fuzz, the default; every type ID must map to its object, and type <-> menu index
    (0x68458 / 0x684A0) must round-trip for all 30 filters.
Every call compares the return value, all 16 block words and the SETMODE arguments.
"""
import json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_obxa as eo            # noqa: E402
import eos_filter as ef          # noqa: E402
from unicorn import UC_HOOK_CODE                               # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC   # noqa: E402

BASE, GAINBASE = 0x20000, 0x10004D7C
LBUF, VBUF = eo.LBUF, eo.VBUF
VTS = [0x68878, 0x688A4, 0x688D0, 0x688FC, 0x68928, 0x689D8, 0x68A04, 0x68A30]
GETMGR, TYPE2MENU, MENU2TYPE, MGR_PTR, MALLOC = 0x6842C, 0x68458, 0x684A0, 0x1000262C, 0x2AFDC
HEAP = 0x10040000


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


class E(eo.Emu):
    def __init__(self, img):
        super().__init__(img)
        self.heap = HEAP
        self.mu.hook_add(UC_HOOK_CODE, self._malloc, begin=MALLOC, end=MALLOC)

    def _malloc(self, mu, addr, size, _):
        sp = mu.reg_read(UC_M68K_REG_A7)
        ret, n = struct.unpack('>II', mu.mem_read(sp, 8))
        mu.reg_write(UC_M68K_REG_D0, self.heap)
        self.heap += (n + 15) & ~15
        mu.reg_write(UC_M68K_REG_A7, sp + 4)
        mu.reg_write(UC_M68K_REG_PC, ret)

    def call_full(self, fn, args, fill):
        self.mu.mem_write(GAINBASE, struct.pack('>I', self.gain))
        r, blk, calls = self.call(fn, args, blk_init=fill)
        return r, tuple(blk), tuple(calls)

    def text(self, fn, args):
        self.mu.mem_write(LBUF, bytes(64))
        self.mu.mem_write(VBUF, bytes(64))
        r = self.call(fn, args)[0]
        return r, self.cstr(LBUF), self.cstr(VBUF)


def compare(A, a_img, a_vt, Bm, b_img, b_vt, label, fails, check_type=True):
    n = 0
    sa = lambda off: u32(a_img, a_vt + off)      # noqa: E731
    sb = lambda off: u32(b_img, b_vt + off)      # noqa: E731
    if check_type:
        for off in (0x0C,):
            n += 1
            if A.call(sa(off), [0])[0] != Bm.call(sb(off), [0])[0]:
                fails.append(f'{label}: type differs')
        n += 1
        if A.cstr(A.call(sa(0x10), [0])[0]) != Bm.cstr(Bm.call(sb(0x10), [0])[0]):
            fails.append(f'{label}: name differs')
    for off in (0x00, 0x04, 0x08, 0x20, 0x24, 0x28):
        n += 1
        if sa(off) != sb(off):
            fails.append(f'{label}: slot {off:#x} {sa(off):#x} != {sb(off):#x}')
    for gain in (0x00FE00FE, 0x00C200C2):
        A.gain = Bm.gain = gain
        for fill in (eo.FILL, ef.NEUTRAL):
            A.set_drive(0); Bm.set_drive(0)
            for mode in (0, 3):
                for q in range(256):
                    n += 1
                    args = [0, eo.BLK, mode, q, eo.STRUCT]
                    if A.call_full(sa(0x14), args, fill) != Bm.call_full(sb(0x14), args, fill):
                        fails.append(f'{label}: computeFrames mode {mode} q {q} gain {gain:#x} fill {fill:#x}')
            for q in range(128):
                n += 1
                args = [0, eo.BLK, q, eo.STRUCT]
                if A.call_full(sa(0x18), args, fill) != Bm.call_full(sb(0x18), args, fill):
                    fails.append(f'{label}: packQ q {q} gain {gain:#x} fill {fill:#x}')
    for idx in range(4):
        for val in (0, 64, 128, 255):
            n += 1
            args = [0, idx, val, LBUF, VBUF]
            if A.text(sa(0x1C), args) != Bm.text(sb(0x1C), args):
                fails.append(f'{label}: formatParam {idx} {val}: {A.text(sa(0x1C), args)} != {Bm.text(sb(0x1C), args)}')
    return n


def registry(img):
    R = E(img)
    R.mu.mem_write(MGR_PTR, bytes(4))
    R.call(GETMGR, [])
    mgr = struct.unpack('>I', bytes(R.mu.mem_read(MGR_PTR, 4)))[0]
    return R, mgr


def main():
    stock, b2, new = (open(p, 'rb').read() for p in sys.argv[1:4])
    info = json.load(open(sys.argv[3] + '.origfilt.json'))
    fails, n = [], 0
    S, B2, N = E(stock), E(b2), E(new)
    for vt in VTS:
        n += compare(N, new, vt, S, stock, vt, f'E-mu {vt:#x}', fails)
    print(f'1. E-mu filters vs EOS 4.70: {n} calls; {len(fails)} failures')
    n1, f1 = n, len(fails)
    for (name, o), vt in zip(info['obxa'].items(), VTS):
        n += compare(N, new, o['vtable'], B2, b2, vt, name, fails, check_type=False)
        n += 2
        if N.call(u32(new, o['vtable'] + 0x0C), [0])[0] != o['type']:
            fails.append(f'{name}: type not {o["type"]:#x}')
        if N.cstr(N.call(u32(new, o['vtable'] + 0x10), [0])[0]) != name:
            fails.append(f'{name}: name wrong')
    print(f'2. OB-Xa entries vs build 2: {n - n1} calls; {len(fails) - f1} failures')
    # 3. registry
    f2 = len(fails)
    Rs, ms = registry(stock)
    Rn, mn = registry(new)
    def menu(R, m):
        cnt = struct.unpack('>I', bytes(R.mu.mem_read(m + 0x27C if R is Rn else m + 0x258, 4)))[0]
        out = []
        for k in range(cnt):
            obj = struct.unpack('>I', bytes(R.mu.mem_read(m + 0x200 + 4 * k, 4)))[0]
            vt = struct.unpack('>I', bytes(R.mu.mem_read(obj, 4)))[0]
            t = R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x0C, 4)))[0], [obj])[0]
            nm = R.cstr(R.call(struct.unpack('>I', bytes(R.mu.mem_read(vt + 0x10, 4)))[0], [obj])[0])
            out.append((t, nm, obj))
        return out
    ls, ln = menu(Rs, ms), menu(Rn, mn)
    want = [(t, nm) for t, nm, _ in ls[:21]] + [(o['type'], k) for k, o in info['obxa'].items()] \
        + [(3, '4 Pole LP+Fuzz'), (ls[21][0], ls[21][1])]
    got = [(t, nm) for t, nm, _ in ln]
    n += 1
    if got != want:
        fails.append(f'menu: {got} != {want}')
    for t, nm, obj in ln:
        n += 1
        slot = struct.unpack('>I', bytes(Rn.mu.mem_read(mn + 4 * t, 4)))[0]
        if slot != obj:
            fails.append(f'type table {t:#x} -> {slot:#x}, object {obj:#x}')
    for k, (t, nm, _) in enumerate(ln[:-1]):
        n += 2
        if Rn.call(TYPE2MENU, [t])[0] != k:
            fails.append(f'type {t:#x} -> menu {Rn.call(TYPE2MENU, [t])[0]}, want {k}')
        if Rn.call(MENU2TYPE, [k])[0] != t:
            fails.append(f'menu {k} -> type {Rn.call(MENU2TYPE, [k])[0]:#x}, want {t:#x}')
    print(f'3. registry: {len(ln)} menu entries; {len(fails) - f2} failures')
    for k, (t, nm, _) in enumerate(ln):
        print(f'   {k:2d}  type {t:#04x}  {nm}')
    print(f'{n} checks; {len(fails)} failures')
    for f in fails[:15]:
        print('  ' + f)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
