#!/usr/bin/env python3
"""EOS 4.71-beta2 with the E-mu filters restored in place and eight Fuzz filters built on them (test build).

usage: build_fuzz.py BETA1.bin OUT.bin [NAME]     (BETA1 = build/eos471_beta.bin; STOCK = bin/eos470_flash_0x20000.bin)

Menu: the 21 E-mu filters of EOS 4.70 (stock code, order, type IDs), then 2 Pole LP+Fuzz (0x04), 4 Pole LP+Fuzz
(0x03, the type of the old LP+Fuzz), 6 Pole LP+Fuzz (0x05), 2nd Ord HP+Fuzz (0x0A), 2nd Ord BP+Fuzz (0x13),
Contrary BP+Fuzz (0x15), then the default (0x7F). (The 4th-order HP / BP have no free zero/pole pair for a drive.) The OB-Xa models are not in this image (their code
stays in the repository: patches/obxa*, tools/hpbp.py, patches/lpfuzz/lpfuzz_v5_original.s).
Steps:
 1. build_beta2.build(origfilt=True, nfz=6): the 28-entry ctor list with six empty Fuzz slots.
 2. 0x65C00-0x67F98 back to STOCK (only 0x65E18-0x66B36 may differ: beta1's OB-Xa code and the hooks into it), the
    eight E-mu vtables and the table 0x6875C back to STOCK. The old LP+Fuzz / interpolation code in the ctor region
    (lerp .. end_of_ctor) is then unreferenced and is reused.
 3. patches/fuzz/fuzz.s: code (.fzc) in the .blkPM tail, vtables + parameters + names (.fzv) in the old LP+Fuzz
    area (inside 0x60000-0x7FFFE, the reach of the ctor list). Each vtable copies its stock filter's vtable.
 4. The ctor list's eight Fuzz slots, and parameter 195 (the test switch: max 31, getter/setter).
"""
import json, os, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_beta2      # noqa: E402
import eos_lz           # noqa: E402

ROOT = os.path.dirname(HERE)
FZ = os.path.join(ROOT, 'patches', 'fuzz')
BIN = '/opt/homebrew/bin/'
BASE = 0x20000
NAME = b'EOS 4.71-b2 Fuzz6 T'
STOCK = os.path.join(ROOT, 'bin', 'eos470_flash_0x20000.bin')
FILT = (0x65C00, 0x67F98)
OBXA = (0x65E18, 0x66B36)
TABLE = (0x6875C, 0x6879C)
EMU_VTS = (0x68878, 0x688A4, 0x688D0, 0x688FC, 0x68928, 0x689D8, 0x68A04, 0x68A30)
PM_END = 0x15F818
DESC195 = 0x25AF4
COUNT_SITES = (0x6841A, 0x6846E, 0x6848E, 0x684B0)
ALLOC = 0x6843A
DESC_FT = (0x5AC48, 0x6B58E)
CAP, COPY, PEAK, DPOL, DZER, NEUT = 1, 2, 3, 4, 5, 6
# The chip with the zeros on: pole 0 alone (a low-pass stage), zero 1 / pole 4 and zero 5 / pole 8 as pairs.
# Each Fuzz filter = its stock filter at q / 2 + an LP+Fuzz drive pair (pole = the filter's resonant pole, zero
# sliding up from it), as in the 4 Pole LP+Fuzz of EOS 4.71-beta2 (notes/lpfuzz_analysis.md).
# menu order: (label, name, type, base vtable, flags (bit 0 smooth drive pole), setmode, program)
VARIANTS = [
    ('lp2', '2 Pole LP+Fuzz', 0x04, 0x68878, 1, 0xC0, [(CAP, 0, 0), (DPOL, 4, 0), (DZER, 1, 0)]),
    ('lp4', '4 Pole LP+Fuzz', 0x03, 0x688A4, 0, 0xC0, [(CAP, 0, 0), (CAP, 4, 4), (DPOL, 4, 4), (DZER, 1, 0)]),
    ('lp6', '6 Pole LP+Fuzz', 0x05, 0x688D0, 0, 0xC0,
     [(CAP, 0, 0), (CAP, 4, 4), (CAP, 8, 8), (DPOL, 4, 4), (DZER, 1, 0), (PEAK, 5, 8)]),
    ('hp2', '2nd Ord HP+Fuzz', 0x0A, 0x688FC, 0, 0, [(CAP, 4, 4), (DPOL, 8, 4), (DZER, 5, 0)]),
    # BP2: words 0/1/4 are E-mu's cutoff-dependent level compensation (-40 dB at cutoff 0), so the band-pass pair
    # itself (zero 5 / pole 8) is the drive: its zero slides up from E-mu's own zero (Q 0 = the stock BP2)
    ('bp2', '2nd Ord BP+Fuzz', 0x13, 0x689D8, 0, 0, [(CAP, 8, 8), (DPOL, 5, 5), (DZER, 5, 0)]),
    ('cbp', 'Contrary BP+Fuzz', 0x15, 0x68A30, 0, 0, [(CAP, 0, 0), (DPOL, 4, 0), (DZER, 1, 0)]),
]


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


def run(*cmd, cwd=FZ):
    subprocess.run(cmd, check=True, cwd=cwd)


def build(beta1, out, name=NAME):
    stock = open(STOCK, 'rb').read()
    with tempfile.TemporaryDirectory() as td:
        b2 = os.path.join(td, 'b2.bin')
        build_beta2.build(beta1, b2, origfilt=True, nfz=len(VARIANTS))
        syms_l = build_beta2.build.syms_l
        img = bytearray(open(b2, 'rb').read())
        syms = json.load(open(b2 + '.syms.json'))
    # 2. E-mu filters back in place
    for a in range(*FILT):
        if img[a - BASE] != stock[a - BASE] and not OBXA[0] <= a < OBXA[1]:
            raise SystemExit(f'{a:#x} differs from stock outside the OB-Xa code')
    img[FILT[0] - BASE:FILT[1] - BASE] = stock[FILT[0] - BASE:FILT[1] - BASE]
    for vt in EMU_VTS:
        img[vt - BASE:vt + 0x2C - BASE] = stock[vt - BASE:vt + 0x2C - BASE]
    img[TABLE[0] - BASE:TABLE[1] - BASE] = stock[TABLE[0] - BASE:TABLE[1] - BASE]
    dead = ((syms_l['lerp'] + 3) & ~3, syms_l['end_of_ctor'])
    vtlist = syms_l['vtlist']
    for k in range(21, 21 + len(VARIANTS)):
        if img[vtlist + 2 * k - BASE:vtlist + 2 * k + 2 - BASE] != b'\0\0':
            raise SystemExit(f'Fuzz list slot {k} not empty')
    lp = syms_l.get('lpf_vt')
    if lp is not None and any(struct.unpack('>H', img[vtlist + 2 * k - BASE:vtlist + 2 * k + 2 - BASE])[0] * 2 + 0x60000
                              == lp for k in range(22 + len(VARIANTS))):
        raise SystemExit('the old LP+Fuzz vtable is still listed')
    pm_lo = PM_END
    while img[pm_lo - 2 - BASE:pm_lo - BASE] == b'\x4e\x71':
        pm_lo -= 2
    pm_lo = (pm_lo + 3) & ~3
    # 3. the Fuzz engine
    with open(os.path.join(FZ, 'fz_vt.inc'), 'w') as f:
        f.write('| generated by tools/build_fuzz.py: each Fuzz vtable = its stock filter\'s, parameters, name\n')
        for lab, nm, typ, base, flags, sm, prog in VARIANTS:
            slots = [u32(stock, base + 4 * k) for k in range(11)]
            sub = {3: 'fz_type', 4: 'fz_name', 5: 'fz_cf', 6: 'fz_pq', 7: 'fz_fmt'}
            f.write(f'        .align  4\n        .globl  fzv_{lab}\nfzv_{lab}:\n')
            for k, v in enumerate(slots):
                f.write(f'        .long   {sub.get(k, f"0x{v:08X}")}\n')
            f.write(f'        .byte   0x{typ:02X}, {flags}, 0x{sm:02X}, 0\n')
            f.write(f'        .long   fzn_{lab}, 0x{base:08X}\n')
            f.write('        .byte   ' + ', '.join(f'0x{(op << 4) | d:02X}, {s}' for op, d, s in prog) + ', 0xFF\n')
            f.write(f'fzn_{lab}: .asciz "{nm}"\n')
    run(BIN + 'm68k-elf-as', '-mcpu=5206e', '-o', 'fuzz.o', 'fuzz.s')
    ld = f'SECTIONS {{\n  .fzc 0x{pm_lo:X} : {{ fuzz.o(.fzc) }}\n  .fzv 0x{dead[0]:X} : {{ fuzz.o(.fzv) }}\n}}\n'
    open(os.path.join(FZ, 'fuzz.ld'), 'w').write(ld)
    run(BIN + 'm68k-elf-ld', '-T', 'fuzz.ld', '-o', 'fuzz.elf', 'fuzz.o')
    fsyms = {}
    for line in subprocess.run([BIN + 'm68k-elf-nm', 'fuzz.elf'], check=True, capture_output=True, text=True,
                               cwd=FZ).stdout.splitlines():
        a, _, n = line.split()
        fsyms[n] = int(a, 16)
    for sec, lo, hi in (('.fzc', pm_lo, PM_END), ('.fzv', dead[0], dead[1])):
        run(BIN + 'm68k-elf-objcopy', '-O', 'binary', '-j', sec, 'fuzz.elf', 'sec.bin')
        code = open(os.path.join(FZ, 'sec.bin'), 'rb').read()
        if lo + len(code) > hi:
            raise SystemExit(f'{sec}: {len(code)} bytes > {hi - lo} free at {lo:#x}')
        img[lo - BASE:hi - BASE] = b'\x4e\x71' * ((hi - lo) // 2) + (b'\x4e' if (hi - lo) % 2 else b'')
        img[lo - BASE:lo - BASE + len(code)] = code
        print(f'{sec}: {len(code)}/{hi - lo} bytes at {lo:#x}')
    # 4. list slots, parameter 195
    for k, (lab, *_r) in enumerate(VARIANTS):
        vt = fsyms[f'fzv_{lab}']
        if vt % 2 or not 0x60000 <= vt <= 0x7FFFE:
            raise SystemExit(f'{lab} vtable {vt:#x} out of the list range')
        struct.pack_into('>H', img, vtlist + 2 * (21 + k) - BASE, (vt - 0x60000) // 2)
    if u32(img, DESC195 + 10) != 7 or img[DESC195 + 0x1A - BASE:DESC195 + 0x22 - BASE] != bytes(8):
        raise SystemExit('descriptor 195 not stock')
    struct.pack_into('>I', img, DESC195 + 10 - BASE, 31)
    struct.pack_into('>II', img, DESC195 + 0x1A - BASE, fsyms['fz_swget'], fsyms['fz_swset'])
    for d in DESC_FT:
        if u32(img, d + 10) != 20 + len(VARIANTS):
            raise SystemExit(f'descriptor {d:#x} max not {20 + len(VARIANTS)}')
    # header
    img[0x18:0x30] = name.ljust(24, b' ')[:24]
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    open(out, 'wb').write(img)
    info = dict(vtlist=vtlist, variants=[dict(label=v[0], name=v[1], type=v[2], base=v[3], flags=v[4], setmode=v[5],
                                              prog=v[6], vtable=fsyms[f'fzv_{v[0]}']) for v in VARIANTS],
                fzc=pm_lo, fzv=dead[0], syms={k: v for k, v in fsyms.items() if k.startswith('fz')})
    json.dump(info, open(out + '.fuzz.json', 'w'), indent=1)
    json.dump(syms, open(out + '.syms.json', 'w'), indent=1)
    print(f'{out}: checksum {c:08x}; name {name.decode()!r}')
    return info


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3].encode() if len(sys.argv) > 3 else NAME)
