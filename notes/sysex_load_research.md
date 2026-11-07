# Loading a test sample + preset into the E4 over MIDI only (EOS 4.71-beta2 b4)

Static research on `build/eos471_beta2_b4.bin` (load 0x20000). Nothing sent to hardware. Addresses are code
addresses in that image. Decompiles via REA/Ghidra 12.1.4 raw-binary import; key ones re-checked in objdump.

## Summary

| # | Question | Answer | Confidence |
|---|---|---|---|
| 1 | Sample in, no panel | **Possible.** MMA SDS is received at any time, from any page. The "open Sample Dump -> Receive first" note in `tools/sds_send.py` is not supported by the code. | high (code), needs 1 hardware run |
| 2 | Preset in, no disk | **Possible.** E-mu editor preset dump `55 0D` (closed loop) or `55 0F` (no handshake) creates preset N itself. Exact 3 messages below. Edit-command path also exists once the preset exists. | medium-high |
| 3 | Routing ids | Voice submix = id 69 (0..7). Preset FX A/B = ids 6-21. Master FX = 228-245. Channel submix = 250. No table id routes into RFX. | ids high; value meanings of 69 above 0 low |
| 4 | Persistence / acks | RAM only, nothing else needed. SDS: WAIT then ACK/NAK/CANCEL. Dump: WAIT then ACK/NAK/CANCEL. Param edits: no ack; read back with `55 02`. | high |

## 0. How SysEx reaches the handlers

- MIDI SysEx parser 0x136B64 (`a5` = bytes after F0):
  - byte0 0x7E -> 0x136BE0: sub-id 06 -> identity (0x136E8C).
  - Sub-id 02 (SDS data) goes to the SDS handler 0x17539C only while a receive is open (0x1747C8 = flag 0x10006727).
  - Every other 7E sub-id (01 header, 03 request, 7C-7F handshake) goes to 0x17539C unconditionally.
  - **No UI-page check and no channel check.**
  - byte0 0x18 -> 0x136C16. `F0 18 7F ...` goes to 0x348E8 (remote family). Otherwise byte2 must be 0x7F or the
    device ID (0x10004F23), and byte1 must be the product byte (0x10004F38). byte3 0x55 is queued by 0x533F0 (key
    0x55) and run by dispatcher 0x5870C.
- Dispatcher 0x5870C gets a pointer to the 0x55 byte: +1 = command, +2... = payload.
- The 0x55 path is the one already confirmed live (`tools/eos_remote.py`). SDS goes through the same parser function.

## 1. Sample in: MMA SDS, always listening

**Header** `F0 7E cc 01 ss ss ee pp pp pp ll ll ll aa aa aa bb bb bb tt F7` -> 0x175014:
- Sends WAIT `F0 7E 00 7C kk F7`, then checks sample number < 1000 and free memory (0x13E3B8 minus 0x400,
  plus the old sample's size if the slot is in use).
- Fail: CANCEL `F0 7E 00 7D kk F7`.
- OK:
  - deletes the existing sample at that number (0x13DA58(n,3));
  - allocates the sample (0x13E81C);
  - computes the pitch word from the period (44053 Hz reference, as e4b_format §6.4);
  - sets loop start/end from aa/bb (words);
  - loop on unless tt = 7F; tt+1 goes to flag bits 6-7 of +0x3A;
  - opens the receive (0x10006727 = 1);
  - sends ACK `F0 7E 00 7F 00 F7`.
- ee < 15 -> 2 bytes per word; 15..21 -> 3; > 21 -> 4. Words per packet = 120 / that (40 for 16-bit).

**Data packet** `F0 7E cc 02 kk <120 bytes> xx F7` -> 0x174ECC:
- Sends WAIT, decodes 40 words, writes them to sample RAM.
- Word decode 0x174E60: `(b0<<9 | b1<<2 | b2>>5) - 0x8000`, i.e. left-justified offset binary, as `sds_send.py` writes.
- Checksum = XOR of `7E cc 02 kk` + data. OK -> ACK `F0 7E 00 7F kk F7`. Bad -> NAK `F0 7E 00 7E kk F7`.
- kk in the E4's reply is its own counter (0x10006728, +1 per ACK). The host's kk is not checked.
- After the last word it finalises the sample: 0x13E82C, 0x1749AC, 0x13D614, 0x13D8C4.
- CANCEL from the host (7D) -> 0x174864 aborts.

Facts for the host:
- **Channel:** cc is ignored on receive. Replies always carry channel 00. The reply template at RAM 0x1000671C is
  `F0 7E 00 .. .. F7`, and no code writes its channel byte.
- **Sample number:** the SDS sample number is used directly as the E4 sample number (must be < 1000; use 1..999).
- **Example:** sample 100, 16-bit, 48 kHz, 4800 frames, forward loop 100..4700. The header is:
  `F0 7E 01 01 64 00 10 61 22 01 40 25 00 64 00 00 5C 24 00 00 F7`
  It is followed by 120 data packets. `tools/sds_send.py sine.wav 100 --loop 100 4700` builds exactly this.
  - Wait for the ACK after the header.
  - If you get WAIT, keep waiting for the next reply.
- **Docstring conflict:** `tools/sds_send.py` says both "EOS receives these on its own" (top line) and "receives only
  from its Sample Dump page" (line 19). The code supports the first statement.
- **Loop window:** the disk loader moves loops that start under 6 frames. Not checked for SDS, so keep loops >= 6
  frames from start and end.

Not needed, but present:
- Remote front-panel family `F0 18 7F ...` (0x348E8 -> queue key 0x7F -> 0x35480) handles button/wheel/LCD
  remote. No need to drive the Sample Dump page.
- The 0x55 family has no sample-data upload. It only has sample name get/set (0x09-0x0C) and delete sample
  (`55 50 s s`, 0x5646C).

## 2. Preset in: editor preset dump (creates the preset)

### 2.1 Commands (0x5870C)

| cmd | payload | handler | does |
|---|---|---|---|
| 0D 01 | pkt, 4-byte length (7-bit LSB first) | 0x57870 | dump header, closed loop. Replies WAIT then ACK pkt |
| 0D 02 | pkt, 256 data bytes, checksum | 0x57870 -> 0x55588 / 0x547A4 / 0x5439C / 0x54544 | data packet, closed loop. WAIT, then ACK / NAK |
| 0F 01, 0F 02 | same | 0x57870(...,1) | same format, **no replies** (open loop) |
| 0D 03 / 0D 04 / 0D 05 | other variants (14-bit packet number) | 0x57414 / 0x577DC | not needed |
| 0E | preset lo hi | 0x554E8 | E4 sends preset as `0D` dump. The host must ACK each packet with `55 7F pp` |
| 7F / 7E / 7D / 7C | pp | | host ACK / NAK / CANCEL / WAIT, used when the E4 is sending |

E4 replies (dd = E4 device ID):
- WAIT `F0 18 21 dd 55 7C F7`
- ACK `F0 18 21 dd 55 7F pp F7`
- NAK `F0 18 21 dd 55 7E pp F7`
- CANCEL `F0 18 21 dd 55 7D F7`

### 2.2 Packet format

Format taken from the receiver and cross-checked against the E4's own sender 0x54AD0 / 0x552E0 / 0x55094 /
0x54C50 / 0x54E58.

- **Data packet:** `F0 18 21 dd 55 0D 02 pp <exactly 256 data bytes> cs F7`. The last packet may be shorter.
- **Checksum:** cs = (~sum of data bytes) & 0x7F. Checked by 0x542B0.
- **Data stream:**
  - It is a list of 14-bit values (lo, hi; values >= 0x2000 are negative).
  - Each value is applied through the normal parameter setter 0x53DC0, so it is clamped to the parameter's min/max.
  - Non-final packets must be exactly 256 bytes. The parser only stops at offset 0x104.

| order | content |
|---|---|
| 1 | preset number (0..999). 0x55588 calls 0x13C52C -> 0x13C328, which creates "Untitled Preset" with 1 default voice and 1 zone. Then the editor preset (0x1000134A) is set to it. |
| 2 | name, 16 raw ASCII bytes |
| 3 | 22 values, param ids 0..21 (preset header, FX) |
| 4 | link count L, then per link the values of ids 23..35 (13 each) |
| 5 | voice count V (0x51674 adds V-1 voices), then per voice: |
| 5a | the values of ids 37..182 (146 values) |
| 5b | zone count Z. If Z = 1, no zone values follow. Id 38, 39, 40, 42, 44 at voice level go to zone 0. If Z > 1, Z × (ids 38,39,40,42,44,45..52 = 13 values) |

The header length field is stored (0x1000135C) but not used for parsing.

### 2.3 Ready-made messages

Preset 4, 1 voice, 1 zone, sample 100, keys 0-127, original key 72. All other values are the table defaults
(entry +6, clamped to min/max). Device ID 1. Generated by
`/private/tmp/claude-501/-Users-tony-OpenWork-Chat-EOS/920c8256-0010-4820-9106-ce130db2fbe5/scratchpad/gen.py`.

Bytes to change for other values:
- **Preset:** packet 1 data bytes 0-1.
- **Sample:** id 38 = packet 1 data bytes 68-69 (here `64 00`).
- **Original key:** id 44 (here `48 00`).
- **Checksum:** recompute after any change.

1. Header: `F0 18 21 01 55 0D 01 00 68 02 00 00 F7` -> expect WAIT, then ACK 00.
2. Data 1 (266 bytes) -> expect WAIT, then ACK 01:
   `F0 18 21 01 55 0D 02 01 04 00 53 59 53 45 58 20 54 45 53 54 20 53 49 4E 45 20 00 00 00 00 7F 7F 7F 7F 7F 7F 7F 7F 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 01 00 64 00 00 00 00 00 00 00 00 00 00 00 48 00 00 00 00 00 7F 00 00 00 00 00 00 00 7F 00 00 00 00 00 00 00 7F 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 64 00 00 00 64 00 00 00 64 00 14 00 00 00 00 00 00 00 00 00 7F 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 64 00 00 00 64 00 00 00 64 00 14 00 00 00 00 00 00 00 40 00 00 00 00 00 00 00 00 00 40 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 64 00 00 00 64 00 00 00 64 00 14 00 00 00 00 00 00 00 00 00 00 00 00 00 2D F7`
3. Data 2 (114 bytes) -> expect WAIT, then ACK 02:
   `F0 18 21 01 55 0D 02 02 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 01 00 7E F7`

Voice values used:
- Amp env: Atk2 / Dcy1 / Dcy2 levels 100 %, Rls1 rate 20, so the voice sustains.
- Filter: type index 0, freq 255, Q 0.
- No cords (the factory Vel->AmpVol cords are left out). Volume 0 dB, pan 0, submix 0, group 1.
- Initial controllers -1. FX A/B algorithm 0 = use master.

### 2.4 Edit-command path (preset must already exist)

Edit message: `F0 18 21 dd 55 01 <2k> (<id lo> <id hi> <val lo> <val hi>)×k 7F F7`. Handler 0x53F8C; the 7F is a
pad.

**Editor selection globals** (setters 0x53B40..0x53BFC; selection resolved by 0x5908C):

| id | sets | effect |
|---|---|---|
| 223 | preset | 0x1000134A. Also resets voice to 0 and link/zone/group to -1. |
| 225 | voice | 0x1000131A |
| 226 | zone | 0x1000131E |
| 224 | link | 0x10001314 |
| 227 | group | 0x10001320 |

- They are separate from the front-panel selection. Always send 223 first.
- With zone = -1, the zone ids (38, 44) write zone 0 of the selected voice (setters 0x595D0 / 0x594B4).

**Ids:**

| id | field | range | where |
|---|---|---|---|
| 38 | sample number (negative = ROM sample) | 0..999 (min −8 with ROM) | zone +0x08 (setter 0x595D0) |
| 44 | original key | 0..127, default 72 | zone +0x0C (0x594B4) |
| 45 / 46 / 47 / 48 | key low / low fade / high / high fade | 0..127 | voice +0x0C..0x0F |
| 49-52 | velocity low / low fade / high / high fade | 0..127 | |
| 37 | group | 1..32 | |

**Example:** preset 4, sample 100, original key 72:
- `F0 18 21 01 55 01 02 5F 01 04 00 7F F7` (id 223 = 4)
- `F0 18 21 01 55 01 02 26 00 64 00 7F F7` (id 38 = 100)
- `F0 18 21 01 55 01 02 2C 00 48 00 7F F7` (id 44 = 72)

**Structure commands:**
- `20 p p`: add voice (0x515F8)
- `21 p p v v`: delete voice
- `22 sp sp sv sv dp dp grp`: copy voice; creates dp if missing (0x52CFC)
- `30 p p v v`: add zone
- `32`: delete zone
- `70 src src dst dst`: copy preset (0x13BF1C); NAK 0 on failure
- `71 p p`: select preset (0x13B468)

**Destructive commands. Do not send:**
- `74`, `75` erase or new preset bank (0x192820 / 0x13C52C(0))
- `76` clears every sample slot (0x13E76C)
- `52` compacts sample memory (0x13E188)
- `50` deletes a sample

### 2.5 Read-back

| send | E4 replies | checks |
|---|---|---|
| `55 06 p p` | `55 05 p p <16-char name>` | preset exists |
| `55 16 p p` | `55 17 n n` | voice count |
| `55 1C p p v v` | `55 1D` | zone count |
| `55 0A s s` | `55 09 s s <name>` | sample present ("Empty Sample" if not) |
| `55 02 01 id id` | `55 01 02 id id val val 7F` | parameter value |
| `55 10` | `55 11` | memory in KB |

## 3. Routing parameter ids (table 0x63E58; min/max from the descriptor)

| id | name | min..max | level |
|---|---|---|---|
| 69 | voice submix | 0..7 | voice +0x36. 0 = Main (default). Meaning of 1..7 not decoded. Strings at 0xBE8B4 suggest Main/Aux1-3 vs Send0-3 naming. |
| 39 / 40 | voice volume dB / pan | −96..10 / −64..63 | zone 0 if no zone selected |
| 68 | amp env depth | 0..16 | voice +0x37 |
| 130+3c | cord destination | 0..255 | dests include SndMain / SndAux1-3 (strings 0x63CE7) |
| 1 | preset volume | −96..10 | preset |
| 6 | preset FX A algorithm (0 = master) | 0..44 | preset +0x3A |
| 7-9 | FX A params | 0..90, 0..127, 0..127 | |
| 10-13 | FX A send from Main / Sub1 / Sub2 / Sub3 | 0..100 | |
| 14 | preset FX B algorithm (0 = master) | 0..32 | |
| 15-17 / 18-21 | FX B params / sends | 0..127 / 0..100 | |
| 228 | master FX A algorithm | 1..44 (def 14) | global |
| 229-231 | Decay Time, HF Damping, FxB==>FxA | 0..90, 0..127, 0..127 | |
| 232-235 | Main / Sub1 / Sub2 / Sub3 FX A Send | 0..100 (def 10/20/30/40) | |
| 236 | master FX B algorithm | 1..32 | |
| 237-239 | Feedback, LFO Rate, Delay Time | 0..127 | |
| 240-243 | Main / Sub1 / Sub2 / Sub3 FX B Send | 0..100 (def 10/15/30/0) | |
| 244 | Effects Engine | 0..1 | When 1, master-FX edits 228..243 skip the refresh (0x53DC0). Meaning of 0/1 unconfirmed. |
| 245 | Multimode Effects Control | −1..15 | |
| 246 | multisetup current channel (1-based) | 1..? | .data max is 0, set at runtime? |
| 247 | channel preset | −1..999 | 0x13857C. Alternative to Program Change. |
| 248 / 249 | channel volume / pan | 0..127 / −64..63 | |
| 250 | channel submix (byte at 0x1030AD26 + ch×0x80) | −1..? | −1 = use voice routing? |
| 186 / 187 / 189 / 270 | Output Boost, Output Format, AES Boost, Output Dither | 0..1, 1..2, 0..1, 0..1 | globals |

**RFX-32:**
- RFX bus routing ("Off / Main / GFX1 / GFX2 / Bus1..", strings 0x5E348 / 0x152EF8) and the preset "RFX Setup /
  TwoFX (legacy) mode" fields (0x6C21F) are not in the SysEx table.
- To reach RFX, a host can only pick the voice submix (69) / channel submix (250) / FX sends. The RFX setup itself
  must already route those buses. Unknown which submix value feeds RFX.

## 4. Persistence and acks

- **RAM only.**
  - SDS finalises the sample itself.
  - The dump leaves preset N in RAM.
  - Nothing to save; both are lost at power-off.
- **Playing preset 4:**
  - Program Change 4 on the E4's channel (Rcv Program Change, id 220, default 1), or
  - ids 246 = channel, 247 = 4. The id 246 clamp is suspect; prefer Program Change.
- **Acks to wait on:**
  - **SDS:** WAIT `7C`, then ACK `7F` / NAK `7E` / CANCEL `7D`, all as `F0 7E 00 xx kk F7`.
  - **Preset dump (0D):** WAIT `55 7C`, then ACK `55 7F pp` / NAK `55 7E pp` / CANCEL `55 7D`.
  - **0F variant:** silent.
  - **Param edits:** no reply.
  - **`55 70`:** replies NAK 0 only on failure.

## 5. Hardware checks still needed

1. SDS with no page open:
   - header ACK arrives;
   - sample 100 appears (`55 0A 64 00`);
   - loop plays;
   - reply channel byte is 00.
2. Dump to an **empty** preset slot: ACK 00/01/02, then `55 06 04 00` returns the name and `55 16` returns 1.
3. Dump over an **existing** preset: 0x13C328 re-allocates the slot. Not proven that it frees or replaces the old
   one cleanly. Try once and check memory (`55 10`).
4. Clamping of RAM descriptors:
   - Id 38's min/max live in RAM (0x10001E70 / 0x10001E74).
   - The getter 0x594FC sets both to −1 while a multi-zone voice is selected, which would clamp a later set to −1.
   - Read back id 38 after loading. If it is wrong, `55 02` it once (refreshes the limits), then set it again.
5. Which submix value (69) reaches the RFX-32 when fitted, and what 244 = 0/1 means.
6. Id 246 max (channel select) at runtime.
