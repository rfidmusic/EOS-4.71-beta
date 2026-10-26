#!/usr/bin/env python3
"""EOS 4.71-beta2 with the E-mu filters of 4.70 and five Fuzz filters on the OB-Xa models (test build).

usage: build_fuzzob.py BETA1.bin OUT.bin [NAME]     (BETA1 = build/eos471_beta.bin; STOCK = bin/eos470_flash_0x20000.bin)

Menu: the 21 E-mu filters of EOS 4.70 (stock code, order, type IDs), then 2 Pole LP+Fuzz (0x04), 4 Pole LP+Fuzz
(0x03: the original LP+Fuzz of build 2, unchanged), 2nd Ord HP+Fuzz (0x0A), 2nd Ord BP+Fuzz (0x13), Contrary BP+Fuzz
(0x15), then the default (0x7F). The OB-Xa models stay in the image as the Fuzz filters' bases (not in the menu).
Steps:
 1. build_origfilt.prepare(nfz=5, low=...): build 2 with the 27-entry list (five empty Fuzz slots), the disk-unit
    compaction, the stock code beta1 overwrote copied out (OB-Xa code stays in place), the E-mu vtables restored;
    room for the Fuzz vtables reserved first below 0x7FFFE (the reach of the ctor list).
 2. patches/fuzzob/fuzzob.s: one section per routine, largest first, each in the smallest hole that fits. Besides
    the builder holes, two pieces of build 2's OB-Xa code that nothing uses any more (EXTRA: never executed or read
    by any remaining filter, tools/emu_fuzzob.py; no reference to them anywhere in the image, checked here).
 3. Each engine filter: a vtable = build 2's OB-Xa vtable with its own type / name stubs and the engine methods;
    slot 11 points at its parameter block (base computeFrames / packQ / formatParam, SETMODE flags, program).
 4. The list's five slots: the four engine filters and, in slot 22, the original LP+Fuzz vtable (lpf_vt).
"""
import json, os, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_origfilt   # noqa: E402
import eos_lz           # noqa: E402

ROOT = os.path.dirname(HERE)
FZ = os.path.join(ROOT, 'patches', 'fuzzob')
BIN = '/opt/homebrew/bin/'
BASE = 0x20000
NAME = b'EOS 4.71-b2 FuzzOB T'
DESC_FT = (0x5AC48, 0x6B58E)
COPY, SMTH, DZER = 1, 2, 3
VT_LEN = 48                       # 11 slots + the parameter pointer
N_LOW = 3                         # vtables reserved in the compaction block; the 4th fits in the first EXTRA piece
EXTRA = [(0x6627C, 0x662D4, 'unused OB-Xa HP4 table'), (0x65E62, 0x65E9E, 'unused OB-Xa LP code')]
# menu order from slot 21: (label, name, type, OB-Xa base vtable in build 2, SETMODE flags after the base, program)
# 'lp4' is the original LP+Fuzz (lpfuzz.s), not the engine. As Fuzz6's programs, without the 0xDF cap (never acts on
# these OB-Xa bases: their capped words stay at or below 0xD8 for every q / 2).
VARIANTS = [
    ('lp2', '2 Pole LP+Fuzz', 0x04, 0x68878, 0xC0, [(SMTH, 4, 0), (DZER, 1, 4)]),
    ('lp4', '4 Pole LP+Fuzz', 0x03, None, None, None),
    ('hp2', '2nd Ord HP+Fuzz', 0x0A, 0x688FC, 0, [(COPY, 8, 4), (DZER, 5, 8)]),
    ('bp2', '2nd Ord BP+Fuzz', 0x13, 0x689D8, 0, [(DZER, 5, 5)]),
    ('cbp', 'Contrary BP+Fuzz', 0x15, 0x68A30, 0, [(COPY, 4, 0), (DZER, 1, 4)]),
]
ENGINE = [v for v in VARIANTS if v[3] is not None]


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


def put(img, a, b):
    img[a - BASE:a - BASE + len(b)] = b


def run(*cmd):
    return subprocess.run(cmd, check=True, cwd=FZ, capture_output=True, text=True).stdout


def refs_into(img, lo, hi):
    """Absolute longs, 16-bit PC-relative operands (branches, lea/pea/jsr/jmp d16(pc)) and short branches anywhere
    in the image (outside [lo, hi)) that point into [lo, hi)."""
    out = []
    for o in range(0, len(img) - 4, 2):
        a = o + BASE
        if lo <= a < hi:
            continue
        if lo <= struct.unpack('>I', img[o:o + 4])[0] < hi:
            out.append(a)
        op = struct.unpack('>H', img[o:o + 2])[0]
        if (op & 0xF0FF) == 0x6000 or op in (0x41FA, 0x43FA, 0x45FA, 0x47FA, 0x49FA, 0x4BFA, 0x4DFA, 0x4FFA, 0x487A,
                                              0x4EBA, 0x4EFA):
            if lo <= a + 2 + struct.unpack('>h', img[o + 2:o + 4])[0] < hi:
                out.append(a)
        if 0x6000 <= op < 0x7000 and (op & 0xFF) not in (0, 0xFF):
            if lo <= a + 2 + struct.unpack('>b', img[o + 1:o + 2])[0] < hi:
                out.append(a)
    return out


def assemble(defs, at=None):
    """Assemble fuzzob.s; with at = {section: address}, link and return ({section: bytes}, symbols), else the sizes."""
    run(BIN + 'm68k-elf-as', '-mcpu=5206e', *[x for k, v in defs.items() for x in ('--defsym', f'{k}={v}')],
        '-o', 'fuzzob.o', 'fuzzob.s')
    if at is None:
        return {ln.split()[1]: int(ln.split()[2], 16) for ln in run(BIN + 'm68k-elf-objdump', '-h', 'fuzzob.o')
                .splitlines() if len(ln.split()) > 2 and ln.split()[1].startswith('.fz_')}
    lds = ''.join(f'  {sec} 0x{a:X} : {{ fuzzob.o({sec}) }}\n' for sec, a in at.items())
    open(os.path.join(FZ, 'fuzzob.ld'), 'w').write(f'SECTIONS {{\n{lds}}}\n')
    run(BIN + 'm68k-elf-ld', '-T', 'fuzzob.ld', '-o', 'fuzzob.elf', 'fuzzob.o')
    code = {}
    for sec in at:
        run(BIN + 'm68k-elf-objcopy', '-O', 'binary', '-j', sec, 'fuzzob.elf', 'sec.bin')
        code[sec] = open(os.path.join(FZ, 'sec.bin'), 'rb').read()
    syms = {n: int(a, 16) for a, _, n in (ln.split() for ln in run(BIN + 'm68k-elf-nm', 'fuzzob.elf').splitlines())}
    return code, syms


def build(beta1, out, name=NAME):
    P = build_origfilt.prepare(beta1, nfz=len(VARIANTS), low=VT_LEN * N_LOW)
    img, holes, syms_l, base_vt, vtlist = P['img'], P['holes'], P['syms_l'], P['base_vt'], P['vtlist']
    lpf_vt, zlerp, lpf_fmt = syms_l['lpf_vt'], syms_l['zlerp'], syms_l['lpf_fmt']
    stock = P['stock']
    holes.add(P['low'], P['low'] + VT_LEN * N_LOW, 'list-range block')
    for lo, hi, what in EXTRA:
        if any(img[a - BASE] == stock[a - BASE] for a in range(lo, hi)):
            raise SystemExit(f'{what}: stock bytes in {lo:#x}-{hi:#x}')
        r = refs_into(img, lo, hi)
        if r:
            raise SystemExit(f'{what}: referenced from {[hex(x) for x in r]}')
        holes.add(lo, hi, what)
    if not 0x60000 <= lpf_vt <= 0x7FFFE or lpf_vt % 2:
        raise SystemExit('lpf_vt out of the list range')
    for k in range(21, 21 + len(VARIANTS)):
        if img[vtlist + 2 * k - BASE:vtlist + 2 * k + 2 - BASE] != b'\0\0':
            raise SystemExit(f'Fuzz list slot {k} not empty')
    # 2. vtables first (list range), then the engine code
    vts = [holes.take(VT_LEN, 4, 'vtable', below=0x7FFFE) for _ in ENGINE]
    defs = dict(ZLERP=f'0x{zlerp:X}', LPF_FMT=f'0x{lpf_fmt:X}')
    sizes = assemble(defs)
    at = {sec: holes.take(n, 2, sec) for sec, n in sorted(sizes.items(), key=lambda x: -x[1])}
    code, fs = assemble(defs, at)
    for sec, a in at.items():
        if len(code[sec]) != sizes[sec]:
            raise SystemExit(f'{sec}: size changed')
        put(img, a, code[sec])
    # 3. engine vtables, parameter blocks, names, stubs
    placed = {}
    for (lab, nm, typ, base, sm, prog), vt_at in zip(ENGINE, vts):
        slots = list(base_vt[base])
        na = holes.take(len(nm) + 1, 1, 'name')
        put(img, na, nm.encode() + b'\0')
        ts = holes.take(4, 2, 'type stub')
        put(img, ts, bytes([0x70, typ, 0x4E, 0x75]))                        # moveq #type,d0 ; rts
        ns = holes.take(8, 2, 'name stub')
        put(img, ns, b'\x20\x3c' + struct.pack('>I', na) + b'\x4e\x75')     # move.l #name,d0 ; rts
        pb = struct.pack('>III', slots[5], slots[6], slots[7]) + bytes([sm, 0]) \
            + bytes(b for op, d, s in prog for b in ((op << 4) | d, s)) + b'\xff'
        pa = holes.take(len(pb), 2, 'parameters')
        put(img, pa, pb)
        slots[3], slots[4], slots[5], slots[6], slots[7] = ts, ns, fs['fz_cf'], fs['fz_pq'], fs['fz_fmt']
        put(img, vt_at, b''.join(struct.pack('>I', v) for v in slots + [pa]))
        placed[lab] = dict(name=nm, type=typ, base=base, setmode=sm, prog=prog, vtable=vt_at, params=pa,
                           type_stub=ts, name_stub=ns, name_at=na)
    # 4. the list
    for k, (lab, *_r) in enumerate(VARIANTS):
        vt = lpf_vt if lab == 'lp4' else placed[lab]['vtable']
        if vt % 2 or not 0x60000 <= vt <= 0x7FFFE:
            raise SystemExit(f'{lab} vtable {vt:#x} out of the list range')
        struct.pack_into('>H', img, vtlist + 2 * (21 + k) - BASE, (vt - 0x60000) // 2)
    for d in DESC_FT:
        if u32(img, d + 10) != 20 + len(VARIANTS):
            raise SystemExit(f'descriptor {d:#x} max not {20 + len(VARIANTS)}')
    # header
    if len(name) > 24:
        raise SystemExit('name too long')
    img[0x18:0x30] = name.ljust(24, b' ')
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    open(out, 'wb').write(img)
    info = dict(vtlist=vtlist, lpf_vt=lpf_vt, sections=at, engine=fs, variants=placed, extra=EXTRA,
                order=[v[0] for v in VARIANTS], free_left=holes.free(), lp_group=P['lp_dest'], hpbp_group=P['hp_dest'],
                table=P['table_new'], new={hex(k): v for k, v in P['new'].items()})
    json.dump(info, open(out + '.fuzzob.json', 'w'), indent=1)
    json.dump(P['syms'], open(out + '.syms.json', 'w'), indent=1)
    print(f'{out}: checksum {c:08x}; name {name.decode()!r}; engine {sum(sizes.values())} bytes in {len(at)} pieces; '
          f'{holes.free()} bytes left in the holes')
    return info


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3].encode() if len(sys.argv) > 3 else NAME)
