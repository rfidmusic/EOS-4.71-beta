#!/usr/bin/env python3
"""EOS 4.71 interpolated resonance + "4 Pole LP+Fuzz" test firmware (patches/lpfuzz/lpfuzz.s).

usage: build_lpfuzz.py BASE.bin OUT.bin [NAME] [--release]      (BASE = build/eos471_beta.bin)
--release: frozen LP+Fuzz (switch 15 behaviour), no test switch: descriptor 195 left stock.
All code and data are ours (no E-mu data beyond the base image). Patches:
  0x67F98..0x683F0  registry ctor loop (23 filters) + all new code, the new vtable and strings
  0x6843A           manager allocation 0x25C -> 0x260
  0x6841A 0x6846E 0x6848E 0x684B0   count displacement 0x258 -> 0x25C (ctor tail, FUN_00068458, FUN_000684A0)
  0x5AC48 / 0x6B58E filter-type descriptors: max 20 -> 21 and stored range (+0x15) 20 -> 21 (else the store rescales)
  0x65E5A           OB-Xa LP words -> jmp words_i ; 0x6684E HP/BP apply table part -> jmp apply_i
  descriptor 195    getter/setter = switch, max 7 -> 31
"""
import os, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eos_lz   # noqa: E402

ROOT = os.path.dirname(HERE)
PDIR = os.path.join(ROOT, 'patches', 'lpfuzz')
BIN = '/opt/homebrew/bin/'
BASE = 0x20000
NAME = b'EOS 4.71 LPFuzz5 T'
REL_NAME = b'EOS 4.71-beta2'
REGION = (0x67F98, 0x683F0)
VT_LP4 = 0x688A4
DESC195, DESC_FT1, DESC_FT2 = 0x25AF4, 0x5AC48, 0x6B58E
ALLOC = 0x6843A
COUNT_SITES = (0x6841A, 0x6846E, 0x6848E, 0x684B0)       # displacement words of the four $258 uses outside the ctor
WORDS, WORDS_STOCK = 0x65E5A, 'e48902810000001f'
APPLY, APPLY_STOCK = 0x6684E, '2451200174001429'
PATCH_RAM_FLASH = (0x205E4, 0x205F0)


def run(*cmd):
    subprocess.run(cmd, check=True, cwd=PDIR)


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


def build(base, out, name=NAME, release=False, origfilt=False, nfz=0):
    img = bytearray(open(base, 'rb').read())
    # stock checks
    if img[WORDS - BASE:WORDS - BASE + 8].hex() != WORDS_STOCK:
        raise SystemExit('OB-Xa LP words not at 0x65E5A (base must be 4.71-beta)')
    if img[APPLY - BASE:APPLY - BASE + 8].hex() != APPLY_STOCK:
        raise SystemExit('HP/BP apply table part not at 0x6684E')
    if img[ALLOC - BASE:ALLOC - BASE + 4].hex() != '4878025c':
        raise SystemExit('manager allocation not pea $25c')
    for a in COUNT_SITES:
        if img[a - BASE:a - BASE + 2] != b'\x02\x58':
            raise SystemExit(f'count displacement at {a:#x} not 0x258')
    for d in (DESC_FT1, DESC_FT2):
        if u32(img, d + 10) != 20:
            raise SystemExit(f'descriptor {d:#x} max not 20')
    if u32(img, DESC195 + 10) != 7 or img[DESC195 + 0x1A - BASE:DESC195 + 0x22 - BASE] != bytes(8):
        raise SystemExit('descriptor 195 not stock')
    if any(img[PATCH_RAM_FLASH[0] - BASE:PATCH_RAM_FLASH[1] - BASE]):
        raise SystemExit('patch RAM seed bytes not zero')
    stock = open(os.path.join(ROOT, 'bin', 'eos470_flash_0x20000.bin'), 'rb').read()
    if img[0x67F98 - BASE:0x68430 - BASE] != stock[0x67F98 - BASE:0x68430 - BASE]:
        raise SystemExit('registry ctor not stock')
    # new vtable = LP4's with type/name/computeFrames/packQ/formatParam replaced
    vt = [u32(img, VT_LP4 + 4 * k) for k in range(11)]
    sub = {3: 'lpf_type', 4: 'lpf_name', 5: 'lpf_cf', 6: 'lpf_pq', 7: 'lpf_fmt'}
    with open(os.path.join(PDIR, 'lpf_vt.inc'), 'w') as f:
        f.write('| vtable of 4 Pole LP+Fuzz: 4 Pole Low-pass (0x688A4) with slots 0x0C-0x1C replaced\n')
        for k, v in enumerate(vt):
            f.write(f'        .long   {sub.get(k, f"0x{v:08X}")}\n')
    run(BIN + 'm68k-elf-as', '-mcpu=5206e', *(['--defsym', 'RELEASE=1'] if release else []),
        *(['--defsym', 'ORIGFILT=1'] if origfilt else []), *(['--defsym', f'NFZ={nfz}'] if nfz else []),
        '-o', 'lpfuzz.o', 'lpfuzz.s')
    open(os.path.join(PDIR, 'lpfuzz.ld'), 'w').write(f'SECTIONS {{\n  .ctor 0x{REGION[0]:X} : {{ lpfuzz.o(.ctor) }}\n}}\n')
    run(BIN + 'm68k-elf-ld', '-T', 'lpfuzz.ld', '-e', '_start', '-o', 'lpfuzz.elf', 'lpfuzz.o')
    run(BIN + 'm68k-elf-objcopy', '-O', 'binary', '-j', '.ctor', 'lpfuzz.elf', 'lpfuzz_ctor.bin')
    code = open(os.path.join(PDIR, 'lpfuzz_ctor.bin'), 'rb').read()
    syms = {}
    for line in subprocess.run([BIN + 'm68k-elf-nm', 'lpfuzz.elf'], check=True, capture_output=True, text=True,
                               cwd=PDIR).stdout.splitlines():
        a, _, n = line.split()
        syms[n] = int(a, 16)
    lo, hi = REGION
    if len(code) > hi - lo:
        raise SystemExit(f'.ctor {len(code)} > {hi - lo}')
    if syms['lpf_vt'] % 4:
        raise SystemExit('vtable not aligned')
    # apply
    img[lo - BASE:lo - BASE + len(code)] = code
    nmenu, count, alloc = (22 + nfz if nfz else 31, 0x27C, 0x280) if origfilt else (23, 0x25C, 0x260)
    if not nfz:                                             # (nfz: build_fuzz.py fills the Fuzz slots)
        slot = syms['vtlist'] + 2 * (nmenu - 2) - BASE      # vtable list entry before the default
        if img[slot:slot + 2] != b'\x00\x00' or not 0x60000 < syms['lpf_vt'] < 0x70000:
            raise SystemExit('vtable list LP+Fuzz slot not the placeholder')
        struct.pack_into('>H', img, slot, (syms['lpf_vt'] - 0x60000) // (2 if origfilt else 1))
    img[lo - BASE + len(code):hi - BASE] = b'\x4e\x71' * ((hi - lo - len(code)) // 2)
    struct.pack_into('>H', img, ALLOC + 2 - BASE, alloc)
    for a in COUNT_SITES:
        struct.pack_into('>H', img, a - BASE, count)
    for d in (DESC_FT1, DESC_FT2):
        if img[d + 0x15 - BASE] != 20:
            raise SystemExit('filter-type descriptor stored range not stock')
        struct.pack_into('>I', img, d + 10 - BASE, nmenu - 2)
        img[d + 0x15 - BASE] = nmenu - 2   # stored range = max: no rescaling of the stored type ID (0x596B4/0x59718)
    if not release:
        struct.pack_into('>I', img, DESC195 + 10 - BASE, 31)
        struct.pack_into('>II', img, DESC195 + 0x1A - BASE, syms['sw_get'], syms['sw_set'])
    img[WORDS - BASE:WORDS - BASE + 6] = b'\x4e\xf9' + struct.pack('>I', syms['words_i'])
    img[APPLY - BASE:APPLY - BASE + 6] = b'\x4e\xf9' + struct.pack('>I', syms['apply_i'])
    if len(name) > 24:
        raise SystemExit('name too long')
    img[0x18:0x30] = name.ljust(24, b' ')
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    open(out, 'wb').write(img)
    print(f'{out}: .ctor {len(code)}/{hi - lo} bytes; checksum {c:08x}; name {name.decode()!r}')
    return syms


if __name__ == '__main__':
    rel = '--release' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--release']
    build(args[0], args[1], args[2].encode() if len(args) > 2 else (REL_NAME if rel else NAME), release=rel)
