#!/usr/bin/env python3
"""Make the redistributable 4.71-beta patch: only the bytes that differ from stock EOS 4.70.

usage: make_patch.py STOCK.bin PATCHED.bin OUT.e4p [--v2]
Version 1 (E4PATCH1): b'E4PATCH1', sha256(stock) 32, sha256(patched) 32, u32 image length, u8 name length, name,
u32 range count, then per range: u32 offset (image-relative), u32 length, bytes.
Ranges are exact runs of differing bytes (no unchanged stock bytes are included).

Version 2 (--v2, E4PATCH2): the same header with b'E4PATCH2', then u32 op count and the ops, applied in order:
  u8 0 (data), u32 offset, u32 length, bytes
  u8 1 (copy), u32 offset, u32 length, u32 source offset: the bytes come from the user's own stock 4.70 image
A build that moves stock code (e.g. the E-mu filter code relocated by build_origfilt.py) then carries no E-mu
code: inside each differing run, every stretch of at least MINCOPY bytes that also occurs in stock 4.70 becomes a
copy (the longest match; stretches of a single repeated byte value or of NOPs stay data). The tool then checks
that no data op still holds MINCOPY or more bytes found anywhere in stock, and that applying the ops gives PATCHED.
"""
import hashlib, struct, sys

MINCOPY = 8


def runs_of(a, b):
    runs, i = [], 0
    while i < len(a):
        if a[i] != b[i]:
            j = i
            while j < len(a) and a[j] != b[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def filler(s):
    return len(set(s)) == 1 or all(s[k:k + 2] == b'\x4e\x71' for k in range(0, len(s) - 1, 2))


def ops_v2(a, b):
    """[('data', off, bytes) | ('copy', off, length, src)] for the differing runs of b against a."""
    index = {}
    for i in range(len(a) - MINCOPY + 1):
        index.setdefault(a[i:i + MINCOPY], []).append(i)
    ops = []
    for lo, hi in runs_of(a, b):
        k, lit = lo, lo
        while k < hi:
            best = None
            key = b[k:k + MINCOPY]
            if k + MINCOPY <= hi and not filler(key):
                for s in index.get(key, [])[:256]:
                    n = MINCOPY
                    while k + n < hi and s + n < len(a) and a[s + n] == b[k + n]:
                        n += 1
                    if best is None or n > best[1]:
                        best = (s, n)
            if best:
                if lit < k:
                    ops.append(('data', lit, b[lit:k]))
                ops.append(('copy', k, best[1], best[0]))
                k += best[1]
                lit = k
            else:
                k += 1
        if lit < hi:
            ops.append(('data', lit, b[lit:hi]))
    return ops, index


def header(magic, a, b):
    name = b[0x18:0x30].rstrip(b' \0')
    return bytearray(magic + hashlib.sha256(a).digest() + hashlib.sha256(b).digest()) + \
        struct.pack('>IB', len(b), len(name)) + name


def main():
    a, b = (open(p, 'rb').read() for p in sys.argv[1:3])
    assert len(a) == len(b)
    if '--v2' not in sys.argv:
        runs = [(lo, b[lo:hi]) for lo, hi in runs_of(a, b)]
        out = header(b'E4PATCH1', a, b) + struct.pack('>I', len(runs))
        for off, data in runs:
            out += struct.pack('>II', off, len(data)) + data
        open(sys.argv[3], 'wb').write(out)
        img = bytearray(a)
        for off, data in runs:
            img[off:off + len(data)] = data
        assert bytes(img) == b, 'self-check failed'
        print(f'{sys.argv[3]}: {len(runs)} ranges, {sum(len(d) for _, d in runs)} bytes, {len(out)} bytes total')
        return
    ops, index = ops_v2(a, b)
    out = header(b'E4PATCH2', a, b) + struct.pack('>I', len(ops))
    for op in ops:
        if op[0] == 'data':
            out += struct.pack('>BII', 0, op[1], len(op[2])) + op[2]
        else:
            out += struct.pack('>BIII', 1, op[1], op[2], op[3])
    open(sys.argv[3], 'wb').write(out)
    img = bytearray(a)
    for op in ops:
        if op[0] == 'data':
            img[op[1]:op[1] + len(op[2])] = op[2]
        else:
            img[op[1]:op[1] + op[2]] = a[op[3]:op[3] + op[2]]
    assert bytes(img) == b, 'self-check failed'
    leaks = [(op[1] + i) for op in ops if op[0] == 'data' for i in range(len(op[2]) - MINCOPY + 1)
             if not filler(op[2][i:i + MINCOPY]) and op[2][i:i + MINCOPY] in index]
    assert not leaks, f'data ops still hold stock bytes at {[hex(x) for x in leaks[:8]]}'
    nd = sum(len(op[2]) for op in ops if op[0] == 'data')
    nc = sum(op[2] for op in ops if op[0] == 'copy')
    print(f'{sys.argv[3]}: {len(ops)} ops: {nd} data bytes, {nc} bytes copied from the user\'s 4.70 '
          f'({sum(op[0] == "copy" for op in ops)} copies); {len(out)} bytes total; no data op holds '
          f'{MINCOPY}+ stock bytes')


if __name__ == '__main__':
    main()
