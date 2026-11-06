#!/usr/bin/env python3
"""Reference reader/writer for E-mu E4 bank files (.E4B), EOS 4.x. Spec: notes/specs/e4b_format.md.

Written from the spec; contains no E-mu code or data. Every record keeps its raw bytes, and fields are views onto
them, so parse -> write is byte-exact for chunks this module understands.

  bank = read_bank(open('x.E4B', 'rb').read())
  bank.presets[0].voices[0]['volume'] = -6
  open('y.E4B', 'wb').write(write_bank(bank))

  # building from scratch
  s = Sample.from_pcm(1, 'Sine', 44100, left=pcm_bytes_le16, loop=(start, end))
  v = Voice.new([Zone.new(sample=1, key_low=0, key_high=127, orig_key=60)])
  p = Preset.new(0, 'My Preset', [v])
  data = write_bank(Bank(presets=[p], samples=[s]))

usage: e4b_ref.py dump BANK.E4B      print presets, voices, zones and samples
"""
import math
import struct
import sys

# ---------------------------------------------------------------- field tables
# name: (offset, struct format, SysEx parameter id or None)

PRESET_FIELDS = {
    'voice_offset': (0x10, '>H', None),     # always 0x52
    'voice_count':  (0x12, '>H', None),
    'link_count':   (0x14, '>H', None),     # always 0 in every bank seen; links are not described here
    'transpose':    (0x18, 'b', 0),
    'volume':       (0x19, 'b', 1),
    'ctrl_a':       (0x36, 'b', 2), 'ctrl_b': (0x37, 'b', 3), 'ctrl_c': (0x38, 'b', 4), 'ctrl_d': (0x39, 'b', 5),
    'fxa_algorithm': (0x3a, 'B', 6),
    'fxa_parm0': (0x3b, 'B', 7), 'fxa_parm1': (0x3c, 'B', 8), 'fxa_parm2': (0x3d, 'B', 9),
    'fxa_send0': (0x3e, 'B', 10), 'fxa_send1': (0x3f, 'B', 11), 'fxa_send2': (0x40, 'B', 12), 'fxa_send3': (0x41, 'B', 13),
    'fxb_algorithm': (0x42, 'B', 14),
    'fxb_parm0': (0x43, 'B', 15), 'fxb_parm1': (0x44, 'B', 16), 'fxb_parm2': (0x45, 'B', 17),
    'fxb_send0': (0x46, 'B', 18), 'fxb_send1': (0x47, 'B', 19), 'fxb_send2': (0x48, 'B', 20), 'fxb_send3': (0x49, 'B', 21),
}
PRESET_HEADER = 0x52
# typical values of the bytes with no known meaning (spec §4.2)
PRESET_TYPICAL = {0x1a: 0x78, 0x32: 0x52, 0x33: 0x23, 0x35: 0x7e}

VOICE_FIELDS = {
    'size':        (0x00, '>H', None),
    'zone_count':  (0x02, 'B', None),
    'group':       (0x03, 'B', 37),         # 0..31 = group 1..32
    'key_low': (0x0c, 'B', 45), 'key_low_fade': (0x0d, 'B', 46),
    'key_high_fade': (0x0e, 'B', 48), 'key_high': (0x0f, 'B', 47),
    'vel_low': (0x10, 'B', 49), 'vel_low_fade': (0x11, 'B', 50),
    'vel_high_fade': (0x12, 'B', 52), 'vel_high': (0x13, 'B', 51),
    'rt_low': (0x14, 'B', 53), 'rt_low_fade': (0x15, 'B', 54),
    'rt_high_fade': (0x16, 'B', 56), 'rt_high': (0x17, 'B', 55),
    'assign_group': (0x19, 'B', 66),
    'delay_ms':     (0x1a, '>H', 61),
    'start_offset': (0x1e, '>H', 62),
    'transpose':    (0x20, 'b', 43),
    'coarse_tune':  (0x21, 'b', 41),
    'fine_tune':    (0x22, 'b', 42),
    'glide_rate':   (0x23, 'B', 63),
    'non_transpose': (0x24, 'B', 57),
    'solo_mode':    (0x25, 'B', 65),
    'chorus_width': (0x27, 'b', 59),
    'chorus_amount': (0x28, 'B', 58),
    'chorus_itd':   (0x2a, 'b', 60),
    'latch':        (0x30, 'B', 67),
    'glide_curve':  (0x33, 'B', 64),
    'volume':       (0x34, 'b', 39),
    'pan':          (0x35, 'b', 40),
    'submix':       (0x36, 'B', 69),
    'amp_env_depth': (0x37, 'B', 68),
    'filter_type':  (0x38, 'B', 82),        # filter ID, not the menu index (FILTER_IDS)
    'filter_freq':  (0x3a, 'B', 83),
    'filter_q':     (0x3b, 'B', 84),
    'lfo1_rate': (0x96, 'B', 105), 'lfo1_shape': (0x97, 'B', 106), 'lfo1_delay': (0x98, 'B', 107),
    'lfo1_var': (0x99, 'B', 108), 'lfo1_sync': (0x9a, 'B', 109),
    'lfo2_rate': (0x9e, 'B', 110), 'lfo2_shape': (0x9f, 'B', 111), 'lfo2_delay': (0xa0, 'B', 112),
    'lfo2_var': (0xa1, 'B', 113), 'lfo2_sync': (0xa2, 'B', 114),
    'lag0': (0xa5, 'B', 115), 'lag1': (0xa7, 'B', 116),
}
for _k in range(8):
    VOICE_FIELDS[f'filter_parm{_k + 1}'] = (0x3c + _k, 'B', 85 + _k)
SEGMENTS = ('atk1', 'atk2', 'dcy1', 'dcy2', 'rls1', 'rls2')
for _env, _base, _id, _lvl in (('amp', 0x6c, 70, 'B'), ('filt', 0x7a, 93, 'b'), ('aux', 0x88, 117, 'b')):
    for _s, _seg in enumerate(SEGMENTS):
        VOICE_FIELDS[f'{_env}_{_seg}_rate'] = (_base + 2 * _s, 'B', _id + 2 * _s)
        VOICE_FIELDS[f'{_env}_{_seg}_level'] = (_base + 2 * _s + 1, _lvl, _id + 2 * _s + 1)
for _c in range(18):
    VOICE_FIELDS[f'cord{_c}_src'] = (0xbc + 4 * _c, 'B', 129 + 3 * _c)
    VOICE_FIELDS[f'cord{_c}_dst'] = (0xbd + 4 * _c, 'B', 130 + 3 * _c)
    VOICE_FIELDS[f'cord{_c}_amount'] = (0xbe + 4 * _c, 'b', 131 + 3 * _c)
VOICE_HEADER = 0x11c
# stored as -127..127 (or 0..127), shown and sent over SysEx as -100..100 % (spec §5.3)
SCALED = {k for k in VOICE_FIELDS if k.endswith('_level') or k.startswith('cord') and k.endswith('_amount')} | \
    {'chorus_amount', 'lfo1_var', 'lfo2_var'}


def to_percent(raw):
    """Stored value -> percent as the E4 shows it (and as SysEx parameters carry it)."""
    p = abs(raw) * 100 / 127
    return int(p + 0.5) * (1 if raw >= 0 else -1)


def from_percent(pct):
    """Percent -> stored value (to_percent(from_percent(p)) == p for -100..100)."""
    r = int(abs(pct) * 127 / 100 + 0.5)
    return r * (1 if pct >= 0 else -1)


VOICE_DEFAULTS = {
    'key_high': 127, 'vel_high': 127, 'rt_high': 127,
    'filter_type': 0, 'filter_freq': 255, 'filter_q': 0,
    'amp_atk2_level': 127, 'amp_dcy1_level': 126, 'amp_dcy2_level': 127, 'amp_rls1_rate': 20,
    'filt_atk2_level': 127, 'filt_dcy1_level': 126, 'filt_dcy2_level': 127, 'filt_rls1_rate': 20,
    'aux_atk2_level': 127, 'aux_dcy1_level': 126, 'aux_dcy2_level': 127, 'aux_rls1_rate': 20,
    'lfo1_rate': 64, 'lfo2_rate': 64,
    # the cords most banks carry (spec §5.4)
    'cord0_src': 12, 'cord0_dst': 64, 'cord0_amount': 30,      # Vel<   -> AmpVol
    'cord1_src': 16, 'cord1_dst': 48, 'cord1_amount': 8,       # PitWl  -> Pitch
    'cord2_src': 96, 'cord2_dst': 48,                          # Lfo1~  -> Pitch
    'cord3_src': 17, 'cord3_dst': 170, 'cord3_amount': 8,      # ModWl  -> C02Amt
    'cord4_src': 12, 'cord4_dst': 56,                          # Vel<   -> FilFreq
    'cord5_src': 80, 'cord5_dst': 56,                          # FEnv+  -> FilFreq
    'cord6_src': 8, 'cord6_dst': 56,                           # Key+   -> FilFreq
    'cord7_src': 22, 'cord7_dst': 8, 'cord7_amount': 127,      # FtSw1  -> KeySust
}
VOICE_TYPICAL = {0x1c: 0xff, 0x1d: 0xff, 0x26: 0x01, 0x78: 0x03, 0x86: 0x03, 0x94: 0x03}

ZONE_FIELDS = {
    'key_low': (0x00, 'B', 45), 'key_low_fade': (0x01, 'B', 46),
    'key_high_fade': (0x02, 'B', 48), 'key_high': (0x03, 'B', 47),
    'vel_low': (0x04, 'B', 49), 'vel_low_fade': (0x05, 'B', 50),
    'vel_high_fade': (0x06, 'B', 52), 'vel_high': (0x07, 'B', 51),
    'sample':    (0x08, '>H', 38),
    'fine_tune': (0x0a, '>h', 42),
    'orig_key':  (0x0c, 'B', 44),
    'volume':    (0x0d, 'b', 39),
    'pan':       (0x0e, 'b', 40),
}
ZONE_SIZE = 22

# menu index (SysEx value of parameter 82) -> filter ID stored in the voice
FILTER_IDS = [1, 0, 2, 8, 9, 16, 17, 18, 32, 33, 34, 64, 65, 66, 72, 80, 81, 96, 97, 98, 104]
FILTER_NAMES = ['2 Pole Low-pass', '4 Pole Low-pass', '6 Pole Low-pass', '2nd Order High-pass',
                '4th Order High-pass', '2nd Order Band-pass', '4th Order Band-pass', 'Contrary Band-pass',
                'Swept EQ 1 octave', 'Swept EQ 2->1 oct', 'Swept EQ 3->1 oct', 'Phaser 1', 'Phaser 2',
                'Bat-Phaser', 'Flanger Lite', 'Vocal Ah-Ay-Ee', 'Vocal Oo-Ah', 'Dual EQ Morph',
                '2EQ+Lowpass Morph', '2EQMorph+Exprssn', 'Peak/Shelf Morph']

# sample header: 19 little-endian longs after the name (offsets relative to the name)
SAMPLE_FIELDS = {
    'unused0':    (0x10, '<I'),   # not checked by the loader; write 0
    'start_l':    (0x14, '<I'), 'start_r':    (0x18, '<I'),
    'end_l':      (0x1c, '<I'), 'end_r':      (0x20, '<I'),
    'loop_start_l': (0x24, '<I'), 'loop_start_r': (0x28, '<I'),
    'loop_end_l': (0x2c, '<I'), 'loop_end_r': (0x30, '<I'),
    'rate':       (0x34, '<I'),
    'pitch':      (0x38, '<h'),   # 1/64 semitone; pitch_for_rate()
    'flags':      (0x3a, '<H'),
}
SAMPLE_HEADER = 0x5c               # name (16) + 19 longs; PCM starts here
F_LOOP, F_LOOP_IN_RELEASE, F_LOOP_ALIGN, F_LEFT, F_RIGHT = 0x01, 0x08, 0x10, 0x20, 0x40
LOOP_GUARD_START, LOOP_GUARD_END = 6, 5   # frames the loader requires before the loop and after it


def pitch_for_rate(rate):
    """Pitch word EOS writes for an untuned sample of this rate (matches 75 % of 27,113 samples; the rest
    were retuned on the E4)."""
    return int(768 * math.log2(rate / 44053))


def name16(s):
    b = s.encode('ascii', 'replace')[:16] if isinstance(s, str) else bytes(s)[:16]
    return b.ljust(16, b' ')


# ---------------------------------------------------------------- records

class Record:
    FIELDS = {}

    def __init__(self, raw):
        self.raw = bytearray(raw)

    def __getitem__(self, k):
        off, fmt = self.FIELDS[k][:2]
        return struct.unpack_from(fmt, self.raw, off)[0]

    def __setitem__(self, k, v):
        off, fmt = self.FIELDS[k][:2]
        struct.pack_into(fmt, self.raw, off, v)

    def fields(self):
        return {k: self[k] for k in self.FIELDS}


class Zone(Record):
    FIELDS = ZONE_FIELDS

    @classmethod
    def new(cls, **kw):
        z = cls(bytes(ZONE_SIZE))
        z['key_high'] = z['vel_high'] = 127
        z['orig_key'] = 60
        for k, v in kw.items():
            z[k] = v
        return z


class Voice(Record):
    FIELDS = VOICE_FIELDS

    def __init__(self, raw, zones=()):
        super().__init__(raw[:VOICE_HEADER])
        self.zones = list(zones)

    @classmethod
    def new(cls, zones, **kw):
        v = cls(bytes(VOICE_HEADER), zones)
        for off, b in VOICE_TYPICAL.items():
            v.raw[off] = b
        for k, x in {**VOICE_DEFAULTS, **kw}.items():
            v[k] = x
        return v

    def to_bytes(self):
        self['size'] = VOICE_HEADER + ZONE_SIZE * len(self.zones)
        self['zone_count'] = len(self.zones)
        return bytes(self.raw) + b''.join(bytes(z.raw) for z in self.zones)


class Preset(Record):
    FIELDS = PRESET_FIELDS

    def __init__(self, index, raw, voices=()):
        super().__init__(raw[:PRESET_HEADER])
        self.index = index
        self.voices = list(voices)

    @property
    def name(self):
        return bytes(self.raw[:16]).rstrip(b'\0 ').decode('latin1')

    @classmethod
    def new(cls, index, name, voices, **kw):
        p = cls(index, bytes(PRESET_HEADER), voices)
        p.raw[:16] = name16(name)
        for off, b in PRESET_TYPICAL.items():
            p.raw[off] = b
        p['voice_offset'] = PRESET_HEADER
        p['ctrl_a'] = p['ctrl_b'] = p['ctrl_c'] = p['ctrl_d'] = -1
        for k, x in kw.items():
            p[k] = x
        return p

    def to_bytes(self):
        self['voice_count'] = len(self.voices)
        return bytes(self.raw) + b''.join(v.to_bytes() for v in self.voices)


class Sample(Record):
    FIELDS = SAMPLE_FIELDS

    def __init__(self, index, raw):
        super().__init__(raw)
        self.index = index

    @property
    def name(self):
        return bytes(self.raw[:16]).rstrip(b'\0 ').decode('latin1')

    @property
    def stereo(self):
        return self['flags'] & (F_LEFT | F_RIGHT) == F_LEFT | F_RIGHT

    @classmethod
    def from_pcm(cls, index, name, rate, left, right=None, loop=None, loop_in_release=False):
        """left/right: 16-bit little-endian PCM bytes (equal length if stereo). loop: (start, end) in sample
        frames, end exclusive (the frame after the last looped one). The loader needs
        LOOP_GUARD_START <= start < end <= frames - LOOP_GUARD_END (spec §6.3); without a loop the points are
        set to that window, as EOS does."""
        n = len(left) // 2
        if right is not None and len(right) != len(left):
            raise ValueError('left and right must have the same length')
        if loop and not LOOP_GUARD_START <= loop[0] < loop[1] <= n - LOOP_GUARD_END:
            raise ValueError(f'loop {loop} outside {LOOP_GUARD_START}..{n - LOOP_GUARD_END} frames')
        s = cls(index, bytes(SAMPLE_HEADER))
        s.raw[:16] = name16(name)
        ls, le = loop if loop else (LOOP_GUARD_START, max(LOOP_GUARD_START, n - LOOP_GUARD_START))
        start_l = SAMPLE_HEADER
        s['start_l'], s['end_l'] = start_l, start_l + 2 * n
        s['loop_start_l'], s['loop_end_l'] = start_l + 2 * ls, start_l + 2 * le
        flags = F_LOOP_ALIGN | F_LEFT | (F_LOOP if loop else 0) | (F_LOOP_IN_RELEASE if loop_in_release else 0)
        pcm = bytes(left)
        if right is not None:
            start_r = start_l + 2 * n + 2           # one pad word between the channel blocks, as EOS writes
            s['start_r'], s['end_r'] = start_r, start_r + 2 * n
            s['loop_start_r'], s['loop_end_r'] = start_r + 2 * ls, start_r + 2 * le
            flags |= F_RIGHT
            pcm += b'\0\0' + bytes(right)
        s['rate'], s['pitch'], s['flags'] = rate, pitch_for_rate(rate), flags
        s.raw += pcm
        return s

    def to_bytes(self):
        return bytes(self.raw)


class Bank:
    def __init__(self, presets=(), samples=(), other=()):
        self.presets, self.samples, self.other = list(presets), list(samples), list(other)


# ---------------------------------------------------------------- file level

def chunk_offsets(data):
    """(type, offset) of every chunk: from the TOC when there is one, else by walking the chunks (older banks
    have no TOC, spec §2)."""
    if data[:4] != b'FORM' or data[8:12] != b'E4B0':
        raise ValueError('not an E4B file')
    if data[12:16] == b'TOC1':
        toc_len = struct.unpack_from('>I', data, 16)[0]
        for k in range(toc_len // 32):
            ctype, size, off, index = struct.unpack_from('>4sIIH', data, 20 + 32 * k)
            if data[off:off + 4] == ctype:          # skip stale or blank TOC entries
                yield ctype, off, 20 + 32 * k
        return
    off, end = 12, min(len(data), 8 + struct.unpack_from('>I', data, 4)[0])
    while off + 10 <= end:
        clen = struct.unpack_from('>I', data, off + 4)[0]
        yield data[off:off + 4], off, None
        off += 8 + clen + (clen & 1)


def read_bank(data):
    bank = Bank()
    for ctype, off, toc in chunk_offsets(data):
        index = struct.unpack_from('>H', data, off + 8)[0]
        clen = struct.unpack_from('>I', data, off + 4)[0]
        body = data[off + 10:off + 8 + clen]        # after the 2-byte index
        if ctype == b'E4P1':
            nv, pos, voices = struct.unpack_from('>H', body, 0x12)[0], PRESET_HEADER, []
            for _ in range(nv):
                vsize, nz = struct.unpack_from('>H', body, pos)[0], body[pos + 2]
                zones = [Zone(body[pos + VOICE_HEADER + ZONE_SIZE * z:pos + VOICE_HEADER + ZONE_SIZE * (z + 1)])
                         for z in range(nz)]
                voices.append(Voice(body[pos:pos + VOICE_HEADER], zones))
                pos += vsize
            bank.presets.append(Preset(index, body, voices))
        elif ctype == b'E3S1':
            bank.samples.append(Sample(index, body))
        else:
            name = data[toc + 14:toc + 30] if toc else data[off + 10:off + 26]
            bank.other.append((ctype, index, data[off + 10:off + 8 + clen], name))
    return bank


def write_bank(bank):
    """FORM 'E4B0', TOC1, then E4Ma/other chunks, presets, samples (the order EOS writes)."""
    items = [(t, i, body, nm) for t, i, body, nm in bank.other if t != b'EMSt']
    items += [(b'E4P1', p.index, p.to_bytes(), bytes(p.raw[:16])) for p in sorted(bank.presets, key=lambda p: p.index)]
    items += [(b'E3S1', s.index, s.to_bytes(), bytes(s.raw[:16])) for s in sorted(bank.samples, key=lambda s: s.index)]
    items += [(t, i, body, nm) for t, i, body, nm in bank.other if t == b'EMSt']
    toc, chunks = [], []
    off = 20 + 32 * len(items)
    for ctype, index, body, nm in items:
        clen = 2 + len(body)
        chunk = ctype + struct.pack('>IH', clen, index) + body + (b'\0' if clen & 1 else b'')
        toc.append(ctype + struct.pack('>IIH', clen - 2, off, index) + name16(nm) + b'\0\0')
        chunks.append(chunk)
        off += len(chunk)
    toc = b''.join(toc)
    inner = b'E4B0TOC1' + struct.pack('>I', len(toc)) + toc + b''.join(chunks)
    return b'FORM' + struct.pack('>I', len(inner)) + inner


# ---------------------------------------------------------------- dump

def dump(bank):
    for p in bank.presets:
        print(f'preset {p.index:03d} {p.name!r}: volume {p["volume"]} dB, transpose {p["transpose"]}, '
              f'{len(p.voices)} voice(s)')
        for n, v in enumerate(p.voices):
            ft = v['filter_type']
            fname = FILTER_NAMES[FILTER_IDS.index(ft)] if ft in FILTER_IDS else f'id {ft}'
            print(f'  voice {n}: keys {v["key_low"]}-{v["key_high"]}, vel {v["vel_low"]}-{v["vel_high"]}, '
                  f'vol {v["volume"]}, pan {v["pan"]}, filter {fname} {v["filter_freq"]}/{v["filter_q"]}, '
                  f'{len(v.zones)} zone(s)')
            for z in v.zones:
                print(f'    zone: sample {z["sample"]}, keys {z["key_low"]}-{z["key_high"]}, '
                      f'vel {z["vel_low"]}-{z["vel_high"]}, orig key {z["orig_key"]}, fine {z["fine_tune"]}')
    for s in bank.samples:
        frames = (s['end_l'] - s['start_l']) // 2 if s['flags'] & F_LEFT else (s['end_r'] - s['start_r']) // 2
        print(f'sample {s.index:03d} {s.name!r}: {s["rate"]} Hz, {"stereo" if s.stereo else "mono"}, '
              f'{frames} frames, loop {"on" if s["flags"] & 3 else "off"}, pitch {s["pitch"]}')
    for t, i, body, _ in bank.other:
        print(f'{t.decode("latin1")} {i}: {len(body)} bytes (kept as is)')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'dump':
        dump(read_bank(open(sys.argv[2], 'rb').read()))
    else:
        print(__doc__)
