#!/usr/bin/env python3
"""Compaction: fold the disk-unit function tables (notes/compaction.md, candidate 1).

EOS 4.70 has two tables of 45 identical 22-byte records in flash at 0x7F9CE (A) and 0x7FDAC (B), 0x7F9CE-0x8018A:
  0000, then pointers 0x7F89C, 0x7F8A8, 0x7F8B4, 0x7F8B8, 0x7F898.
21 sites read them as `movea.l #table(+field),aN; ... muls (unit * 22); adda.l d0,aN` (or an indexed (aN,d0.l)
load) and then only fetch function pointers through aN for `jsr (a0)`. Every record is identical, so:
  - each `adda.l d0,aN` becomes `nop` and each `d(aN,d0.l)` load becomes `d(aN)`: aN stays on record 0, and d0 and
    the flags are as in stock;
  - table B's bases (0x7FDAC, 0x7FDBA) are repointed to table A (0x7F9CE, 0x7F9DC);
  - 0x7F9E4-0x8018A (1,958 bytes) is then unreferenced (proved by the reference scan in notes/compaction.md).
usage: unitcompact.py IN.bin OUT.bin [--fill] [--name NAME]
  --fill: write 0xA5 into the freed block (a leftover reader then jumps to 0xA5A5A5A5 and crashes instead of
          silently working)
  --name: set the header name (24 bytes) and recompute the image checksum, for a flashable image
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eos_lz            # noqa: E402

BASE = 0x20000
TABLE_A, TABLE_B, REC, NREC = 0x7F9CE, 0x7FDAC, 22, 45
FREE = (TABLE_A + REC, TABLE_B + NREC * REC)            # 0x7F9E4 .. 0x8018A
RECORD = bytes.fromhex('0000' '0007f89c' '0007f8a8' '0007f8b4' '0007f8b8' '0007f898')
# (site of the movea, address of the instruction to patch, stock bytes, new bytes)
ADDA = [(0x80588, 0x8059C, 'd5c0'), (0x80730, 0x80744, 'd9c0'), (0x80C72, 0x80C94, 'dbc0'),
        (0x86098, 0x860BA, 'd7c0'), (0x84E58, 0x84E80, 'd1c0'), (0x84F28, 0x84F3E, 'd1c0'),
        (0x85394, 0x853A6, 'd1c0'), (0x89E9C, 0x89EBC, 'd1c0'), (0x89F28, 0x89F46, 'd1c0'),
        (0x8A0C2, 0x8A0E4, 'd1c0'), (0x8A242, 0x8A270, 'd1c0'), (0x8AC22, 0x8AC50, 'd1c0'),
        (0x8B766, 0x8B782, 'd1c0'), (0x8B7A8, 0x8B7C4, 'd1c0'), (0x8AEDE, 0x8AEF4, 'd1c0'),
        (0x8941E, 0x89442, 'd1c0'), (0x894A6, 0x894C0, 'd1c0'), (0x8B442, 0x8B462, 'd1c0'),
        (0x8B5A4, 0x8B5BE, 'd1c0')]
INDEXED = [(0x85246, 0x85270, '2073080e', '206b000e'),    # movea.l $e(a3,d0.l),a0 -> movea.l $e(a3),a0
           (0x85246, 0x852B2, '2073080e', '206b000e'),    # the same function reads the table a second time
           (0x873E2, 0x8740A, '20740802', '206c0002'),    # movea.l $2(a4,d0.l),a0 -> movea.l $2(a4),a0
           (0x873E2, 0x87772, '2074080e', '206c000e')]    # later read with the offset saved in -8(a6)
REBASE = {TABLE_B: TABLE_A, TABLE_B + 14: TABLE_A + 14}   # movea.l #imm at site+2
SITES = [s for s, _, _ in ADDA] + [s for s, _, _, _ in INDEXED]


def u32(img, a):
    return struct.unpack('>I', img[a - BASE:a - BASE + 4])[0]


def apply(img, fill=False):
    img = bytearray(img)
    for k in range(2 * NREC):
        a = TABLE_A + k * REC
        if img[a - BASE:a - BASE + REC] != RECORD:
            raise SystemExit(f'unit table record {k} at {a:#x} is not the stock record')
    for s in SITES:
        if img[s - BASE] & 0xF1 != 0x20 or img[s - BASE + 1] & 0x3F != 0x3C:   # movea.l #imm,An
            raise SystemExit(f'{s:#x} is not movea.l #imm')
        if u32(img, s + 2) not in (TABLE_A, TABLE_A + 10, TABLE_A + 14, TABLE_B, TABLE_B + 14):
            raise SystemExit(f'{s:#x} does not load a unit table address')
    for s, a, stock in ADDA:
        if img[a - BASE:a - BASE + 2].hex() != stock:
            raise SystemExit(f'{a:#x}: expected {stock}')
        img[a - BASE:a - BASE + 2] = b'\x4e\x71'
    for s, a, stock, new in INDEXED:
        if img[a - BASE:a - BASE + 4].hex() != stock:
            raise SystemExit(f'{a:#x}: expected {stock}')
        img[a - BASE:a - BASE + 4] = bytes.fromhex(new)
    for s in SITES:
        v = u32(img, s + 2)
        if v in REBASE:
            struct.pack_into('>I', img, s + 2 - BASE, REBASE[v])
    left = indexed_uses(img)
    if left:
        raise SystemExit('unpatched indexed table uses: ' + ', '.join(f'{a:#x} {t}' for a, t in left))
    if fill:
        img[FREE[0] - BASE:FREE[1] - BASE] = b'\xa5' * (FREE[1] - FREE[0])
    return bytes(img)


def indexed_uses(img):
    """Every `d(aN,Xn)` or `adda/suba ..,aN` reachable from each site's movea while aN still holds the table:
    a walk over all branch paths (both arms of each conditional branch, bra/jmp targets, calls fall through) that
    stops a path at rts or where aN is reassigned. A computed jump on such a path is reported too.
    After apply() the list must be empty."""
    import capstone, re
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_040)
    left = []
    for s in dict.fromkeys(SITES):
        reg = next(md.disasm(img[s - BASE:s - BASE + 6], s)).op_str.split(',')[-1].strip()
        todo, seen = [s + 6], set()
        while todo:
            a = todo.pop()
            if a in seen or not (BASE <= a < BASE + len(img)):
                continue
            seen.add(a)
            i = next(md.disasm(img[a - BASE:a - BASE + 12], a), None)
            if i is None:
                continue
            ops = [o.strip() for o in i.op_str.split(',')]
            m = i.mnemonic.split('.')[0]
            if re.search(r'\(\s*' + reg + r'\s*,', i.op_str) or (m in ('adda', 'suba') and ops[-1] == reg):
                left.append((a, f'{i.mnemonic} {i.op_str}'))
            if m in ('rts', 'rte'):
                continue
            if ops and ops[-1] == reg and m in ('movea', 'lea', 'move') and reg not in ','.join(ops[:-1]):
                continue                                            # aN reassigned: this path is done
            tgt = re.search(r'\$([0-9a-f]+)$', i.op_str)
            if m in ('bra', 'jmp'):
                if tgt and m == 'bra' or (m == 'jmp' and i.op_str.startswith('$')):
                    todo.append(int(tgt.group(1), 16))
                else:
                    left.append((a, f'computed jump {i.mnemonic} {i.op_str}'))
                continue
            if m.startswith('b') and m not in ('bsr', 'btst', 'bset', 'bclr', 'bchg') and tgt:
                todo.append(int(tgt.group(1), 16))                  # conditional branch: taken arm
            if m.startswith('db') and tgt:
                todo.append(int(tgt.group(1), 16))
            todo.append(a + i.size)                                 # fall through (and after calls)
    return sorted(set(left))


def finish(img, name):
    """Header name (as build_beta2.py) and the loader checksum."""
    img = bytearray(img)
    img[0x18:0x30] = name.encode().ljust(24, b' ')[:24]
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    return bytes(img), c


if __name__ == '__main__':
    src = open(sys.argv[1], 'rb').read()
    out = apply(src, '--fill' in sys.argv)
    note = ''
    if '--name' in sys.argv:
        out, c = finish(out, sys.argv[sys.argv.index('--name') + 1])
        note = f'; name {out[0x18:0x30].decode().rstrip()!r}, checksum {c:08x}'
    open(sys.argv[2], 'wb').write(out)
    print(f'{sys.argv[2]}: {len(dict.fromkeys(SITES))} sites, {len(ADDA) + len(INDEXED)} instructions patched; '
          f'free {FREE[0]:#x}-{FREE[1]:#x} ({FREE[1] - FREE[0]} bytes){note}')
