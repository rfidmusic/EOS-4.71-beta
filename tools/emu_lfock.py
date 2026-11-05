#!/usr/bin/env python3
"""Unicorn: Lfo1Ck / Lfo2Ck on the EOS 4.71-beta2 build 3 image (patches/lfock/lfock.s, build_lfock.py).

usage: emu_lfock.py BASE.bin       (BASE = build/eos471_beta.bin)

Builds build 3 and the LfoCk image, then:
gap clear: init and ticks match the release (Rate 0..143).
A negative gap sum scales onto the 16 lengths (full scale 4032 = 1/32). Zero or positive matches the release.
d2 and d3 survive every tick.
The Rate getter shows 128+division while the gap word is negative, and the stored byte otherwise.
The setter leaves that byte alone while the word is negative.
"""
from __future__ import annotations

import os
import random
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_lfock as build_beta2  # noqa: E402

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn.m68k_const import (
    UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4, UC_M68K_REG_A5, UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_D1,
    UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D6, UC_M68K_REG_D7,
    UC_CPU_M68K_CFV4E)

BASE, RET = 0x20000, 0x1000
RAM, STACK = 0x10000000, 0x10080000
VOICE, PARAMS = 0x10010000, 0x10011000
VOICE_IX = 0x1000134A
UI_RATE = ((1, 0x6B5B0, 0x96), (2, 0x6B65A, 0x9E))
RATE_SET_STOCK = 0x69F80
LFO1, LFO2 = VOICE + 0x188, VOICE + 0x1A8
GAP1, GAP2 = VOICE + 0x1A4, VOICE + 0x1A6
INIT1, INIT2, TICK1, TICK2 = 0x61A50, 0x61CDC, 0x61BC0, 0x61D5C
SEED, TICK, TPC, CLKMODE, CLKRATE = (
    0x1000229C, 0x10000428, 0x10000420, 0x1000042C, 0x10000434)
CLKUS, PPQ, ARPTEMPO, NOWMS = 0x1000043C, 0x1000041E, 0x1000719C, 0x10000450
CNT = 0x100003F0
DEST = 0x6344C
KTAB = (384, 192, 96, 72, 48, 36, 32, 24, 18, 16, 12, 9, 8, 6, 4, 3)
FULL = 4032  # controller CC 127 through panel amount -100 (stored byte -127)
BIND = 0x4000  # gap base lfo_bind gives a note of the preset on screen
LFO_BIND = 0x5F7E0


class Emu:
    def __init__(self, img):
        self.img = img
        self.mu = mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        mu.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
        mu.mem_map(0, 0x220000)
        mu.mem_write(BASE, img)
        mu.mem_write(RET, b"\x4e\x71")
        mu.mem_map(RAM, 0x81000)

    def w(self, a, fmt, *v):
        self.mu.mem_write(a, struct.pack(">" + fmt, *v))

    def r(self, a, fmt):
        return struct.unpack(">" + fmt, self.mu.mem_read(a, struct.calcsize(">" + fmt)))

    def call(self, fn, *args):
        sp = STACK - 0x200
        self.w(sp, "I" * (len(args) + 1), RET, *args)
        self.mu.reg_write(UC_M68K_REG_A7, sp)
        self.mu.emu_start(fn, RET, count=20000)

    def snap(self):
        return bytes(self.mu.mem_read(VOICE, 0x200)) + bytes(self.mu.mem_read(SEED, 4))

    def setup(self, seed, ms, tick=0, mode=0, tpc=20):
        self.mu.mem_write(VOICE, bytes(0x200))
        self.mu.mem_write(PARAMS, bytes(0x200))
        self.w(SEED, "I", seed)
        self.w(NOWMS, "I", ms)
        self.w(TICK, "I", tick)
        self.w(TPC, "H", tpc)
        self.w(CLKMODE, "I", mode)
        self.w(PPQ, "H", 480)
        self.w(ARPTEMPO, "I", 120)
        self.w(CLKRATE, "I", 0)
        self.w(CLKUS, "I", 0x412)
        self.w(CNT, "III", 0, ms - 100000 if ms > 100000 else 0, 0)
        self.w(0x10004089, "B", 1)
        self.w(0x100003E0, "I", 0)
        self.w(0x100003E8, "II", 0, 0)

    def lfo(self, n, rate, shape=0, delay=0, var=0, sync=0):
        self.w(PARAMS, "BBBBB", rate, shape, delay, var, sync)
        self.call(INIT1 if n == 1 else INIT2, LFO1 if n == 1 else LFO2, PARAMS)

    def tick(self, n, k=1):
        self.mu.reg_write(UC_M68K_REG_D2, 0x13579BDF)
        self.mu.reg_write(UC_M68K_REG_D3, 0x2468ACE0)
        self.call(TICK1 if n == 1 else TICK2, LFO1 if n == 1 else LFO2, k)
        self.saved = (self.mu.reg_read(UC_M68K_REG_D2), self.mu.reg_read(UC_M68K_REG_D3))

    def regs_ok(self):
        return self.saved == (0x13579BDF, 0x2468ACE0)

    def set_cord(self, n, div, bind=True):
        """Store the running sum the engine would leave for this division.

        LFO2's gap keeps the stock init value 1, so its word is one higher than the sum.
        A note of the preset on screen starts its gaps at BIND (lfo_bind); bind=False is
        a note of some other preset.
        """
        lo = 32 if div == 0 else ((div * FULL + 15) // 16) + 1
        hi = (((div + 1) * FULL - 1) // 16) + 1
        mag = (lo + hi) // 2
        word = (-mag + (1 if n == 2 else 0) + (BIND if bind else 0)) & 0xFFFF
        self.w(GAP1 if n == 1 else GAP2, "H", word)
        return mag

    def stub_voice(self):
        """0x139728 returns the test voice. The real lookup needs a loaded preset."""
        self.mu.mem_write(0x139728, bytes.fromhex("203c100100004e75"))

    def rate_call(self, fn, *args):
        self.mu.reg_write(UC_M68K_REG_D1, 0x11111111)
        self.mu.reg_write(UC_M68K_REG_D2, 0x13579BDF)
        self.mu.reg_write(UC_M68K_REG_D3, 0x2468ACE0)
        self.mu.reg_write(UC_M68K_REG_A2, 0xA2A2A2A2)
        self.call(fn, *args)
        kept = (
            self.mu.reg_read(UC_M68K_REG_D1) & 0xFFFFFFFF,
            self.mu.reg_read(UC_M68K_REG_D2) & 0xFFFFFFFF,
            self.mu.reg_read(UC_M68K_REG_D3) & 0xFFFFFFFF,
            self.mu.reg_read(UC_M68K_REG_A2) & 0xFFFFFFFF,
        )
        return self.mu.reg_read(UC_M68K_REG_D0) & 0xFFFFFFFF, kept == (
            0x11111111, 0x13579BDF, 0x2468ACE0, 0xA2A2A2A2)


def expect(T, T0, d, tpc):
    P = KTAB[d] * tpc
    return ((T - T0) % P) * 65536 // P


def cstr(img, addr):
    o = addr - BASE
    e = img.find(0, o, o + 16)
    return img[o:e].decode() if e > o else None


def main():
    with tempfile.TemporaryDirectory() as td:
        ref, out = os.path.join(td, "ref.bin"), os.path.join(td, "out.bin")
        build_beta2.build(sys.argv[1], ref, cord=False)
        syms, _ = build_beta2.build(sys.argv[1], out, cord=True)
        base_img, cord_img = open(ref, "rb").read(), open(out, "rb").read()
    B, C = Emu(base_img), Emu(cord_img)
    rnd = random.Random(0xB2C0)
    fails, n = [], 0

    n += 1
    if cord_img[0x18:0x30] != b"EOS 4.71-beta2 b3+LfoCk".ljust(24):
        fails.append(f"name {cord_img[0x18:0x30]!r}")
    for code, name, off in ((98, "Lfo1Ck", 0x1A4), (107, "Lfo2Ck", 0x1A6)):
        np, voff, fl = struct.unpack_from(">IHH", cord_img, DEST + 8 * code - BASE)
        n += 1
        if cstr(cord_img, np) != name or voff != off or fl != 0x200:
            fails.append(f"dest {code}: {cstr(cord_img, np)!r} voff={voff:#x} fl={fl:#x}")
    np, voff, fl = struct.unpack_from(">IHH", cord_img, DEST + 8 * 106 - BASE)
    n += 1
    if cstr(cord_img, np) != "Lag0in" or voff != 0x1C4 or fl != 0x200:
        fails.append(f"Lag0in moved: {cstr(cord_img, np)!r} voff={voff:#x} fl={fl:#x}")

    for case in range(80):
        lfo = 1 + case % 2
        rate = rnd.randrange(144)
        shape, sync = rnd.randrange(17), rnd.randrange(2)
        delay, var = rnd.randrange(128), rnd.randrange(128)
        seed, ms, tick0 = rnd.getrandbits(32), rnd.randrange(1, 10**6), rnd.randrange(1 << 16)
        bound = case % 4 >= 2   # a note of the preset on screen starts its gaps at BIND
        for E in (B, C):
            E.setup(seed, ms, tick=tick0)
            E.w(GAP1, "I", (BIND << 16 | BIND | 1) if bound and E is C else 1)
            E.lfo(lfo, rate, shape, delay, var, sync)

        def same():
            b, c = B.snap(), C.snap()
            return b[:0x1A4] + b[0x1A8:] == c[:0x1A4] + c[0x1A8:] if bound else b == c
        n += 1
        if not same():
            fails.append(f"gap-clear init lfo{lfo} rate {rate}")
            continue
        for step in range(8):
            k = rnd.choice([1, 2, 3])
            for E in (B, C):
                E.tick(lfo, k)
            n += 1
            if not same():
                fails.append(f"gap-clear tick lfo{lfo} rate {rate} step {step} bound {bound}")
                break

    for cc in range(128):
        mag = (cc * 127) >> 2
        d = None if mag == 0 else min(15, ((mag - 1) * 16) // FULL)
        for lfo, bound in ((1, False), (2, False), (1, True), (2, True)):
            tpc, t0 = 20, 1000
            C.setup(1, 1000, tick=t0, tpc=tpc)
            C.w(VOICE + 0x2E, "I", t0)
            C.lfo(lfo, 40, 0, 0, 0, 1)
            word = (0 if mag == 0 else -mag) + (1 if lfo == 2 else 0) + (BIND if bound else 0)
            C.w(GAP1 if lfo == 1 else GAP2, "H", word & 0xFFFF)
            T = t0 + 500
            C.w(TICK, "I", T)
            C.tick(lfo, 1)
            ph = C.r((LFO1 if lfo == 1 else LFO2) + 0x12, "H")[0]
            n += 1
            if not C.regs_ok():
                fails.append(f"cc {cc} lfo{lfo}: d2/d3 clobbered {tuple(hex(r) for r in C.saved)}")
            n += 1
            if C.r(GAP1 if lfo == 1 else GAP2, "H")[0] != word & 0xFFFF:
                fails.append(f"cc {cc} lfo{lfo} bound {bound}: gap word rewritten")
            if d is None:
                C2 = Emu(base_img)
                C2.setup(1, 1000, tick=t0, tpc=tpc)
                C2.w(VOICE + 0x2E, "I", t0)
                C2.lfo(lfo, 40, 0, 0, 0, 1)
                C2.w(GAP1, "I", 1)
                C2.w(TICK, "I", T)
                C2.tick(lfo, 1)
                if ph != C2.r((LFO1 if lfo == 1 else LFO2) + 0x12, "H")[0]:
                    fails.append(f"cc {cc} lfo{lfo}: idle diverged from beta2")
                continue
            e = expect(T, t0, d, tpc)
            if ph != e:
                fails.append(f"cc {cc} lfo{lfo}: phase {ph} != div {d} ({e})")

    for case in range(80):
        lfo, d = 1 + case % 2, rnd.randrange(16)
        tpc, t0 = 20, rnd.randrange(0, 1 << 20)
        C.setup(rnd.getrandbits(32), 1000, tick=t0, mode=0, tpc=tpc)
        C.w(VOICE + 0x2E, "I", t0)
        C.lfo(lfo, rnd.randrange(128), 0, 0, 0, 1)
        C.set_cord(lfo, d)
        p = LFO1 if lfo == 1 else LFO2
        T = t0
        for step in range(8):
            T += rnd.randrange(0, 4 * tpc)
            C.w(TICK, "I", T)
            C.tick(lfo, 1)
            ph = C.r(p + 0x12, "H")[0]
            e = expect(T, t0, d, tpc)
            n += 1
            if not C.regs_ok():
                fails.append(f"cord lfo{lfo} div {d}: d2/d3 clobbered")
                break
            if ph != e:
                fails.append(f"cord lfo{lfo} div {d} T {T}: phase {ph} != {e}")
                break

    for case in range(80):
        lfo = 1 + case % 2
        d_rate, d_cord = rnd.randrange(16), rnd.randrange(16)
        if d_rate == d_cord:
            d_cord = (d_cord + 1) & 15
        tpc, t0 = 20, rnd.randrange(0, 1 << 16)
        C.setup(1, 2000, tick=t0, tpc=tpc)
        C.w(VOICE + 0x2E, "I", t0)
        C.lfo(lfo, 128 + d_rate, 0, 0, 0, 0)
        C.set_cord(lfo, d_cord)
        p = LFO1 if lfo == 1 else LFO2
        T = t0 + rnd.randrange(1, 4000)
        C.w(TICK, "I", T)
        C.tick(lfo, 1)
        ph = C.r(p + 0x12, "H")[0]
        if not C.regs_ok():
            fails.append(f"override lfo{lfo}: d2/d3 clobbered")
        e_cord = expect(T, t0, d_cord, tpc)
        e_rate = expect(T, t0, d_rate, tpc)
        n += 1
        if ph != e_cord:
            fails.append(f"override lfo{lfo}: phase {ph} != cord {e_cord} (rate would be {e_rate})")

    for addr, _off in ((0x6B5B0, 0x96), (0x6B65A, 0x9E)):
        get, setter = struct.unpack_from(">II", base_img, addr - BASE + 0x1A)
        n += 1
        if (get, setter) != (0, RATE_SET_STOCK):
            fails.append(f"release Rate {addr:#x} getter/setter {get:#x}/{setter:#x}")
        get, setter = struct.unpack_from(">II", cord_img, addr - BASE + 0x1A)
        n += 1
        if (get, setter) != (0, syms["rate_set"]):
            fails.append(f"cord Rate {addr:#x} getter/setter {get:#x}/{setter:#x}")

    C.stub_voice()
    for lfo, desc, off in UI_RATE:
        for div in range(16):
            C.mu.mem_write(VOICE, bytes(0x200))
            C.w(VOICE_IX, "H", 0)
            C.w(VOICE + off, "B", 40)
            C.set_cord(lfo, div)
            gap = C.r(GAP1 if lfo == 1 else GAP2, "H")[0]
            C.w(0x100003E8 + (0 if lfo == 1 else 2), "H", (gap - BIND) & 0xFFFF)
            C.w(0x1000337C + 8, "II", 0, 0)
            C.rate_call(syms["rate_set"], desc, 99)
            n += 1
            if C.r(VOICE + off, "B")[0] != 40 or C.r(0x1000337C + 8, "II") != (0, 0):
                fails.append(f"rate_set lfo{lfo} div {div} wrote {C.r(VOICE + off, 'B')[0]} "
                             f"queue {C.r(0x1000337C + 8, 'II')}")

    # The panel shows the edited voice's Rate byte. While a note is sounding, that byte
    # follows the cord and the original is kept aside.
    C.w(0x100040AC, "I", VOICE)
    for lfo, off, div, stored in ((1, 0x96, 3, 40), (2, 0x9E, 7, 55)):
        C.setup(1, 1000, tick=1000)
        C.w(0x100040AC, "I", VOICE)
        C.lfo(lfo, stored, 0, 0, 0, 1)
        C.w(VOICE + off, "B", stored)
        C.set_cord(lfo, div)
        C.tick(lfo, 1)
        n += 1
        if C.r(VOICE + off, "B")[0] != 128 + div:
            fails.append(f"publish lfo{lfo}: rate {C.r(VOICE + off, 'B')[0]}")
        held = C.mu.mem_read(0x100003EC + lfo - 1, 1)[0]
        n += 1
        if held != stored:
            fails.append(f"publish lfo{lfo}: held {held}")
        C.w(GAP1 if lfo == 1 else GAP2, "H", BIND + (0 if lfo == 1 else 1))
        C.tick(lfo, 1)
        n += 1
        if C.r(VOICE + off, "B")[0] != stored:
            fails.append(f"restore lfo{lfo}: rate {C.r(VOICE + off, 'B')[0]}")
        n += 1
        if C.r(0x100003E8 + 2 * (lfo - 1), "H")[0] != lfo - 1:
            fails.append(f"restore lfo{lfo}: mirror {C.r(0x100003E8 + 2 * (lfo - 1), 'H')[0]:#x}")

    # Opening an LFO page reads the Rate byte. A later change asks that page to draw again.
    C.mu.mem_map(0x102C0000, 0x10000)
    C.mu.mem_write(0xCC1CC, bytes.fromhex("52b910080f004e75"))
    C.w(0x10080F00, "I", 0)
    C.w(0x1000415C, "I", 0x12)
    C.mu.mem_write(0x102C1000, bytes(0x40))
    C.w(0x102C327C + 7 * 4, "I", 0x102C1000)
    C.setup(1, 1000, tick=1000)
    C.w(0x10004D64, "I", 0x102C1000)
    C.w(0x100040AC, "I", VOICE)
    C.lfo(1, 40, 0, 0, 0, 1)
    C.w(VOICE + 0x96, "B", 40)
    C.set_cord(1, 3)
    C.tick(1, 1)
    n += 1
    draws = C.r(0x10080F00, "I")[0]
    if draws != 1:
        fails.append(f"refresh on change: {draws}")
    C.tick(1, 1)
    n += 1
    draws = C.r(0x10080F00, "I")[0]
    if draws != 1:
        fails.append(f"refresh repeated: {draws}")
    C.set_cord(1, 4)
    C.tick(1, 1)
    n += 1
    draws = C.r(0x10080F00, "I")[0]
    if draws != 2:
        fails.append(f"refresh on a new division: {draws}")
    C.w(0x1000415C, "I", 0)
    C.set_cord(1, 5)
    C.tick(1, 1)
    n += 1
    draws = C.r(0x10080F00, "I")[0]
    if draws != 2:
        fails.append(f"refresh off the LFO page: {draws}")
    C.w(0x10004D64, "I", 0)
    C.w(0x1000415C, "I", 0x12)
    C.set_cord(1, 6)
    C.tick(1, 1)
    n += 1
    if C.r(0x10080F00, "I")[0] != draws:
        fails.append(f"refresh while another screen is up: {C.r(0x10080F00, 'I')[0]}")
    C.w(0x10004D64, "I", 0x102C1000)

    # The cached object is the field list. Rate is the container's first child. Its enable
    # byte is the same switch the Tempo field uses: 0 greys it, 1 draws it normally.
    SCREEN, BOX, WIDGET = 0x102C1000, 0x102C1180, 0x102C1200
    C.w(SCREEN, "I", 0xB2D1C)
    C.w(SCREEN + 0x30, "I", BOX)
    C.w(SCREEN + 0x38, "I", 0x102C1400)
    C.w(BOX, "I", 0x10D300)
    C.w(BOX + 0x0C, "I", WIDGET)
    C.mu.mem_write(WIDGET, bytes(0x40))
    C.w(WIDGET + 0x3A, "B", 1)
    C.w(WIDGET + 0x24, "B", 1)
    C.w(0x1000415C, "I", 0x12)
    C.tick(1, 1)
    n += 1
    if C.r(WIDGET + 0x3A, "B")[0] != 0 or C.r(WIDGET + 0x24, "B")[0] != 0:
        fails.append(f"grey lfo1: enable {C.r(WIDGET + 0x3A, 'B')[0]} focus {C.r(WIDGET + 0x24, 'B')[0]}")
    C.w(WIDGET + 0x3A, "B", 1)
    C.w(WIDGET + 0x24, "B", 1)
    C.tick(1, 1)
    n += 1
    if C.r(WIDGET + 0x3A, "B")[0] != 0 or C.r(WIDGET + 0x24, "B")[0] != 0:
        fails.append(f"grey rebuilt: enable {C.r(WIDGET + 0x3A, 'B')[0]} focus {C.r(WIDGET + 0x24, 'B')[0]}")
    draws = C.r(0x10080F00, "I")[0]
    C.tick(1, 1)
    n += 1
    if C.r(WIDGET + 0x3A, "B")[0] != 0 or C.r(0x10080F00, "I")[0] != draws:
        fails.append(f"grey held steady: enable {C.r(WIDGET + 0x3A, 'B')[0]}")
    C.w(GAP1, "H", BIND)
    C.tick(1, 1)
    n += 1
    if C.r(WIDGET + 0x3A, "B")[0] != 1:
        fails.append(f"grey released: {C.r(WIDGET + 0x3A, 'B')[0]}")
    C.w(0x1000415C, "I", 0x13)
    C.w(0x102C327C + 8 * 4, "I", 0x102C1000)
    C.mu.mem_write(WIDGET, bytes(0x40))
    C.w(WIDGET + 0x3A, "B", 1)
    C.set_cord(1, 2)
    C.tick(1, 1)
    n += 1
    if C.r(WIDGET + 0x3A, "B")[0] != 1:
        fails.append(f"lfo1 tick greys the lfo2 page: {C.r(WIDGET + 0x3A, 'B')[0]}")
    C.lfo(2, 40, 0, 0, 0, 1)
    C.set_cord(2, 6)
    C.tick(2, 1)
    n += 1
    if C.r(WIDGET + 0x3A, "B")[0] != 0:
        fails.append(f"grey lfo2: {C.r(WIDGET + 0x3A, 'B')[0]}")

    # Transport does not release the cord. A quiet external clock and a long internal gap
    # leave the division sounding, the Rate byte at 128+div, and the knob blocked.
    n += 1
    if struct.unpack_from(">I", base_img, 0x68A68 - BASE)[0] != 0x66B38:
        fails.append("nocord image moved the #$40 stub")
    n += 1
    hooked = b"\x4e\xb9" + struct.pack(">I", syms["rate_enter"]) + b"\x4e\x71"
    if cord_img[0xCDAC2 - BASE:0xCDAC2 - BASE + 8] != hooked:
        fails.append("LFO page opener was not retargeted")
    n += 1
    if base_img[0xCDAC2 - BASE:0xCDAC2 - BASE + 8] != bytes.fromhex("23c71000415cdc87"):
        fails.append("nocord image retargeted the LFO page opener")
    n += 1
    hooked = b"\x4e\xb9" + struct.pack(">I", syms["rate_built"]) + b"\x4e\x71"
    if cord_img[0xCDB8C - BASE:0xCDB8C - BASE + 8] != hooked:
        fails.append("LFO page cache store was not retargeted")
    n += 1
    if base_img[0xCDB8C - BASE:0xCDB8C - BASE + 8] != bytes.fromhex("298d6c004fef0014"):
        fails.append("nocord image retargeted the LFO page cache store")

    # A page built for the first time comes up with Rate enabled. The cache store at the end
    # of that build greys it when this LFO's gap copy is negative, records the page as the
    # one on display, and does the displaced lea 20(sp),sp.
    def built(lfo, mirror):
        slot = 0x102C327C + (6 + lfo) * 4
        C.w(slot, "I", 0)
        C.w(0x10004D64, "I", OTHER)
        C.w(0x1000415C, "I", 0x11 + lfo)
        C.w(0x100003E8 + 2 * (lfo - 1), "H", mirror & 0xFFFF)
        C.mu.mem_write(WIDGET, bytes(0x40))
        C.w(WIDGET + 0x3A, "B", 1)
        C.w(WIDGET + 0x24, "B", 1)
        sp = STACK - 0x200
        C.w(sp, "I" * 6, RET, 0xDEAD0001, 0xDEAD0002, 0xDEAD0003, 0xDEAD0004, 0xDEAD0005)
        C.mu.reg_write(UC_M68K_REG_A7, sp)
        C.mu.reg_write(UC_M68K_REG_A4, 0x102C327C)
        C.mu.reg_write(UC_M68K_REG_A5, SCREEN)
        C.mu.reg_write(UC_M68K_REG_D6, 6 + lfo)
        C.mu.reg_write(UC_M68K_REG_D2, 0x13579BDF)
        C.mu.emu_start(syms["rate_built"], RET, count=20000)
        return (C.r(slot, "I")[0], C.r(0x10004D64, "I")[0],
                C.mu.reg_read(UC_M68K_REG_A7) & 0xFFFFFFFF, C.mu.reg_read(UC_M68K_REG_D2) & 0xFFFFFFFF)

    OTHER = 0x102C2000
    for lfo in (1, 2):
        draws = C.r(0x10080F00, "I")[0]
        slot, cur, sp, d2 = built(lfo, -40 + (lfo - 1))
        n += 1
        if slot != SCREEN or cur != SCREEN or sp != STACK - 0x200 + 24 or d2 != 0x13579BDF \
                or C.r(WIDGET + 0x3A, "B")[0] != 0 or C.r(WIDGET + 0x24, "B")[0] != 0 \
                or C.r(0x10080F00, "I")[0] != draws + 1:
            fails.append(f"fresh lfo{lfo} page held: slot {slot:#x} current {cur:#x} sp {sp:#x} "
                         f"enable {C.r(WIDGET + 0x3A, 'B')[0]} draws {C.r(0x10080F00, 'I')[0] - draws}")
        draws = C.r(0x10080F00, "I")[0]
        slot, cur, sp, d2 = built(lfo, lfo - 1)
        n += 1
        if slot != SCREEN or cur != SCREEN or sp != STACK - 0x200 + 24 \
                or C.r(WIDGET + 0x3A, "B")[0] != 1 or C.r(0x10080F00, "I")[0] != draws:
            fails.append(f"fresh lfo{lfo} page released: enable {C.r(WIDGET + 0x3A, 'B')[0]} "
                         f"draws {C.r(0x10080F00, 'I')[0] - draws}")
    n += 1
    if cord_img[0xCD924 - BASE:0xCD924 - BASE + 8] != bytes.fromhex("6100fcfa4fef000c"):
        fails.append("cord image retargeted the other page shower")
    for addr, stock in (
        (0x135F2C, bytes.fromhex("4eb900020136")),
        (0x135F34, bytes.fromhex("4eb900136b20")),
        (0x135F3C, bytes.fromhex("4eb900136b28")),
    ):
        n += 1
        if cord_img[addr - BASE:addr - BASE + 6] != stock:
            fails.append(f"realtime {addr:#x} was retargeted")

    LASTMS = 0x100003F4

    def cord_phase(lfo, rate, mode, gap):
        ms, t0, tpc = 5000, 1000, 20
        E = Emu(cord_img)
        E.setup(1, ms, tick=t0, mode=mode, tpc=tpc)
        E.w(LASTMS, "I", ms - gap)
        E.w(VOICE + 0x2E, "I", t0)
        E.w(0x100040AC, "I", VOICE)
        E.w(0x1000415C, "I", 0)
        E.lfo(lfo, rate, 0, 0, 0, 0)
        E.w(VOICE + (0x96 if lfo == 1 else 0x9E), "B", rate)
        E.set_cord(lfo, 9)
        E.w(TICK, "I", t0 + 400)
        E.tick(lfo, 1)
        p = LFO1 if lfo == 1 else LFO2
        return E.r(p + 0x12, "H")[0], E.r(VOICE + (0x96 if lfo == 1 else 0x9E), "B")[0], E

    def ref_phase(lfo, rate, mode, gap):
        ms, t0, tpc = 5000, 1000, 20
        E = Emu(base_img)
        E.setup(1, ms, tick=t0, mode=mode, tpc=tpc)
        E.w(LASTMS, "I", ms - gap)
        E.w(VOICE + 0x2E, "I", t0)
        E.lfo(lfo, rate, 0, 0, 0, 0)
        E.w(TICK, "I", t0 + 400)
        E.tick(lfo, 1)
        return E.r((LFO1 if lfo == 1 else LFO2) + 0x12, "H")[0]

    for lfo, rate, mode, gap, label in (
        (1, 40, 1, 10, "external clock"),
        (2, 17, 1, 1000, "quiet external clock"),
        (1, 40, 0, 4000, "internal tempo"),
    ):
        ph, shown, E = cord_phase(lfo, rate, mode, gap)
        want = ref_phase(lfo, 128 + 9, mode, gap)
        n += 1
        if ph != want or shown != 128 + 9 or not E.regs_ok():
            fails.append(f"{label} lfo{lfo}: phase {ph} != {want}, rate {shown}")

    C.setup(1, 5000, tick=1000, mode=1, tpc=20)
    C.w(LASTMS, "I", 5000 - 1000)
    C.w(0x100040AC, "I", VOICE)
    C.w(0x1000415C, "I", 0x12)
    C.w(0x102C327C + 7 * 4, "I", SCREEN)
    C.w(VOICE + 0x2E, "I", 1000)
    C.lfo(1, 40, 0, 0, 0, 0)
    C.w(VOICE + 0x96, "B", 40)
    C.set_cord(1, 3)
    C.w(WIDGET + 0x3A, "B", 1)
    C.tick(1, 1)
    C.tick(1, 1)
    n += 1
    if C.r(VOICE + 0x96, "B")[0] != 128 + 3 or C.r(WIDGET + 0x3A, "B")[0] != 0 or not C.regs_ok():
        fails.append(f"quiet keeps the cord: rate {C.r(VOICE + 0x96, 'B')[0]} "
                     f"enable {C.r(WIDGET + 0x3A, 'B')[0]}")
    C.w(0x1000337C + 8, "II", 0, 0)
    C.rate_call(syms["rate_set"], 0x6B5B0, 77)
    n += 1
    if C.r(0x1000337C + 8, "II") != (0, 0) or C.r(VOICE + 0x96, "B")[0] != 128 + 3:
        fails.append(f"rate_set while held queued {C.r(0x1000337C + 8, 'II')} "
                     f"rate {C.r(VOICE + 0x96, 'B')[0]}")

    # The Cords page writes the preset table. The gap word stays at the last note's sum
    # until the next note, so opening the LFO page has to release from the table itself.
    def plant(*cords):
        raw = bytearray(96)
        for i, (src, dst, amt) in enumerate(cords):
            struct.pack_into(">BBb", raw, 4 * i, src, dst, amt)
        C.mu.mem_write(VOICE + 0xBC, bytes(raw))

    def engage(lfo, div):
        off = 0x96 if lfo == 1 else 0x9E
        C.w(0x100003EC + lfo - 1, "B", 0xFF)
        C.w(0x1000415C, "I", 0x11 + lfo)
        C.w(0x102C327C + (6 + lfo) * 4, "I", SCREEN)
        C.w(0x10004D64, "I", SCREEN)
        C.lfo(lfo, 40, 0, 0, 0, 0)
        C.w(VOICE + off, "B", 40)
        C.set_cord(lfo, div)
        C.w(WIDGET + 0x3A, "B", 1)
        C.tick(lfo, 1)

    def released(lfo, saved=40):
        off = 0x96 if lfo == 1 else 0x9E
        return C.r(VOICE + off, "B")[0] == saved and C.r(WIDGET + 0x3A, "B")[0] == 1

    def held(lfo, div):
        off = 0x96 if lfo == 1 else 0x9E
        return C.r(VOICE + off, "B")[0] == 128 + div and C.r(WIDGET + 0x3A, "B")[0] == 0

    # The hook runs while the previous screen (the Cords page) is still the current object.
    OTHER = 0x102C2000

    def open_page():
        C.w(0x10004D64, "I", OTHER)
        C.call(syms["rate_open"])

    C.w(0x1000415C, "I", 0)
    open_page()
    n += 1
    if not held(1, 3) or C.r(0x10004D64, "I")[0] != OTHER:
        fails.append("opening another page released Rate")
    C.w(0x1000415C, "I", 0x12)
    plant()
    open_page()
    n += 1
    if C.r(0x10004D64, "I")[0] != SCREEN:
        fails.append(f"open did not make the LFO page current: {C.r(0x10004D64, 'I')[0]:#x}")
    n += 1
    if not released(1):
        fails.append(f"removed cord: rate {C.r(VOICE + 0x96, 'B')[0]} "
                     f"enable {C.r(WIDGET + 0x3A, 'B')[0]}")
    engage(1, 3)
    plant((8, 98, -100))
    C.w(GAP1, "H", BIND)
    open_page()
    n += 1
    if not held(1, 3):
        fails.append("negative amount with a cleared gap released Rate")
    plant((8, 98, 0))
    C.set_cord(1, 3)
    open_page()
    n += 1
    if not released(1):
        fails.append(f"amount 0: rate {C.r(VOICE + 0x96, 'B')[0]} "
                     f"enable {C.r(WIDGET + 0x3A, 'B')[0]}")
    engage(1, 5)
    plant((8, 98, 40))
    open_page()
    n += 1
    if not released(1):
        fails.append("positive amount left Rate grey")
    engage(1, 3)
    plant((8, 0, -100))
    open_page()
    n += 1
    if not released(1):
        fails.append("removed Lfo1Ck target left Rate grey")
    engage(1, 3)
    plant((8, 98, 0), (9, 98, -40))
    open_page()
    n += 1
    if not held(1, 3):
        fails.append("a second negative cord released Rate")
    plant((8, 98, 0), (9, 50, -40))
    open_page()
    n += 1
    if not released(1):
        fails.append("retargeting the second cord left Rate grey")
    engage(2, 6)
    plant((8, 107, -80))
    C.w(VOICE + 0x96, "B", 22)
    open_page()
    n += 1
    if not held(2, 6) or C.r(VOICE + 0x96, "B")[0] != 22:
        fails.append(f"lfo2 still held: rate {C.r(VOICE + 0x9E, 'B')[0]} "
                     f"lfo1 {C.r(VOICE + 0x96, 'B')[0]}")
    plant((8, 107, 0))
    open_page()
    n += 1
    if not released(2) or C.r(VOICE + 0x96, "B")[0] != 22:
        fails.append(f"lfo2 amount 0: rate {C.r(VOICE + 0x9E, 'B')[0]} "
                     f"lfo1 {C.r(VOICE + 0x96, 'B')[0]}")
    engage(1, 3)
    plant()
    C.mu.reg_write(UC_M68K_REG_D2, 0x13579BDF)
    C.mu.reg_write(UC_M68K_REG_D7, 0x12)
    C.mu.reg_write(UC_M68K_REG_D6, 0xFFFFFFF5)
    C.w(0x10004D64, "I", OTHER)
    C.call(syms["rate_enter"])
    n += 1
    d2 = C.mu.reg_read(UC_M68K_REG_D2) & 0xFFFFFFFF
    d6 = C.mu.reg_read(UC_M68K_REG_D6) & 0xFFFFFFFF
    d7 = C.mu.reg_read(UC_M68K_REG_D7) & 0xFFFFFFFF
    if not released(1) or d2 != 0x13579BDF or d6 != 7 or d7 != 0x12 or C.r(0x1000415C, "I")[0] != 0x12:
        fails.append(f"page entry left rate {C.r(VOICE + 0x96, 'B')[0]} "
                     f"enable {C.r(WIDGET + 0x3A, 'B')[0]} d2 {d2:#x} d6 {d6:#x} d7 {d7:#x}")
    engage(1, 4)
    plant((8, 98, -20))
    C.mu.reg_write(UC_M68K_REG_D7, 0x12)
    C.mu.reg_write(UC_M68K_REG_D6, 0xFFFFFFF5)
    C.w(0x10004D64, "I", OTHER)
    C.call(syms["rate_enter"])
    n += 1
    d6 = C.mu.reg_read(UC_M68K_REG_D6) & 0xFFFFFFFF
    if not held(1, 4) or d6 != 7:
        fails.append(f"page entry with a negative amount released, d6 {d6:#x}")

    # The preset the panel edits and the voice a note is playing are different objects.
    # Publishing writes the Rate byte and nothing past the 284-byte header.
    PRESET, OUTER = 0x10018000, 0x10020000
    runtime = OUTER + 0x1FE
    C.setup(1, 1000, tick=1000)
    C.mu.mem_write(PRESET, b"\xA5" * 0x200)
    C.w(PRESET + 0x96, "B", 40)
    C.w(0x100040AC, "I", PRESET)
    C.w(0x1000415C, "I", 0)
    C.w(OUTER + 0x4A, "I", 0x11111111)
    C.w(OUTER + 0x4E, "I", 0x22222222)
    C.w(PARAMS, "BBBBB", 40, 0, 0, 0, 1)
    C.call(INIT1, runtime, PARAMS)
    C.set_cord(1, 3)
    gap = C.r(GAP1, "H")[0]
    C.w(runtime + 0x1C, "H", gap)
    C.mu.reg_write(UC_M68K_REG_D2, 0x13579BDF)
    C.mu.reg_write(UC_M68K_REG_D3, 0x2468ACE0)
    C.call(TICK1, runtime, 1)
    n += 1
    tail = bytes(C.mu.mem_read(PRESET + 0x11C, 0x200 - 0x11C))
    if C.r(PRESET + 0x96, "B")[0] != 128 + 3 or tail != b"\xA5" * (0x200 - 0x11C) \
            or C.r(runtime + 0x1C, "H")[0] != gap or C.r(0x100003E8, "H")[0] != (gap - BIND) & 0xFFFF \
            or C.r(OUTER + 0x4A, "I")[0] != 0x11111111 or C.r(OUTER + 0x4E, "I")[0] != 0x22222222:
        fails.append(f"separate preset: rate {C.r(PRESET + 0x96, 'B')[0]} "
                     f"mirror {C.r(0x100003E8, 'H')[0]:#x}")

    # Editing a different preset drops the saved Rate. The previous preset keeps its division.
    VB = 0x10014000
    C.setup(1, 1000, tick=1000)
    C.w(0x100040AC, "I", VOICE)
    C.w(0x1000415C, "I", 0)
    C.lfo(1, 40, 0, 0, 0, 1)
    C.w(VOICE + 0x96, "B", 40)
    C.set_cord(1, 3)
    C.tick(1, 1)
    C.mu.mem_write(VB, bytes(0x200))
    C.w(VB + 0x96, "B", 10)
    C.w(0x100040AC, "I", VB)
    C.tick(1, 1)
    n += 1
    if C.r(VB + 0x96, "B")[0] != 128 + 3 or C.r(0x100003EC, "B")[0] != 10 \
            or C.r(VOICE + 0x96, "B")[0] != 128 + 3:
        fails.append(f"voice switch: new {C.r(VB + 0x96, 'B')[0]} held {C.r(0x100003EC, 'B')[0]} "
                     f"old {C.r(VOICE + 0x96, 'B')[0]}")

    ZONE = 0x10016000
    C.mu.mem_write(ZONE, b"\x5A" * 22)
    C.w(0x10004089, "B", 0)
    C.w(0x100040AC, "I", ZONE)
    C.tick(1, 1)
    n += 1
    if bytes(C.mu.mem_read(ZONE, 22)) != b"\x5A" * 22:
        fails.append("zone publish wrote past the zone")

    # The note start writes long 1 across both gap words. lfo_bind writes 0x40004001 instead
    # when the note's preset is the one on screen. a3 = preset+0x9C, a4 = amp+0x1A4 there.
    n += 1
    if cord_img[LFO_BIND - BASE:LFO_BIND - BASE + 6] != b"\x4e\xb9" + struct.pack(">I", syms["lfo_bind"]):
        fails.append("note start gap init was not retargeted")
    n += 1
    if base_img[LFO_BIND - BASE:LFO_BIND - BASE + 6] != bytes.fromhex("28fc00000001"):
        fails.append("nocord image retargeted the note start gap init")
    AMP = 0x10022000
    for edited, want in ((VOICE, BIND << 16 | BIND | 1), (VB, 1)):
        C.w(0x100040AC, "I", edited)
        C.w(AMP + 0x1A4, "I", 0xDEADBEEF)
        C.mu.reg_write(UC_M68K_REG_A3, VOICE + 0x9C)
        C.mu.reg_write(UC_M68K_REG_A4, AMP + 0x1A4)
        C.mu.reg_write(UC_M68K_REG_A5, AMP)
        C.mu.reg_write(UC_M68K_REG_D7, 0x77777777)
        C.call(syms["lfo_bind"])
        n += 1
        if C.r(AMP + 0x1A4, "I")[0] != want or C.mu.reg_read(UC_M68K_REG_A4) & 0xFFFFFFFF != AMP + 0x1A8 \
                or C.mu.reg_read(UC_M68K_REG_A3) & 0xFFFFFFFF != VOICE + 0x9C \
                or C.mu.reg_read(UC_M68K_REG_A5) & 0xFFFFFFFF != AMP \
                or C.mu.reg_read(UC_M68K_REG_D7) & 0xFFFFFFFF != 0x77777777:
            fails.append(f"lfo_bind edited {edited:#x}: gaps {C.r(AMP + 0x1A4, 'I')[0]:#x} "
                         f"a4 {C.mu.reg_read(UC_M68K_REG_A4) & 0xFFFFFFFF:#x}")

    # A note of another preset sounds its division and leaves the readout alone: the Rate
    # byte, the saved Rate, the gap copy and the widget stay as they were, and the knob works.
    for lfo, off in ((1, 0x96), (2, 0x9E)):
        E = Emu(cord_img)
        E.mu.mem_map(0x102C0000, 0x10000)
        E.mu.mem_write(0xCC1CC, bytes.fromhex("52b910080f004e75"))
        E.mu.mem_write(RATE_SET_STOCK, bytes.fromhex("52b910080f044e75"))
        E.w(0x10080F00, "II", 0, 0)
        E.w(SCREEN, "I", 0xB2D1C)
        E.w(SCREEN + 0x30, "I", BOX)
        E.w(BOX, "I", 0x10D300)
        E.w(BOX + 0x0C, "I", WIDGET)
        E.mu.mem_write(WIDGET, bytes(0x40))
        E.w(WIDGET + 0x3A, "B", 1)
        E.w(0x1000415C, "I", 0x11 + lfo)
        E.w(0x102C327C + (6 + lfo) * 4, "I", SCREEN)
        E.w(0x10004D64, "I", SCREEN)
        tpc, t0 = 20, 1000
        E.setup(1, 1000, tick=t0, tpc=tpc)
        E.w(0x100040AC, "I", VOICE)
        E.w(VOICE + 0x2E, "I", t0)
        E.lfo(lfo, 40, 0, 0, 0, 1)
        E.w(VOICE + off, "B", 40)
        E.w(0x100003EC + lfo - 1, "B", 0xFF)
        E.set_cord(lfo, 5, bind=False)
        T = t0 + 700
        E.w(TICK, "I", T)
        E.tick(lfo, 1)
        ph = E.r((LFO1 if lfo == 1 else LFO2) + 0x12, "H")[0]
        n += 1
        if ph != expect(T, t0, 5, tpc) or not E.regs_ok():
            fails.append(f"other preset lfo{lfo}: phase {ph} != {expect(T, t0, 5, tpc)}")
        n += 1
        if E.r(VOICE + off, "B")[0] != 40 or E.r(0x100003EC + lfo - 1, "B")[0] != 0xFF \
                or E.r(0x100003E8, "I")[0] != 0 or E.r(WIDGET + 0x3A, "B")[0] != 1 \
                or E.r(0x10080F00, "I")[0] != 0:
            fails.append(f"other preset lfo{lfo} moved the readout: rate {E.r(VOICE + off, 'B')[0]} "
                         f"held {E.r(0x100003EC + lfo - 1, 'B')[0]:#x} mirror {E.r(0x100003E8, 'I')[0]:#x} "
                         f"enable {E.r(WIDGET + 0x3A, 'B')[0]} draws {E.r(0x10080F00, 'I')[0]}")
        E.rate_call(syms["rate_set"], 0x6B5B0 if lfo == 1 else 0x6B65A, 77)
        n += 1
        if E.r(0x10080F04, "I")[0] != 1:
            fails.append(f"other preset lfo{lfo}: knob blocked")
        # the same note, when it belongs to the preset on screen
        E.set_cord(lfo, 5)
        E.tick(lfo, 1)
        n += 1
        if E.r(VOICE + off, "B")[0] != 128 + 5 or E.r(0x100003EC + lfo - 1, "B")[0] != 40 \
                or E.r(WIDGET + 0x3A, "B")[0] != 0 or E.r(0x10080F00, "I")[0] != 2:
            fails.append(f"own preset lfo{lfo}: rate {E.r(VOICE + off, 'B')[0]} "
                         f"held {E.r(0x100003EC + lfo - 1, 'B')[0]} enable {E.r(WIDGET + 0x3A, 'B')[0]} "
                         f"draws {E.r(0x10080F00, 'I')[0]}")
        E.rate_call(syms["rate_set"], 0x6B5B0 if lfo == 1 else 0x6B65A, 77)
        n += 1
        if E.r(0x10080F04, "I")[0] != 1:
            fails.append(f"own preset lfo{lfo}: knob not blocked")

    # Two full-depth cords on one LFO still read as the preset on screen; two full-depth
    # cords the other way on another preset's note still read as that.
    for lfo in (1, 2):
        E = Emu(cord_img)
        E.setup(1, 1000, tick=1000)
        E.w(0x100040AC, "I", VOICE)
        E.lfo(lfo, 40, 0, 0, 0, 1)
        E.w(VOICE + (0x96 if lfo == 1 else 0x9E), "B", 40)
        E.w(GAP1 if lfo == 1 else GAP2, "H", (BIND - 2 * FULL + (lfo - 1)) & 0xFFFF)
        E.tick(lfo, 1)
        n += 1
        if E.r(VOICE + (0x96 if lfo == 1 else 0x9E), "B")[0] != 128 + 15 or not E.regs_ok():
            fails.append(f"two cords lfo{lfo}: rate {E.r(VOICE + (0x96 if lfo == 1 else 0x9E), 'B')[0]}")
        E.w(GAP1 if lfo == 1 else GAP2, "H", 2 * FULL + (lfo - 1))
        E.w(VOICE + (0x96 if lfo == 1 else 0x9E), "B", 40)
        E.w(0x100003E8, "I", 0)
        E.tick(lfo, 1)
        n += 1
        if E.r(VOICE + (0x96 if lfo == 1 else 0x9E), "B")[0] != 40 or E.r(0x100003E8, "I")[0] != 0:
            fails.append(f"two positive cords lfo{lfo}: rate {E.r(VOICE + (0x96 if lfo == 1 else 0x9E), 'B')[0]} "
                         f"mirror {E.r(0x100003E8, 'I')[0]:#x}")

    print(f"{n} checks; {len(fails)} failures")
    for f in fails[:25]:
        print("  " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: emu_lfock.py BASE.bin")
    main()
