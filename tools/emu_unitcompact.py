#!/usr/bin/env python3
"""Emulator test of tools/unitcompact.py: each of the 21 unit-table sites, stock against compacted.

usage: emu_unitcompact.py STOCK.bin
The compacted image is built with the freed block 0x7F9E4-0x8018A filled with 0xA5, so any read left there would
give a different call target. For each site and each unit 0..44 (the multiplicand is forced at the site's muls),
both images run the site's real code from the movea onward with the same deterministic register, stack and memory
contents. The unit is forced at every muls that feeds a table read (the nearest muls before each patched
instruction), so loops that come back to a table read use a valid unit too. Every `jsr (a0)` records a0 and the data registers and is then stepped over (as if it returned 0); calls
to fixed addresses (`jsr abs`, `bsr`) are stepped over the same way, returning 0, 1 or -1 in d0 (three passes),
so the code after both outcomes of each call runs. A run ends at rts / unlk or after 400
instructions. Pass: the same sequence of call targets and data registers at every call, and the same final d0-d7.
A second pass plants a bug (only one adda left unpatched) to show the test catches it.
"""
import os, random, struct, sys
from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn.m68k_const import *   # noqa: F403

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unitcompact as uc          # noqa: E402

BASE = 0x20000
DREG = [UC_M68K_REG_D0, UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_D5,
        UC_M68K_REG_D6, UC_M68K_REG_D7]
AREG = [UC_M68K_REG_A0, UC_M68K_REG_A1, UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4, UC_M68K_REG_A5]


def is_muls(img, a):
    w = img[a - BASE:a - BASE + 2]
    return w in (b'\x4c\x01', b'\x4c\x2e', b'\xc1\xfc')


def table_muls(img):
    """Every muls that computes a table offset: the nearest muls before each patched instruction."""
    out = set()
    for a in [a for _, a, _ in uc.ADDA] + [a for _, a, _, _ in uc.INDEXED]:
        m = next((x for x in range(a - 2, a - 0x40, -2) if is_muls(img, x)), None)
        if m is not None:                             # (0x87772 reuses the offset saved after 0x873FC's muls)
            out.add(m)
    return out


class Emu:
    def __init__(self, img):
        self.img = img
        self.mu = mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        mu.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
        mu.mem_map(0, 0x220000)
        mu.mem_write(BASE, img)
        mu.hook_add(UC_HOOK_MEM_UNMAPPED, self._map)
        mu.hook_add(UC_HOOK_CODE, self._code)

    def _map(self, mu, access, addr, size, value, _):
        page = addr & ~0xFFF
        rng = random.Random(page ^ self.seed)
        mu.mem_map(page, 0x1000)
        mu.mem_write(page, rng.randbytes(0x1000))
        return True

    def _code(self, mu, addr, size, _):
        self.n += 1
        op = bytes(mu.mem_read(addr, 2))
        if addr in self.muls:                         # force the multiplicand: the unit number
            form = op
            if form == b'\x4c\x2e':                   # muls.l d16(a6),d0: write the unit into that stack slot
                d = struct.unpack('>h', bytes(mu.mem_read(addr + 4, 2)))[0]
                a6 = mu.reg_read(UC_M68K_REG_A6)
                mu.mem_write((a6 + d) & 0xFFFFFFFF, struct.pack('>i', self.unit))
                mu.reg_write(UC_M68K_REG_D0, 22)
            elif form == b'\xc1\xfc':                 # muls.w #22,d0
                mu.reg_write(UC_M68K_REG_D0, self.unit)
            else:                                     # muls.l d1,d0 (d1 = 22)
                mu.reg_write(UC_M68K_REG_D0, self.unit)
                mu.reg_write(UC_M68K_REG_D1, 22)
            return
        if op == b'\x4e\x90':                         # jsr (a0)
            self.calls.append((mu.reg_read(UC_M68K_REG_A0),) + tuple(mu.reg_read(r) for r in DREG))
            self._skip(addr + 2)
        elif op == b'\x4e\xb9':                       # jsr abs.l
            self.calls.append(('abs', struct.unpack('>I', bytes(mu.mem_read(addr + 2, 4)))[0]))
            self._skip(addr + 6)
        elif op[0] == 0x61:                           # bsr
            ln = 2 if op[1] not in (0, 0xFF) else (4 if op[1] == 0 else 6)
            self.calls.append(('bsr', addr))
            self._skip(addr + ln)
        elif op in (b'\x4e\x75', b'\x4e\x5e') or self.n > 400:
            mu.emu_stop()

    def _skip(self, nxt):
        self.mu.reg_write(UC_M68K_REG_D0, self.ret)
        self.mu.reg_write(UC_M68K_REG_PC, nxt)

    def run(self, site, unit, seed, ret=0):
        mu = self.mu
        self.seed, self.unit, self.n, self.calls, self.ret = seed, unit, 0, [], ret
        self.muls = table_muls(self.img)
        rng = random.Random(seed)
        for r in DREG + AREG:
            mu.reg_write(r, rng.getrandbits(32))
        stack = 0x30000000 + (seed % 64) * 0x10000
        for p in range(stack - 0x8000, stack + 0x2000, 0x1000):
            try:
                mu.mem_map(p, 0x1000)
            except Exception:
                pass
            mu.mem_write(p, random.Random(p ^ seed).randbytes(0x1000))
        mu.reg_write(UC_M68K_REG_A6, stack)
        mu.reg_write(UC_M68K_REG_A7, stack - 0x400)
        try:
            mu.emu_start(site, 0x7FFFFFFF, count=2000)
        except Exception as e:                        # an exception is a result too: compare it
            self.calls.append(('exc', str(e)))
        return self.calls, tuple(mu.reg_read(r) for r in DREG)


def compare(stock, new, label):
    fails, n = [], 0
    for site in dict.fromkeys(uc.SITES):
        for unit in range(uc.NREC):
            for seed in range(1, 7):
                for ret in (0, 1, -1):                 # skipped calls return 0, 1 or -1: both branch arms
                    n += 1
                    A = Emu(stock).run(site, unit, seed * 1000 + unit, ret)
                    Bv = Emu(new).run(site, unit, seed * 1000 + unit, ret)
                    if A != Bv:
                        fails.append(f'site {site:#x} unit {unit} seed {seed} ret {ret}: stock {A[0][:2]} new {Bv[0][:2]}')
    print(f'{label}: {n} runs ({len(uc.SITES)} sites x 45 units x 6 states x 3 call results); {len(fails)} failures')
    for f in fails[:6]:
        print('   ' + f)
    return fails


def main():
    stock = open(sys.argv[1], 'rb').read()
    new = uc.apply(stock, fill=True)
    ok = not compare(stock, new, 'compacted')
    # planted bug: leave one adda in place (that site then reads the 0xA5 fill for units >= 1)
    s, a, b = uc.ADDA[7]
    bad = bytearray(new)
    bad[a - BASE:a - BASE + 2] = bytes.fromhex(b)
    caught = bool(compare(stock, bytes(bad), f'planted bug at {a:#x}'))
    print('PASS' if ok and caught else 'FAIL')
    sys.exit(0 if ok and caught else 1)


if __name__ == '__main__':
    main()
