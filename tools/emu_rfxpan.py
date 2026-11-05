#!/usr/bin/env python3
"""Emulator check of the RFX pan table (build_beta2.py RFX_PAN): runs the real RFX voice writer FUN_0010E280 in both
images for every pan (-64..63) and a range of send levels, and checks the four sends' L/R register words.

usage: emu_rfxpan.py REF.bin NEW.bin      (REF = build 3, stock 0x10E794; NEW = with the RFX pan fix)
Each image's output must equal the model of 0x10E280 with that image's own 0x10E794 (so the code reads the table as
traced), and NEW at full send must give hard pan 0 dB / far side silent and centre -3.0 dB on both sides.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emu_p2k as ep        # noqa: E402

BASE, TAB, GAIN, OFFS = 0x20000, 0x10E794, 0x10E504, 0x10004D84
BLK, CHIPV, REGS = 0x10050000, 0x10051000, 0x10052000
LEVELS = [4095, 4096, 3500, 3000, 2389, 1500, 600, 16, 0, -500]
OFFSETS = [-0x60, -0x1D]


def words(img, a, n):
    return struct.unpack(f'>{n}h', img[a - BASE:a - BASE + 2 * n])


def model(img, pan, lv, off):
    t, g = words(img, TAB, 128), words(img, GAIN, 256)
    lv = min(lv, 0xFFF)

    def side(x):
        i = max(0, (lv + x) >> 4)
        v = g[i] & 0xFFFF
        return (v + off) & 0xFFFF if v else 0
    return side(t[(pan + 64) ^ 0x7F]), side(t[pan + 64])


def run(E, pan, lvs, off):
    E.mu.mem_write(BLK, bytes(0x80)); E.mu.mem_write(REGS, bytes(0x20))
    E.mu.mem_write(OFFS, struct.pack('>i', off))         # long; the writer adds its low word
    E.mu.mem_write(BLK, struct.pack('>hhI', 100, pan, 0))           # volume, pan, mode 0
    for k, lv in enumerate(lvs):
        E.mu.mem_write(BLK + 8 + 10 * k, struct.pack('>hhhhh', lv, 0, 0x7FFF, 0, 0))
    E.mu.mem_write(BLK + 0x32, struct.pack('>h', 0x7FFF))          # previous pan: force every send to write
    E.mu.mem_write(BLK + 0x36, struct.pack('>II', CHIPV, REGS))
    E.call(0x10E280, [BLK])
    return [struct.unpack('>HH', E.rd(REGS + 4 * k, 4)) for k in range(4)]


def check(img):
    E, n, bad = ep.Emu(img), 0, []
    for off in OFFSETS:
        for pan in range(-64, 64):
            for i in range(0, len(LEVELS), 4):
                lvs = (LEVELS[i:i + 4] + [0, 0, 0])[:4]
                for k, got in enumerate(run(E, pan, lvs, off)):
                    want = model(img, pan, lvs[k], off)
                    n += 1
                    if tuple(got) != want:
                        bad.append((off, pan, lvs[k], got, want))
    return n, bad


def db(img, pan):
    t = words(img, TAB, 128)
    out = []
    for x in (t[(pan + 64) ^ 0x7F], t[pan + 64]):
        i = (4095 + x) >> 4
        out.append(None if i <= 0 else (i - 255) * 0.375)
    return out


def main():
    ok = True
    for nm, path in zip(('REF', 'NEW'), sys.argv[1:3]):
        img = open(path, 'rb').read()
        n, bad = check(img)
        print(f'{nm}: {n} send writes, {len(bad)} mismatches vs model', bad[:3])
        ok &= not bad
        for p in (-64, 0, 63):
            print(f'  pan {p:>3}: L {db(img, p)[0]} dB, R {db(img, p)[1]} dB')
    new = open(sys.argv[2], 'rb').read()
    want = {-64: [0.0, None], 0: [-3.0, -3.0], 63: [None, 0.0]}
    for p, w in want.items():
        if db(new, p) != w:
            print(f'NEW pan {p}: {db(new, p)} != {w}'); ok = False
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
