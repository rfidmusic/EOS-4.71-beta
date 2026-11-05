#!/usr/bin/env python3
"""Emulator test of the build-4 RFX probe (patches/rfxprobe/rfxprobe.s, SysEx parameter 195).

usage: emu_rfxprobe.py B4.bin
Plants a voice table at 0x102E9298 (random empty slots and voice types 1/2/4/8, structs 0x3FE apart as in
0x194B34, each with an RFX block), E-mu's counters at 0x100071C0..C4 and random block caches, then for commands
16, 17 and 64..191 runs the real setter and three getter calls through descriptor 195 and compares the 33 bits with
the expected latch. Also: commands 0..15, 18..63 and 192.. leave the latch alone; descriptor 195 range is 0..191.
"""
import os, random, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_p2k as ep        # noqa: E402

BASE, DESC = 0x20000, 0x25AF4
VOICES, CNT, LATCH = 0x102E9298, 0x100071C0, 0x1029E390
VS, BLK = 0x10300000, 0x10380000          # planted voice structs and RFX blocks


def main():
    img = open(sys.argv[1], 'rb').read()
    mn, mx = struct.unpack('>ii', img[DESC + 6 - BASE:DESC + 14 - BASE])
    get, put = struct.unpack('>II', img[DESC + 0x1A - BASE:DESC + 0x22 - BASE])
    assert (mn, mx) == (0, 191), (mn, mx)
    E = ep.Emu(img)
    E.mu.mem_map(0x10200000, 0x200000)
    fails, n = [], 0
    for seed in range(40):
        r = random.Random(seed)
        E.mu.mem_write(VS, bytes(0x3FE * 130)); E.mu.mem_write(VOICES, bytes(130 * 4))
        types, vptr = {}, {}
        for ch in range(128):
            if r.random() < 0.1:
                continue                                # empty slot
            v = VS + 0x3FE * (ch + 1)                   # struct - 0x3FE is always mapped
            t = r.choice([1, 2, 4, 8, 8, 0])
            types[ch], vptr[ch] = t, v
            E.w32(v + 0x1A, t)
            b = BLK + 0x42 * ch
            E.w32(v + 0x72, b)
            E.mu.mem_write(b + 0x0C, struct.pack('>H', r.choice([0xFFFF, r.randrange(0, 0x1000)])))
            E.mu.mem_write(b + 0x32, struct.pack('>H', r.choice([0xFF7F, r.randrange(0, 0x10000)])))
            E.w32(VOICES + 4 * ch, v)
        c = [r.randrange(0x10000) for _ in range(3)]
        E.mu.mem_write(CNT, struct.pack('>HHH', *c))
        orphans = 0
        for ch, v in vptr.items():
            main = struct.unpack('>I', E.rd(v - 0x3FE + 0x1A, 4))[0]
            if types[ch] == 8 and main & 6 == 0:
                orphans += 1

        def expect(cmd):
            if cmd == 16:
                return c[0] << 16 | c[1]
            if cmd == 17:
                return c[2] << 16 | orphans
            ch = cmd - 64
            if ch not in vptr:
                return 0
            b = BLK + 0x42 * ch
            lvl = struct.unpack('>H', E.rd(b + 0x0C, 2))[0] & 0xFFF
            pan = struct.unpack('>H', E.rd(b + 0x32, 2))[0]
            return (types[ch] << 28 | lvl << 16 | pan) & 0xFFFFFFFF

        for cmd in [16, 17] + list(range(64, 192)) + [0, 5, 15, 18, 40, 63, 192, 300, -1]:
            mark = r.randrange(1 << 32)
            E.w32(LATCH, mark)
            E.call(put, [DESC, cmd & 0xFFFFFFFF])
            p = [E.call(get, [DESC]) for _ in range(3)]
            got = (p[0] | p[1] << 11 | p[2] << 22) & 0xFFFFFFFF
            want = expect(cmd) if 16 <= cmd <= 17 or 64 <= cmd <= 191 else None
            want = mark if want is None else want
            n += 1
            if got != want or any(x > 0x7FF for x in p):
                fails.append((seed, cmd, hex(got), hex(want)))
    print(f'{n} probe reads; {len(fails)} failures', fails[:5])
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
