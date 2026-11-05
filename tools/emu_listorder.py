#!/usr/bin/env python3
"""Unicorn: cord destination list order (patches/lfock/list_order.s, build_lfock.py).

usage: emu_listorder.py BASE.bin       (BASE = build/eos471_beta.bin)

Builds the release and the LfoCk image. On the release, Lfo2Trg is followed by Lag0in.
On the LfoCk image every visible index round-trips, and the list runs
Lfo1Ck, Lfo2Rt, Lfo2Trg, Lfo2Ck, Lag0in, Lag1in. The name shown is still the
stored id's name.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_lfock as build_beta2  # noqa: E402

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN
from unicorn.m68k_const import (
    UC_M68K_REG_A2, UC_M68K_REG_A3, UC_M68K_REG_A4, UC_M68K_REG_A5, UC_M68K_REG_A7,
    UC_M68K_REG_D1, UC_M68K_REG_D2, UC_M68K_REG_D3, UC_M68K_REG_D4, UC_M68K_REG_D5,
    UC_M68K_REG_D0, UC_M68K_REG_D6, UC_M68K_REG_D7, UC_CPU_M68K_CFV4E,
)

BASE, RET = 0x20000, 0x1000
STACK = 0x10080000
FWD_D1, FWD_STK, REV, NAME = 0x62D00, 0x62D60, 0x62C98, 0x62DC4
SENT = {
    UC_M68K_REG_D2: 0x11111111, UC_M68K_REG_D3: 0x22222222, UC_M68K_REG_D4: 0x33333333,
    UC_M68K_REG_D5: 0x55555555, UC_M68K_REG_D6: 0x66666666, UC_M68K_REG_D7: 0x77777777,
    UC_M68K_REG_A2: 0xA2A2A2A2, UC_M68K_REG_A3: 0xA3A3A3A3, UC_M68K_REG_A4: 0xA4A4A4A4,
    UC_M68K_REG_A5: 0xA5A5A5A5,
}


class Emu:
    def __init__(self, img):
        self.img = img
        self.mu = mu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        mu.ctl_set_cpu_model(UC_CPU_M68K_CFV4E)
        mu.mem_map(0, 0x220000)
        mu.mem_write(BASE, img)
        mu.mem_write(RET, b"\x4e\x75")
        mu.mem_map(0x10000000, 0x81000)

    def call(self, fn, d1=None, arg=None):
        mu = self.mu
        for reg, val in SENT.items():
            mu.reg_write(reg, val)
        sp = STACK - 0x200
        words = [RET] if arg is None else [RET, arg & 0xFFFFFFFF]
        mu.mem_write(sp, struct.pack(">" + "I" * len(words), *words))
        mu.reg_write(UC_M68K_REG_A7, sp)
        if d1 is not None:
            mu.reg_write(UC_M68K_REG_D1, d1)
        mu.emu_start(fn, RET, count=200000)
        self.kept = all(mu.reg_read(reg) == val for reg, val in SENT.items())
        return mu.reg_read(UC_M68K_REG_D0)

    def cstr(self, addr):
        o = addr - BASE
        e = self.img.find(0, o, o + 16)
        return self.img[o:e].decode() if e > o else ""


def visible(emu):
    out = []
    for i in range(0, 192):
        a, b = emu.call(FWD_D1, d1=i), emu.call(FWD_STK, arg=i)
        if not emu.kept:
            raise SystemExit(f"regs clobbered at index {i}")
        if a != b:
            raise SystemExit(f"index {i}: d1 path {a} != stack path {b}")
        aid = a & 0xFF
        if i and aid == 0:
            break
        out.append(aid)
        back = emu.call(REV, arg=a) & 0xFF
        if back != i:
            raise SystemExit(f"index {i} id {aid} round-trips to {back}")
    return out


def main():
    with tempfile.TemporaryDirectory() as td:
        ref, out = os.path.join(td, "ref.bin"), os.path.join(td, "out.bin")
        build_beta2.build(sys.argv[1], ref, cord=False)
        build_beta2.build(sys.argv[1], out, cord=True)
        before, after = Emu(open(ref, "rb").read()), Emu(open(out, "rb").read())
    b, a = visible(before), visible(after)
    fails = []
    if 98 in b or 107 in b:
        fails.append("the release already lists Lfo1Ck or Lfo2Ck")
    i106 = b.index(106)
    if b[i106 - 1:i106 + 2] != [105, 106, 108]:
        fails.append(f"release run {b[i106 - 1:i106 + 2]}")
    i98 = a.index(98)
    if a[i98:i98 + 6] != [98, 104, 105, 107, 106, 108]:
        fails.append(f"LfoCk run {a[i98:i98 + 6]}")
    # Names follow the id. The stored table entries are not renumbered.
    for idx, want in ((a.index(107), "Lfo2Ck"), (a.index(106), "Lag0in"), (a.index(98), "Lfo1Ck")):
        got = after.cstr(after.call(NAME, arg=idx))
        if got != want:
            fails.append(f"index of {want} shows {got!r}")
    print(f"{len(a)} indexes; {len(fails)} failures")
    for f in fails:
        print("  " + f)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: emu_listorder.py BASE.bin")
    main()
