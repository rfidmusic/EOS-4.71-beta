#!/usr/bin/env python3
"""Lfo1Ck / Lfo2Ck on EOS 4.71-beta2 build 3.

usage: build_lfock.py BETA1.bin OUT.bin     (BETA1 = build/eos471_beta.bin)

Builds build 3, then places patches/lfock. cord=False (used by the emulator tests)
is build 3 unchanged: name "EOS 4.71-beta2 build 3", checksum 08859e24.

Build 3's tracked holes are 41 bytes and the port-map tail is the restored E-mu
low-pass, so the cord cannot go there. RFX Chorus and RFX UltraChorus share 992
identical bytes. UltraChorus reaches its copy through four PC-relative stubs.
Pointing those stubs at Chorus's copy frees the 988 bytes at 0x1D8C1C (the rts
at 0x1D8C18 stays; it ends a live function). The cord, id_swap and rev_id go
there. The list walkers bsr.w to jmp trampolines in the 20 NOPs at 0x66B24.
"""
import os, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_fuzzob  # noqa: E402
import eos_lz        # noqa: E402

ROOT = os.path.dirname(HERE)
LFK = os.path.join(ROOT, 'patches', 'lfock')
BIN = '/opt/homebrew/bin/'
BASE = 0x20000
RELEASE = b'EOS 4.71-beta2 build 3'
CORD_NAME = b'EOS 4.71-beta2 b3+LfoCk'

# UltraChorus stubs: movea.l #imm followed by lea pc@(imm). The same delta reaches
# Chorus's identical table (0x1D5DFC) and its "%d-%d msec" string.
DELTA = 0x1D5DFC - 0x1D8C1C
STUBS = ((0x1D7730, 0x227C, 0x18B4), (0x1D7AE2, 0x207C, 0x1132),
         (0x1D7B8C, 0x207C, 0x1088), (0x1D8B16, 0x207C, 0x00FE))
HOLE = (0x1D8C1C, 0x1D8FF8)          # table through the shared string; 988 bytes
CHORUS_TABLE = 0x1D5DFC
KEEP_RTS = 0x1D8C18                  # live rts immediately before the hole

LFO_HOOK, LFO_HOOK_STOCK = 0x61BF4, bytes.fromhex('4ef900020400')
LFO_OPEN, LFO_OPEN_STOCK = 0xCDAC2, bytes.fromhex('23c71000415cdc87')
LFO_BUILT, LFO_BUILT_STOCK = 0xCDB8C, bytes.fromhex('298d6c004fef0014')
LFO_BIND, LFO_BIND_STOCK = 0x5F7E0, bytes.fromhex('28fc00000001')
LFO_FMT = 0x68BF0
RATE_SET_STOCK = 0x69F80
UI_RATE = (0x6B5B0, 0x6B65A)
LFOCK_NAME_AT = 0x201AE
LFOCK_DESTS = ((98, 0x1A4, b'Lfo1Ck'), (107, 0x1A6, b'Lfo2Ck'))
DEST_TABLE = 0x6344C
ID_FWD = (0x62D22, 0x62D86)
ID_RET = (0x62D48, 0x62DAC)
ID_REV = 0x62CA0
TRAMP = (0x66B24, 0x66B2A)           # jmp id_swap, jmp rev_id; stub at 0x66B38 stays


def cord_label():
    """Startup name. Fixed so a patch can lock one checksum. 23 bytes, field holds 24."""
    if len(CORD_NAME) > 24:
        raise SystemExit('name too long')
    return CORD_NAME


def bsr_w(at, target):
    disp = target - (at + 2)
    if not -32768 <= disp <= 32767:
        raise SystemExit(f'bsr at {at:#x} cannot reach {target:#x}')
    return b'\x61\x00' + struct.pack('>h', disp)


def build(base, out, cord=True):
    build_fuzzob.build(base, out, RELEASE)
    if not cord:
        return None
    img = bytearray(open(out, 'rb').read())
    if len(img) != 0x1DFE80:
        raise SystemExit(f'image length {len(img):#x}')
    shared = HOLE[1] - HOLE[0]
    if img[HOLE[0] - BASE:HOLE[1] - BASE] != img[CHORUS_TABLE - BASE:CHORUS_TABLE + shared - BASE]:
        raise SystemExit('UltraChorus table is not Chorus\'s copy')
    if img[KEEP_RTS - BASE:KEEP_RTS - BASE + 2] != b'\x4e\x75':
        raise SystemExit('the rts before the hole moved')
    for at, op, imm in STUBS:
        if img[at - BASE:at - BASE + 6] != struct.pack('>HI', op, imm):
            raise SystemExit(f'stub at {at:#x} is not movea.l #{imm:#x}')
        if img[at + 6 - BASE:at + 8 - BASE] != b'\x41\xfb' and img[at + 6 - BASE:at + 8 - BASE] != b'\x43\xfb':
            raise SystemExit(f'stub at {at:#x} is not followed by lea pc@')
        struct.pack_into('>i', img, at + 2 - BASE, imm + DELTA)
    for a, stock, n in ((LFO_HOOK, LFO_HOOK_STOCK, 6), (LFO_OPEN, LFO_OPEN_STOCK, 8),
                        (LFO_BUILT, LFO_BUILT_STOCK, 8), (LFO_BIND, LFO_BIND_STOCK, 6)):
        if img[a - BASE:a - BASE + n] != stock:
            raise SystemExit(f'hook site {a:#x} is not stock')
    if img[TRAMP[0] - BASE:TRAMP[0] - BASE + 20] != b'\x4e\x71' * 10:
        raise SystemExit('0x66B24 is not the 20-byte NOP run')
    if img[0x66B38 - BASE:0x66B38 - BASE + 4] != bytes.fromhex('70404e75'):
        raise SystemExit('moveq #$40 stub moved')
    names = b''.join(n + b'\0' for _, _, n in LFOCK_DESTS)
    if img[LFOCK_NAME_AT - BASE:LFOCK_NAME_AT - BASE + len(names)] != bytes(len(names)):
        raise SystemExit('header pad for Lfo1Ck/Lfo2Ck is not clear')
    for code, _, _ in LFOCK_DESTS:
        off = struct.unpack_from('>H', img, DEST_TABLE + 8 * code + 4 - BASE)[0]
        if off != 0x1E:
            raise SystemExit(f'destination {code} is in use')
    for addr in ID_FWD:
        if img[addr - BASE:addr - BASE + 4] != bytes.fromhex('2c072a49'):
            raise SystemExit(f'{addr:#x} is not the stock id copy')
    for addr in ID_RET:
        if img[addr - BASE:addr - BASE + 2] != bytes.fromhex('2007'):
            raise SystemExit(f'{addr:#x} is not move.l d7,d0')
    if img[ID_REV - BASE:ID_REV - BASE + 4] != bytes.fromhex('122f0017'):
        raise SystemExit('reverse walker id load is not the stock move.b')
    for a in UI_RATE:
        fmt, get, setter = struct.unpack_from('>III', img, a + 0x16 - BASE)
        if (fmt, get, setter) != (LFO_FMT, 0, RATE_SET_STOCK):
            raise SystemExit(f'Rate descriptor {a:#x} not stock')

    with tempfile.TemporaryDirectory() as td:
        for src in ('lfock.s', 'list_order.s'):
            subprocess.run([BIN + 'm68k-elf-as', '-mcpu=5206e', '-o', src.replace('.s', '.o'),
                            os.path.join(LFK, src)], check=True, cwd=td)
        ld = (f'SECTIONS {{\n  .lfk 0x{HOLE[0]:X} : {{ lfock.o(.lfk) }}\n'
              '  .idsw : { list_order.o(.idsw) }\n  .revid : { list_order.o(.revid) }\n}\n')
        open(os.path.join(td, 'lfock.ld'), 'w').write(ld)
        subprocess.run([BIN + 'm68k-elf-ld', '-T', 'lfock.ld', '-o', 'lfock.elf', 'lfock.o', 'list_order.o'],
                       check=True, cwd=td)
        elf = os.path.join(td, 'lfock.elf')
        syms = {}
        for line in subprocess.run([BIN + 'm68k-elf-nm', elf],
                                   check=True, capture_output=True, text=True).stdout.splitlines():
            addr, kind, name = line.split()
            if kind in 'tTdD':
                syms[name] = int(addr, 16)
        sec_at = {}
        for line in subprocess.run([BIN + 'm68k-elf-objdump', '-h', elf],
                                   check=True, capture_output=True, text=True).stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1] in ('.lfk', '.idsw', '.revid'):
                sec_at[parts[1]] = (int(parts[3], 16), int(parts[2], 16))
        for sec, anchor in (('.lfk', 'cord_tick'), ('.idsw', 'id_swap'), ('.revid', 'rev_id')):
            if sec not in sec_at:
                raise SystemExit(f'{sec} missing from the link')
            at, size = sec_at[sec]
            if syms[anchor] < at or syms[anchor] >= at + size:
                raise SystemExit(f'{anchor} is not in {sec}')
            if at < HOLE[0] or at + size > HOLE[1]:
                raise SystemExit(f'{sec} {at:#x}+{size} outside the hole')
            subprocess.run([BIN + 'm68k-elf-objcopy', '-O', 'binary', '-j', sec, elf,
                            os.path.join(td, 'sec.bin')], check=True)
            code = open(os.path.join(td, 'sec.bin'), 'rb').read()
            if len(code) != size:
                raise SystemExit(f'{sec} objcopy {len(code)} != header {size}')
            img[at - BASE:at - BASE + len(code)] = code
            print(f'{sec}: {len(code)} bytes at {at:#x}')
    if img[KEEP_RTS - BASE:KEEP_RTS - BASE + 2] != b'\x4e\x75':
        raise SystemExit('placement overwrote the live rts')

    img[TRAMP[0] - BASE:TRAMP[0] - BASE + 6] = b'\x4e\xf9' + struct.pack('>I', syms['id_swap'])
    img[TRAMP[1] - BASE:TRAMP[1] - BASE + 6] = b'\x4e\xf9' + struct.pack('>I', syms['rev_id'])
    for addr in ID_FWD:
        img[addr - BASE:addr - BASE + 4] = bsr_w(addr, TRAMP[0])
    for addr in ID_RET:
        img[addr - BASE:addr - BASE + 2] = bytes.fromhex('2006')
    img[ID_REV - BASE:ID_REV - BASE + 4] = bsr_w(ID_REV, TRAMP[1])
    img[LFO_HOOK - BASE:LFO_HOOK - BASE + 6] = b'\x4e\xf9' + struct.pack('>I', syms['cord_tick'])
    img[LFO_OPEN - BASE:LFO_OPEN - BASE + 8] = b'\x4e\xb9' + struct.pack('>I', syms['rate_enter']) + b'\x4e\x71'
    img[LFO_BUILT - BASE:LFO_BUILT - BASE + 8] = b'\x4e\xb9' + struct.pack('>I', syms['rate_built']) + b'\x4e\x71'
    img[LFO_BIND - BASE:LFO_BIND - BASE + 6] = b'\x4e\xb9' + struct.pack('>I', syms['lfo_bind'])
    img[LFOCK_NAME_AT - BASE:LFOCK_NAME_AT - BASE + len(names)] = names
    for code, voff, name in LFOCK_DESTS:
        ptr = LFOCK_NAME_AT + names.find(name + b'\0')
        struct.pack_into('>IHH', img, DEST_TABLE + 8 * code - BASE, ptr, voff, 0x200)
    for a in UI_RATE:
        struct.pack_into('>I', img, a + 0x1E - BASE, syms['rate_set'])

    header = cord_label()
    if len(header) > 24:
        raise SystemExit('name too long')
    img[0x18:0x30] = header.ljust(24, b' ')
    struct.pack_into('>II', img, 4, 0, 0xffffffff)
    c = eos_lz.csum(img)
    struct.pack_into('>II', img, 4, c, c ^ 0xffffffff)
    open(out, 'wb').write(img)
    print(f'lfock: cord_tick {syms["cord_tick"]:#x}; id_swap {syms["id_swap"]:#x}; '
          f'rev_id {syms["rev_id"]:#x}; rate_set {syms["rate_set"]:#x}')
    print(f'{out}: checksum {c:08x}; name {header.decode()!r}')
    return syms, None


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])
