#!/usr/bin/env python3
"""Send a WAV file to the E4 as an MMA MIDI Sample Dump (SDS); EOS receives these on its own
("MIDI Sample Dump ... Receiving packets ... %d out of %d").

usage: sds_send.py FILE.wav SAMPLE_NUMBER [--port NAME] [--dev N] [--loop START END] [--dry FILE.syx]
  SAMPLE_NUMBER  SDS sample number (14 bits); the E4 stores the sample in that sample location
  --dev          SDS channel = the E4's MIDI device ID (default 1, as eos_remote.py)
  --loop         loop start/end in sample words (default: no loop)
  --dry          write the messages to a .syx file instead of sending

Format (MMA SDS): Dump Header F0 7E cc 01 ss ss ee ff ff ff gg gg gg hh hh hh ii ii ii jj F7
  ss = sample number (LSB first, 7-bit), ee = bits per word, ff = sample period in ns (21 bits),
  gg = length in words, hh / ii = loop start / end (words), jj = loop type (7F = off)
Data packet F0 7E cc 02 kk <120 data bytes> ll F7: kk = packet number mod 128, ll = XOR checksum of
7E cc 02 kk and the data (& 7F). 16-bit words are sent as 3 bytes, left-justified, 7 bits each,
unsigned (offset binary). Handshake: the receiver answers ACK (7F), NAK (7E, resend), WAIT (7C, wait for
the next reply) or CANCEL (7D); with no reply within 2 s of the header the sender goes on open loop, as the
standard allows, sending each packet no faster than the cable (41 ms) plus 20 ms.
The E4 takes an SDS header on any page, with no front-panel action (parser 0x136B64 -> 0x175014; sample
numbers 1..999; checked on hardware 2026-11-06, notes/sysex_load_research.md).
"""
import argparse, sys, time, wave
import numpy as np


def sds_messages(words, rate, num, dev, loop=None, bits=16):
    """words: int16 numpy array (mono). Returns (header, [packets])."""
    n = len(words)
    period = int(round(1e9 / rate))
    ls, le, lt = (loop[0], loop[1], 0x00) if loop else (0, 0, 0x7F)

    def b7(v, k):
        return [(v >> (7 * i)) & 0x7F for i in range(k)]
    hdr = bytes([0xF0, 0x7E, dev & 0x7F, 0x01] + b7(num, 2) + [bits] + b7(period, 3) + b7(n, 3) + b7(ls, 3)
                + b7(le, 3) + [lt, 0xF7])
    u = (words.astype(np.int32) + 32768).astype(np.uint32)       # offset binary
    data = np.empty(n * 3, np.uint8)
    data[0::3] = (u >> 9) & 0x7F                                  # 16 bits left-justified in 21
    data[1::3] = (u >> 2) & 0x7F
    data[2::3] = (u << 5) & 0x60
    pkts = []
    for i in range(0, len(data), 120):
        chunk = list(data[i:i + 120]) + [0] * max(0, 120 - len(data[i:i + 120]))
        k = (i // 120) & 0x7F
        body = [0x7E, dev & 0x7F, 0x02, k] + chunk
        cs = 0
        for v in body:
            cs ^= v
        pkts.append(bytes([0xF0] + body + [cs & 0x7F, 0xF7]))
    return hdr, pkts


def read_wav(path):
    w = wave.open(path, 'rb')
    if w.getsampwidth() != 2:
        raise SystemExit('16-bit WAV only')
    x = np.frombuffer(w.readframes(w.getnframes()), '<i2')
    if w.getnchannels() > 1:
        x = x.reshape(-1, w.getnchannels())[:, 0]
    return x, w.getframerate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wav'); ap.add_argument('num', type=int)
    ap.add_argument('--port', default='828mk3 Hybrid MIDI Port'); ap.add_argument('--dev', type=int, default=1)
    ap.add_argument('--loop', type=int, nargs=2); ap.add_argument('--dry')
    a = ap.parse_args()
    words, rate = read_wav(a.wav)
    hdr, pkts = sds_messages(words, rate, a.num, a.dev, a.loop)
    print(f'{a.wav}: {len(words)} words at {rate} Hz -> sample {a.num}, {len(pkts)} packets '
          f'(~{(len(hdr) + sum(map(len, pkts))) / 3125 / 60:.1f} min at MIDI speed)', flush=True)
    if a.dry:
        open(a.dry, 'wb').write(hdr + b''.join(pkts))
        return
    import mido
    out, inp = mido.open_output(a.port), mido.open_input(a.port)
    for _ in inp.iter_pending():
        pass

    def reply(timeout):
        t = time.time() + timeout
        while time.time() < t:
            for m in inp.iter_pending():
                if m.type == 'sysex' and len(m.data) >= 4 and m.data[0] == 0x7E and m.data[2] in (0x7F, 0x7E, 0x7C, 0x7D):
                    return m.data[2]
            time.sleep(0.001)
        return None

    def send(msg):
        out.send(mido.Message('sysex', data=list(msg[1:-1])))
    send(hdr)
    r = reply(2.0)
    if r == 0x7D:
        raise SystemExit('E4 cancelled the dump at the header')
    mode = 'handshake' if r == 0x7F else 'open loop'
    print(f'header: {"ACK" if r == 0x7F else "no reply"} -> {mode}', flush=True)
    i, naks, t0 = 0, 0, time.time()
    wire = 127 * 10 / 31250                                # seconds a 127-byte packet takes on the cable
    while i < len(pkts):
        ts = time.time()
        send(pkts[i])
        r = reply(wire + 0.02 if mode == 'open loop' else 0.5)
        if r is None:                                      # never outrun the cable (CoreMIDI queues silently)
            time.sleep(max(0.0, ts + wire + 0.02 - time.time()))
        while r == 0x7C:                                   # WAIT
            r = reply(5.0)
        if r == 0x7D:
            raise SystemExit(f'E4 cancelled at packet {i}')
        if r == 0x7E:
            naks += 1
            if naks > 20:
                raise SystemExit(f'too many NAKs (packet {i})')
            continue
        i += 1
        if i % 500 == 0 or i == len(pkts):
            print(f'{i}/{len(pkts)} packets, {time.time() - t0:.0f} s, {naks} NAKs', flush=True)
    print('done', flush=True)


if __name__ == '__main__':
    main()
