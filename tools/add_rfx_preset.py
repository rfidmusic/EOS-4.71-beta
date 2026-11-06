#!/usr/bin/env python3
"""Add preset 004 'RFX Pan Sine' to the test bank: preset 000's voice with one zone, sample 1 (801 Hz sine,
orig key 72) on keys 0-127. The RFX stuck pan test holds 64-128 notes on spread keys to use every channel;
preset 000 only has zones on keys 72-79, so most of those notes would not sound.

usage: add_rfx_preset.py IN.E4B OUT.E4B
Byte surgery, not a rewrite: every original chunk, TOC entry and the trailing EMSt (not in the TOC, as EOS
writes it) is kept as is; the new E4P1 chunk goes after the last preset and its TOC entry after theirs.
"""
import copy, struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e4b_ref as e  # noqa: E402

INDEX, NAME = 4, 'RFX Pan Sine'


def main(src, dst):
    d = open(src, 'rb').read()
    assert d[:4] == b'FORM' and d[8:16] == b'E4B0TOC1'
    n = struct.unpack_from('>I', d, 16)[0] // 32
    toc = [bytearray(d[20 + 32 * k:52 + 32 * k]) for k in range(n)]
    bank = e.read_bank(d)
    if any(p.index == INDEX for p in bank.presets):
        raise SystemExit(f'preset {INDEX:03d} already exists')
    p0 = next(p for p in bank.presets if p.index == 0)
    v = copy.deepcopy(p0.voices[0])
    z = copy.deepcopy(next(z for z in v.zones if z['sample'] == 1))
    z['key_low'], z['key_high'] = 0, 127
    v.zones = [z]
    p = e.Preset(INDEX, bytes(p0.raw), [v])
    p.raw[:16] = e.name16(NAME)
    body = p.to_bytes()
    clen = 2 + len(body)
    chunk = b'E4P1' + struct.pack('>IH', clen, INDEX) + body + (b'\0' if clen & 1 else b'')
    # insert after the last E4P1 chunk
    offs = [struct.unpack_from('>I', t, 8)[0] for t in toc]
    last = max(k for k in range(n) if toc[k][:4] == b'E4P1')
    lo = offs[last]
    at = lo + 8 + struct.unpack_from('>I', d, lo + 4)[0]
    at += at & 1
    entry = b'E4P1' + struct.pack('>IIH', clen - 2, at + 32, INDEX) + e.name16(NAME) + b'\0\0'
    for t in toc:
        o = struct.unpack_from('>I', t, 8)[0]
        struct.pack_into('>I', t, 8, o + 32 + (len(chunk) if o >= at else 0))
    toc.insert(last + 1, bytearray(entry))
    head = d[:16] + struct.pack('>I', 32 * len(toc)) + b''.join(toc)
    out = head + d[20 + 32 * n:at] + chunk + d[at:]
    out = out[:4] + struct.pack('>I', len(out) - 8) + out[8:]
    open(dst, 'wb').write(out)
    print(f'{dst}: preset {INDEX:03d} {NAME!r}, {len(out)} bytes (+{len(out) - len(d)})')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
