#!/usr/bin/env python3
"""EOS 4.71-beta2 with the original E-mu filters back, and the OB-Xa models as eight new filter types.

usage: build_origfilt.py BETA1.bin OUT.bin [NAME]      (BETA1 = build/eos471_beta.bin; STOCK = bin/eos470_flash_0x20000.bin)

Menu: the 21 E-mu filters of EOS 4.70 in their stock order, type IDs and code; then the eight OB-Xa models
(type IDs 0x04 0x05 0x06 0x0A 0x0B 0x13 0x14 0x15); then 4 Pole LP+Fuzz (0x03); then the default (0x7F).
Presets keep their stored type IDs, so 4.70 presets get the E-mu filters back and beta1/beta2 presets that used the
OB-Xa models on IDs 0x00-0x12 now play the E-mu filters too.

Steps:
 1. build_beta2.build(origfilt=True): the registry ctor reads (vtable - 0x60000) / 2 from a 31-entry list (8 empty
    OB-Xa slots), the menu holds 31 entries, both filter-type descriptors go to max 29, .slT moves to .blkPM.
 2. unitcompact.apply(): the disk-unit tables fold, freeing 0x7F9E4-0x8018A (notes/compaction.md, disk_units.md).
 3. The 25 stock functions that beta1 overwrote (all of the eight filters' code that differs, except the three LP
    type/name stub pairs, whose beta2 copies at 0x65E18-0x65E3C return the stock values) are copied from STOCK:
    the LP group (0x65E18 helper + 2/4/6-pole computeFrames/packQ, 644 bytes, three bsr.w to the helper) into the
    .blkPM tail; the HP/BP group (1,470 bytes, only absolute calls) and STOCK's table 0x6875C (64 bytes; beta1
    changed it) into the freed block. Absolute references to 0x6875C in the copies point at the copy.
 4. The eight E-mu vtables at their stock addresses get their stock slots back (copies where the code moved).
 5. Eight new vtables (= beta2's OB-Xa vtables with a new type and name method) fill the empty list slots.
 6. Names and the small type/name methods go into free holes: the rest of the freed block, the slack of .blkF and
    of the unused vectors at 0x20240, and nine duplicate strings folded into their first copy (each dropped copy's
    only references are verified `pea.l` operands, repointed).
"""
import json, os, struct, sys, tempfile
import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_beta2      # noqa: E402
import unitcompact      # noqa: E402
import eos_lz           # noqa: E402

ROOT = os.path.dirname(HERE)
BASE = 0x20000
NAME = b'EOS 4.71-b2 OrigFilt T'
STOCK = os.path.join(ROOT, 'bin', 'eos470_flash_0x20000.bin')
MD = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_040)

# (stock address, size): copied from STOCK, sizes = up to the next function (or the rts)
LP_GROUP = [(0x65E18, 116), (0x65E98, 132), (0x65F1C, 36), (0x65F4C, 128), (0x65FCC, 40), (0x66000, 140),
            (0x6608C, 52)]
HPBP_GROUP = [(0x660CC, 116), (0x66140, 56), (0x66178, 244), (0x66278, 120), (0x662F0, 60), (0x667A8, 244),
              (0x668A8, 140), (0x66934, 76), (0x6698C, 144), (0x66A1C, 80), (0x66A78, 128), (0x66AF8, 62)]
TABLE, TABLE_LEN = 0x6875C, 64
# vtable, E-mu name, OB-Xa name, OB-Xa type ID
FILTERS = [(0x68878, '2 Pole Low-pass', b'OB-Xa 2 Pole LP', 0x04), (0x688A4, '4 Pole Low-pass', b'OB-Xa 4 Pole LP', 0x05),
           (0x688D0, '6 Pole Low-pass', b'OB-Xa 6 Pole LP', 0x06), (0x688FC, '2nd Order HP', b'OB-Xa 2nd Ord HP', 0x0A),
           (0x68928, '4th Order HP', b'OB-Xa 4th Ord HP', 0x0B), (0x689D8, '2nd Order BP', b'OB-Xa 2nd Ord BP', 0x13),
           (0x68A04, '4th Order BP', b'OB-Xa 4th Ord BP', 0x14), (0x68A30, 'Contrary BP', b'OB-Xa Contrary BP', 0x15)]
VT_LEN = 0x2C
FREED = unitcompact.FREE                            # 0x7F9E4 .. 0x8018A
PM_END = 0x15F818
F_END = 0x683F0
V16 = (0x20240, 0x20260)
DEFAULT_VEC = 0x20926
# duplicate strings: (copy to drop, copy to keep, [operand addresses of the pea.l instructions that load it])
FOLD = [(0xBE7FC, 0xBC338, [0xBC818]), (0xD99A8, 0xD85C4, [0xD8D0A]), (0xD9F38, 0xD85C4, [0xD9D22]),
        (0xB7904, 0x2994C, [0xB4508]), (0x17C878, 0x2994C, [0x17B4CE]), (0xACD08, 0xA8490, [0xAB3EC]),
        (0xD47B4, 0xA8490, [0xD463A]), (0xD139C, 0xB1C58, [0xCEBEA]), (0xE1D68, 0xB1C58, [0xE0FAA])]


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


def put(img, a, b):
    img[a - BASE:a - BASE + len(b)] = b


def all_refs(img, lo, hi):
    """Every 2-aligned long in the image whose value lies in [lo, hi)."""
    out = []
    for o in range(0, len(img) - 4, 2):
        w = struct.unpack('>I', img[o:o + 4])[0]
        if lo <= w < hi:
            out.append((o + BASE, w))
    return out


class Holes:
    def __init__(self):
        self.h = []

    def add(self, lo, hi, what):
        if hi > lo:
            self.h.append([lo, hi, what])

    def take(self, n, align=2, what='', below=None):
        best = None
        for h in self.h:
            a = (h[0] + align - 1) & ~(align - 1)
            if below is not None and a + n > below:
                continue
            if a + n <= h[1] and (best is None or h[1] - h[0] < best[1] - best[0]):
                best = h
        if best is None:
            raise SystemExit(f'no room for {what} ({n} bytes)')
        a = (best[0] + align - 1) & ~(align - 1)
        best[0] = a + n
        return a

    def free(self):
        return sum(h[1] - h[0] for h in self.h)


def relocate(img, stock, group, dest, table_new):
    """Copy the group's functions from STOCK to dest, consecutively; fix bsr/bra into the group and refs to TABLE."""
    new, a = {}, dest
    for f, n in group:
        new[f] = a
        a += n
    for f, n in group:
        code = bytearray(stock[f - BASE:f - BASE + n])
        for i in MD.disasm(bytes(code), f):
            off = i.address - f
            m = i.mnemonic
            if m in ('bsr.w', 'bra.w') or (m.startswith('b') and m.endswith('.w') and m not in ('btst.w',)):
                t = i.address + 2 + struct.unpack('>h', bytes(code[off + 2:off + 4]))[0]
                if not (f <= t < f + n):
                    if t not in new:
                        raise SystemExit(f'{i.address:#x}: {m} to {t:#x} leaves the group')
                    d = new[t] - (new[f] + off + 2)
                    struct.pack_into('>h', code, off + 2, d)
            elif m.endswith('.b') and m.startswith('b') and m not in ('btst.b', 'bset.b', 'bclr.b', 'bchg.b'):
                t = i.address + 2 + struct.unpack('>b', bytes(code[off + 1:off + 2]))[0]
                if not (f <= t < f + n):
                    raise SystemExit(f'{i.address:#x}: short branch out of the function')
            if '(pc' in i.op_str:
                raise SystemExit(f'{i.address:#x}: PC-relative operand {i.op_str}')
            raw = bytes(code[off:off + i.size])
            k = raw.find(struct.pack('>I', TABLE))
            if k > 0:
                struct.pack_into('>I', code, off + k, table_new)
            for t in (TABLE + 1, TABLE + 2, TABLE + 4):
                if raw.find(struct.pack('>I', t)) > 0:
                    raise SystemExit(f'{i.address:#x}: reference into the middle of TABLE')
        put(img, new[f], bytes(code))
    return new


def prepare(beta1, nfz=0, low=0):
    """Steps 1-4 on build 2 (origfilt=True): compaction, stock code relocated, E-mu vtables restored.
    nfz = 0: the OrigFilt list (8 empty OB-Xa slots 21-28, LP+Fuzz at 29); the OB-Xa vtable room is reserved first.
    nfz > 0: build_beta2's NFZ list (21 E-mu, nfz empty slots, the default) and no OB-Xa vtables (build_fuzzob.py);
    low bytes are then reserved first below 0x7FFFE (the list's reach) and returned as 'low'.
    Returns a dict with the image and its layout; the caller places its vtables and writes the header."""
    stock = open(STOCK, 'rb').read()
    with tempfile.TemporaryDirectory() as td:
        b2 = os.path.join(td, 'b2.bin')
        build_beta2.build(beta1, b2, origfilt=True, nfz=nfz)
        syms_l = dict(build_beta2.build.syms_l)
        img = bytearray(open(b2, 'rb').read())
        syms = json.load(open(b2 + '.syms.json'))
    first = struct.pack('>3H', 0x8878 // 2, 0x88A4 // 2, 0x88D0 // 2)
    i = img.find(first, 0x67F98 - BASE, 0x683F0 - BASE)
    if i < 0 or img.find(first, i + 1, 0x683F0 - BASE) >= 0:
        raise SystemExit('origfilt vtable list not found (once) in the ctor region')
    vtlist = i + BASE
    # 1. checks on the beta2 base
    for k, (vt, _, _, _) in enumerate(FILTERS):
        if struct.unpack('>H', img[vtlist + 2 * k - BASE:vtlist + 2 * k + 2 - BASE])[0] * 2 + 0x60000 != vt:
            raise SystemExit('vtable list does not start with the eight filters')
    for k in range(21, 21 + (nfz or 8)):
        if img[vtlist + 2 * k - BASE:vtlist + 2 * k + 2 - BASE] != b'\0\0':
            raise SystemExit(f'list slot {k} not empty')
    for f, n in LP_GROUP + HPBP_GROUP:
        if img[f - BASE:f - BASE + n] == stock[f - BASE:f - BASE + n]:
            raise SystemExit(f'{f:#x} is still stock: nothing to restore?')
    for vt, _, _, _ in FILTERS:
        for s in (0, 1, 2, 8, 9, 10):
            if u32(img, vt + 4 * s) != u32(stock, vt + 4 * s):
                raise SystemExit(f'vtable {vt:#x} slot {s} differs from stock')
    # 2. disk-unit compaction
    img = bytearray(unitcompact.apply(bytes(img)))
    put(img, FREED[0], b'\0' * (FREED[1] - FREED[0]))
    # free holes
    holes = Holes()
    pm_lo = PM_END
    while img[pm_lo - 2 - BASE:pm_lo - BASE] == b'\x4e\x71':
        pm_lo -= 2
    f_lo = F_END
    while img[f_lo - 2 - BASE:f_lo - BASE] == b'\x4e\x71':
        f_lo -= 2
    v_lo = V16[1]
    while u32(img, v_lo - 4) == DEFAULT_VEC:
        v_lo -= 4
    # 3. relocate the stock code
    if PM_END - pm_lo < sum(n for _, n in LP_GROUP):
        raise SystemExit(f'.blkPM tail {PM_END - pm_lo} < LP group')
    lp_dest = (pm_lo + 3) & ~3
    holes.add(FREED[0], FREED[1], 'freed unit tables')
    # the OB-Xa vtables first: the ctor's (vtable - 0x60000) / 2 list only reaches 0x7FFFE
    vt_slots = [] if nfz else [holes.take(VT_LEN, 4, 'OB-Xa vtable', below=0x7FFFE) for _ in FILTERS]
    low_blk = holes.take(low, 4, 'list-range block', below=0x7FFFE) if nfz and low else None
    table_new = holes.take(TABLE_LEN, 4, 'TABLE copy')
    put(img, table_new, stock[TABLE - BASE:TABLE - BASE + TABLE_LEN])
    hp_dest = holes.take(sum(n for _, n in HPBP_GROUP), 4, 'HP/BP group')
    new = relocate(img, stock, LP_GROUP, lp_dest, table_new)
    new.update(relocate(img, stock, HPBP_GROUP, hp_dest, table_new))
    holes.add(lp_dest + sum(n for _, n in LP_GROUP), PM_END, '.blkPM tail')
    holes.add(f_lo, F_END, '.blkF tail')
    holes.add(v_lo, V16[1], 'vectors 0x20240')
    # duplicate strings
    for drop, keep, sites in FOLD:
        s = bytes(img[drop - BASE:img.index(b'\0', drop - BASE) + 1])
        if bytes(img[keep - BASE:keep - BASE + len(s)]) != s:
            raise SystemExit(f'{drop:#x} and {keep:#x} differ')
        refs = all_refs(img, drop, drop + len(s))
        if sorted(r for r, _ in refs) != sorted(sites):
            raise SystemExit(f'references to {drop:#x}: {[hex(r) for r, _ in refs]}')
        for x in sites:
            if img[x - 2 - BASE:x + 4 - BASE] != b'\x48\x79' + struct.pack('>I', drop):
                raise SystemExit(f'{x - 2:#x} is not pea.l {drop:#x}')
            put(img, x, struct.pack('>I', keep))
        put(img, drop, b'\0' * len(s))
        holes.add(drop, drop + len(s), f'string {drop:#x}')
    # 4. E-mu vtables back to stock (code copies where moved)
    base_vt = {vt: [u32(img, vt + 4 * s) for s in range(11)] for vt, _, _, _ in FILTERS}
    for vt, ename, _, _ in FILTERS:
        for s in range(11):
            v = u32(stock, vt + 4 * s)
            if v in new:
                v = new[v]
            elif s in (3, 4) and vt in (0x68878, 0x688A4, 0x688D0):
                v = base_vt[vt][s]                  # beta2's LP type/name stubs: same results as stock
            elif BASE <= v < 0x200000 and s >= 3:
                if img[v - BASE:v - BASE + 4] != stock[v - BASE:v - BASE + 4]:
                    raise SystemExit(f'{ename} slot {s}: {v:#x} is not stock code')
            put(img, vt + 4 * s, struct.pack('>I', v))
    return dict(img=img, stock=stock, syms=syms, syms_l=syms_l, vtlist=vtlist, holes=holes, new=new, base_vt=base_vt,
                lp_dest=lp_dest, hp_dest=hp_dest, table_new=table_new, vt_slots=vt_slots, low=low_blk)


def build(beta1, out, name=NAME):
    P = prepare(beta1)
    img, syms, vtlist, holes, new, base_vt = P['img'], P['syms'], P['vtlist'], P['holes'], P['new'], P['base_vt']
    lp_dest, hp_dest, table_new, vt_slots = P['lp_dest'], P['hp_dest'], P['table_new'], P['vt_slots']
    # 5. OB-Xa vtables, names, type/name methods
    placed = {}
    for vt, _, oname, tid in FILTERS:
        nvt = vt_slots.pop(0)
        na = holes.take(len(oname) + 1, 1, 'name')
        put(img, na, oname + b'\0')
        ts = holes.take(4, 2, 'type method')
        put(img, ts, bytes([0x70, tid, 0x4E, 0x75]))                       # moveq #id,d0 ; rts
        ns = holes.take(8, 2, 'name method')
        put(img, ns, b'\x20\x3c' + struct.pack('>I', na) + b'\x4e\x75')    # move.l #name,d0 ; rts
        slots = list(base_vt[vt])
        slots[3], slots[4] = ts, ns
        put(img, nvt, b''.join(struct.pack('>I', v) for v in slots))
        placed[oname.decode()] = (nvt, tid, na)
    for k, (vt, _, oname, _) in enumerate(FILTERS):
        nvt = placed[oname.decode()][0]
        if nvt % 2 or not 0x60000 <= nvt <= 0x7FFFE:
            raise SystemExit('vtable out of the list range')
        struct.pack_into('>H', img, vtlist + 2 * (21 + k) - BASE, (nvt - 0x60000) // 2)
    # header
    if len(name) > 24:
        raise SystemExit('name too long')
    img[0x18:0x30] = name.ljust(24, b' ')
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    open(out, 'wb').write(img)
    info = dict(lp_group=lp_dest, hpbp_group=hp_dest, table=table_new, new={hex(k): v for k, v in new.items()},
                obxa={k: dict(vtable=v[0], type=v[1], name=v[2]) for k, v in placed.items()}, free_left=holes.free(),
                vtlist=vtlist)
    json.dump(info, open(out + '.origfilt.json', 'w'), indent=1)
    json.dump(syms, open(out + '.syms.json', 'w'), indent=1)          # build 2's symbols (feature tests)
    print(f'{out}: checksum {c:08x}; name {name.decode()!r}; LP group {lp_dest:#x}, HP/BP group {hp_dest:#x}, '
          f'table {table_new:#x}; {holes.free()} bytes left in the holes')
    return info


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3].encode() if len(sys.argv) > 3 else NAME)
