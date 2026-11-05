#!/usr/bin/env python3
"""EOS 4.71-beta2 build 4: b3+LfoCk (tools/build_lfock.py, PR #8) with the RFX pan fix (build_beta2.py RFX_PAN)
and the RFX probe on SysEx parameter 195 (patches/rfxprobe/rfxprobe.s, notes/rfx_bugs.md).

usage: build_b4.py BETA1.bin OUT.bin      (BETA1 = build/eos471_beta.bin)

The probe has no hooks: it is only the getter/setter of parameter 195 (descriptor 0x25AF4, dormant in stock, range
-1..7 -> 0..191). It goes in the end of the hole build_lfock frees at 0x1D8C1C (after rev_id), which build_lfock
leaves unused.
"""
import os, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_lfock   # noqa: E402
import eos_lz        # noqa: E402

ROOT = os.path.dirname(HERE)
XP = os.path.join(ROOT, 'patches', 'rfxprobe')
BIN = '/opt/homebrew/bin/'
BASE = 0x20000
NAME = b'EOS 4.71-beta2 build 4'
DESC = 0x25AF4                     # SysEx parameter 195
XP_RANGE = (0, 191)


def build(base, out):
    syms_l, _ = build_lfock.build(base, out)
    img = bytearray(open(out, 'rb').read())
    lo = (syms_l['rev_id'] + 26 + 1) & ~1          # end of .revid (26 bytes, checked below)
    hi = build_lfock.HOLE[1]
    if img[syms_l['rev_id'] + 24 - BASE:syms_l['rev_id'] + 26 - BASE] != b'\x4e\x75':
        raise SystemExit('.revid does not end with rts where expected')
    mn, mx = struct.unpack('>ii', img[DESC + 6 - BASE:DESC + 14 - BASE])
    if (mn, mx) != (-1, 7) or img[DESC + 0x1A - BASE:DESC + 0x22 - BASE] != bytes(8):
        raise SystemExit('descriptor 195 not stock')
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([BIN + 'm68k-elf-as', '-mcpu=5206e', '-o', 'x.o', os.path.join(XP, 'rfxprobe.s')],
                       check=True, cwd=td)
        open(os.path.join(td, 'x.ld'), 'w').write(f'SECTIONS {{ .rfxp 0x{lo:X} : {{ x.o(.rfxp) }} }}\n')
        subprocess.run([BIN + 'm68k-elf-ld', '-T', 'x.ld', '-o', 'x.elf', 'x.o'], check=True, cwd=td)
        subprocess.run([BIN + 'm68k-elf-objcopy', '-O', 'binary', '-j', '.rfxp', 'x.elf', 'x.bin'], check=True, cwd=td)
        code = open(os.path.join(td, 'x.bin'), 'rb').read()
        syms = {}
        for line in subprocess.run([BIN + 'm68k-elf-nm', os.path.join(td, 'x.elf')], check=True,
                                   capture_output=True, text=True).stdout.splitlines():
            a, t, n = line.split()
            syms[n] = int(a, 16)
    if lo + len(code) > hi:
        raise SystemExit(f'rfxprobe {len(code)} bytes > {hi - lo} free at {lo:#x}')
    img[lo - BASE:lo - BASE + len(code)] = code
    struct.pack_into('>ii', img, DESC + 6 - BASE, *XP_RANGE)
    struct.pack_into('>II', img, DESC + 0x1A - BASE, syms['xp_get'], syms['xp_set'])
    print(f'rfxprobe: {len(code)}/{hi - lo} bytes at {lo:#x}; get {syms["xp_get"]:#x} set {syms["xp_set"]:#x}')
    img[0x18:0x30] = NAME.ljust(24, b' ')
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    open(out, 'wb').write(img)
    print(f'{out}: checksum {c:08x}; name {NAME.decode()!r}')
    return dict(syms_l, **syms, xp_at=lo)


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])
