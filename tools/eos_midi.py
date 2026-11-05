#!/usr/bin/env python3
"""EOS OS download over MIDI (MMA "MIDI File Dump"), as implemented by the
EOS Primary Loader PL01 01f05 (receiver code 0x17360..0x17C94).

Boot the sampler holding [Enter] -> "Download OS from MIDI?" -> Yes -> "Searching for OS...".
The loader requests file "EOSLoader" (type "CEXE"), accepts a header of type "EXE?"/"CEXE",
then feeds the received bytes through the same Lz77 decoder used for floppies.
So the file payload = the compressed stream (floppy image minus its 0x200-byte header).

Wire format (device ID must be 00 - the loader checksums with its own ID, which is 0):
  header : F0 7E 00 07 01 <src> 'E''X''E'' ' <len: 4 x 7-bit, LSB first> <name> F7
  packet : F0 7E 00 07 02 <pkt 0..7F wrap> <nbytes-1> <8-for-7 encoded data> <xor> F7
           (<=112 file bytes/packet; xor of every byte after F0 up to the checksum, & 7F)
  EOF    : F0 7E 00 7B <pkt> F7
Loader replies: ACK F0 7E <src> 7F <pkt> F7, NAK ...7E..., CANCEL ...7D..., WAIT ...7C...
(WAIT keeps the same deadline). send matches the File Dump request 07 03, retries a silent
header three times, and on a header NAK starts the data packets. 4 NAKs of a data packet cancel.

usage:
  eos_midi.py build  (--floppy EOS.img | --bin patched_0x76543210.bin) OUT.syx
  eos_midi.py check  IN.syx [--ref raw.bin]        simulate the loader on a .syx
  eos_midi.py send   IN.syx --port NAME [--port-in NAME]   handshaked transfer (needs mido+python-rtmidi)
  eos_midi.py ports
"""
import argparse, os, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eos_lz  # noqa: E402

DEV = 0x00          # loader's own device ID
SRC = 0x00          # our "sender" ID; loader addresses its ACKs to this
RAM_LIMIT = 0x200000  # loader buffer 0x10200000..0x10400000


def enc7(data):
    out = bytearray()
    for i in range(0, len(data), 7):
        grp = data[i:i + 7]
        msb = 0
        for j, b in enumerate(grp):
            msb |= ((b >> 7) & 1) << (6 - j)
        out.append(msb)
        out += bytes(b & 0x7f for b in grp)
    return bytes(out)


def dec7(enc):  # mirror of loader 0x17ABC
    out, msb = bytearray(), 0
    for i, b in enumerate(enc):
        if i % 8 == 0:
            msb = b
        else:
            msb = (msb << 1) & 0xff
            out.append(b | (msb & 0x80))
    return bytes(out)


def xor7(bs):
    c = 0
    for b in bs:
        c ^= b
    return c & 0x7f


def build_messages(payload, name='EOSLoader'):
    msgs = []
    n = len(payload)
    hdr = bytes([0x7e, DEV, 0x07, 0x01, SRC]) + b'EXE ' + bytes((n >> (7 * k)) & 0x7f for k in range(4)) \
        + name.encode('ascii')
    msgs.append(b'\xf0' + hdr + b'\xf7')
    pkt = 0
    for off in range(0, n, 112):
        e = enc7(payload[off:off + 112])
        body = bytes([0x7e, DEV, 0x07, 0x02, pkt, len(e) - 1]) + e
        msgs.append(b'\xf0' + body + bytes([xor7(body)]) + b'\xf7')
        pkt = (pkt + 1) & 0x7f
    msgs.append(bytes([0xf0, 0x7e, DEV, 0x7b, pkt, 0xf7]))
    return msgs


def split_syx(raw):
    msgs, i = [], 0
    while True:
        s = raw.find(b'\xf0', i)
        if s < 0:
            return msgs
        e = raw.find(b'\xf7', s)
        msgs.append(raw[s:e + 1])
        i = e + 1


def simulate(msgs):
    """Apply the loader's acceptance rules; return the reassembled payload."""
    m = msgs[0]
    assert m[1] == 0x7e and m[2] in (DEV, 0x7f) and m[3:5] == b'\x07\x01', 'bad header'
    t = m[6:10]
    assert t == b'CEXE' or t[:3] == b'EXE', 'type not EXE'
    length = sum((m[10 + k] & 0x7f) << (7 * k) for k in range(4))
    out, expect = bytearray(), 0
    for m in msgs[1:]:
        assert m[0] == 0xf0 and m[-1] == 0xf7 and m[1] == 0x7e and m[2] == DEV
        body = m[3:-1]
        if body[0] == 0x7b:
            assert len(body) == 2
            break
        assert body[:2] == b'\x07\x02', 'not a data packet'
        assert body[2] == expect, f'packet {body[2]} != expected {expect}'
        cnt = body[3] + 1
        assert cnt <= 0x80 and len(body) == cnt + 5
        assert (DEV ^ 0x7e ^ xor7(body[:cnt + 4])) & 0x7f == body[cnt + 4], 'checksum'
        assert all(b < 0x80 for b in m[1:-1]), 'non 7-bit byte'
        out += dec7(body[4:4 + cnt])
        expect = (expect + 1) & 0x7f
    else:
        raise AssertionError('no EOF')
    return length, bytes(out)


def verify_payload(length, payload, ref=None):
    raw = eos_lz.decompress(payload)
    magic, c1, c2, entry, ln = struct.unpack('>5I', raw[:0x14])
    assert magic == 0x76543210, f'decompressed magic {magic:08x}'
    assert eos_lz.csum(raw) == c1 and c1 ^ c2 == 0xffffffff, 'image checksum'
    assert len(raw) <= RAM_LIMIT, 'too large for loader RAM buffer'
    assert len(raw) >= length, 'loader would report Wrong length'
    if ref is not None:
        assert raw == ref, 'differs from reference image'
    return raw, entry, c1


def cmd_build(a):
    if a.floppy:
        img = open(a.floppy, 'rb').read()
        magic, _, _, _, ln = struct.unpack('>5I', img[:0x14])
        assert magic == 0x76543211, 'floppy image not Lz77 (0x76543211)'
        payload = img[0x200:0x200 + ln]
    else:
        raw = open(a.bin, 'rb').read()
        magic, c1, c2, _, ln = struct.unpack('>5I', raw[:0x14])
        assert magic == 0x76543210 and ln == len(raw), 'need full 0x76543210 image (run eos_lz.py fixsum)'
        payload = eos_lz.compress(raw)
    msgs = build_messages(payload)
    data = b''.join(msgs)
    length, back = simulate(split_syx(data))
    raw, entry, c = verify_payload(length, back)
    open(a.out, 'wb').write(data)
    name = raw[0x18:0x30].split(b'\0')[0].decode('latin1').strip()
    print(f'{a.out}: {name!r}, {len(msgs)} messages, {len(data)} bytes, payload {len(payload)} '
          f'-> image {len(raw):#x}, csum {c:08x}; ~{len(data) / 3125 / 60:.1f} min at MIDI speed')


def cmd_check(a):
    msgs = split_syx(open(a.syx, 'rb').read())
    ref = open(a.ref, 'rb').read() if a.ref else None
    length, payload = simulate(msgs)
    raw, entry, c = verify_payload(length, payload, ref)
    print(f'OK: {len(msgs)} messages, image {len(raw):#x} bytes, csum {c:08x}, entry {entry:08x}'
          + (', identical to reference' if ref else ''))


def cmd_ports(_):
    import mido
    print('out:', mido.get_output_names())
    print('in :', mido.get_input_names())


def cmd_send(a):
    import mido
    msgs = split_syx(open(a.syx, 'rb').read())
    simulate(msgs)
    out = mido.open_output(a.port)
    inp = mido.open_input(a.port_in or a.port)

    def pending():
        return [bytes(m.data) for m in inp.iter_pending() if m.type == 'sysex']

    def wait_hs(timeout):
        """ACK 7F, NAK 7E, CANCEL 7D. WAIT 7C keeps the same deadline. Anything else is logged."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            for raw in pending():
                if len(raw) >= 3 and raw[0] == 0x7e and raw[2] in (0x7f, 0x7e, 0x7d, 0x7c):
                    if raw[2] == 0x7c:
                        print(f'  WAIT {raw.hex()}', flush=True)
                        continue
                    return raw[2], raw
                print(f'  note {raw.hex()}', flush=True)
            time.sleep(0.002)
        return None, None

    def tx(raw):
        out.send(mido.Message('sysex', data=list(raw[1:-1])))

    print('Power on holding [Enter], answer Yes to "Download OS from MIDI?" ...', flush=True)
    deadline = time.time() + 300
    req = None
    while req is None and time.time() < deadline:
        for raw in pending():
            # File Dump request is 07 03. A bare 07 also matches our own header, so don't fire on that.
            if len(raw) >= 4 and raw[0] == 0x7e and raw[2:4] == b'\x07\x03':
                req = raw
                break
            print(f'  note {raw.hex()}', flush=True)
        time.sleep(0.002)
    print(f'request received: {req.hex()}' if req else 'no request seen, sending header anyway', flush=True)
    # The loader ACKs a header it accepts. Silence: resend, the header may not have arrived.
    # NAK: it already accepted a header and is waiting for packet 0; a resent header is not a
    # data packet, so stop sending headers and start at packet 0.
    sub = None
    for attempt in range(1, 4):
        tx(msgs[0])
        sub, raw = wait_hs(8)
        if sub == 0x7f:
            print(f'header ACK {raw.hex()}', flush=True)
            break
        if sub == 0x7d:
            sys.exit(f'loader cancelled the header: {raw.hex()}')
        if sub == 0x7e:
            print(f'header NAK {raw.hex()} — loader is waiting for data', flush=True)
            break
        print(f'no header reply, attempt {attempt}', flush=True)
    else:
        sys.exit('header not acknowledged')
    total = len(msgs) - 2
    for i, m in enumerate(msgs[1:-1]):
        for attempt in range(4):
            tx(m)
            sub, raw = wait_hs(2.0)
            if sub == 0x7f:
                break
            if sub == 0x7d:
                sys.exit(f'loader cancelled at packet {i}: {raw.hex()}')
            print(f'packet {i}: {"NAK " + raw.hex() if sub == 0x7e else "timeout"}, resending', flush=True)
        else:
            sys.exit(f'packet {i} failed')
        if i % 200 == 0:
            print(f'{i}/{total}', flush=True)
    tx(msgs[-1])
    print('done - loader should now verify and ask "Burn to flash?"', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest='cmd', required=True)
    b = sp.add_parser('build'); g = b.add_mutually_exclusive_group(required=True)
    g.add_argument('--floppy'); g.add_argument('--bin'); b.add_argument('out')
    c = sp.add_parser('check'); c.add_argument('syx'); c.add_argument('--ref')
    s = sp.add_parser('send'); s.add_argument('syx'); s.add_argument('--port', required=True); s.add_argument('--port-in')
    sp.add_parser('ports')
    a = p.parse_args()
    {'build': cmd_build, 'check': cmd_check, 'send': cmd_send, 'ports': cmd_ports}[a.cmd](a)


if __name__ == '__main__':
    main()
