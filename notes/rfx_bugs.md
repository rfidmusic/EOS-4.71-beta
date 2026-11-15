# RFX-32 user reports vs EOS 4.70 code (researched 2026-11-05)

Source: the emusonacid thread "RFX EMU - keep it in one post" (281 posts, Sep 2002 – Aug 2004). Read: pages 4–9
(https://madlabz.info/emusonacid/viewtopic-p=3503.php.html#p3503 is page 7). Not read: pages 1–3 and 10–19.
Code: Ghidra decompiles of the voice start path (0x5F4A8, 0x5F67C, 0x60334, 0x60D80, 0x609D8, 0x1948F4, 0x194B34,
0x194C6C) plus notes/rfx_mix.md. Nothing here has been tested on hardware.

## What users reported

| # | Bug | Key reports | Versions / units |
|---|---|---|---|
| 1 | **Random / stuck pan.** A voice plays at the pan an earlier note on that channel had. Mono after stereo (or after chorus, which uses two channels) is the classic trigger; any pan change can trigger it. | razmo p2173/p2176/p3503/p3615: pan a mono preset hard left, play 64 notes (128 on a 128-voice unit), centre it, play: clicks on the old side. bendjo p3617: the attack comes out at about −48 dB on the old side, then the pan "sticks". ChanVol bars jump. | 4.61 and 4.7; E4XT Ultra, E6400 Ultra, E4 Platinum, E5000 |
| 2 | **Outbursts / noise bursts** on buses 4–7 and GFX1/2, even when nothing is routed there | greenman p2225, WALLY p3506, Silverman2 p3508, illinformed p3667: Multimode Submix → Bus 7 bursts; routing from the RFX Mixer screen or a voice send stops it; worse at full polyphony and with the RFX compressor | mostly 4.7 |
| 3 | Dropouts, static, shrill noise until power-off | aeser p2485 (pre-2001 E4XT Ultra + 8-out expander); several PSU-related reports | hardware/PSU |
| 4 | RFX setup does not remember bus effect type and mix | razmo p3615 | 4.7 |
| 5 | LCD dark, LEDs solid with the RFX fitted | Diginerd p2886 | PSU |

**E-mu replies:**
- Terry Grame (Sept 2002, quoted p3586) said they understood the problem.
- An E-mu developer (p2398) called the pan bug a "channel reallocation" problem: a timing or race condition that "APPEARS to be dependent on which DRAM".
- Tech support (p3343, p4157) only collected reports.

**Workarounds that worked:**
- Stereo-only or mono-only banks.
- Converting mono samples to stereo.
- Routing problem presets to mono effects (WALLY p3492).
- Multi using a saved RFX setup through the MIXER/VOICE/MAIN route instead of direct Bus 6/7/GFX (WALLY p4058).
- Aux send 1 → Main "stopped most bounce but cut attacks" (p3586).

## What the code shows (bug 1)

1. **EOS writes the new sends before the voice starts.** The steps run in this order:
   - Note-on `0x5F4A8` allocates the channel's voice struct and sets +0x1A (1 mono, 2/4 stereo main, 8 partner).
   - It then calls `0x5F67C`, which calls `0x60334`. That stages the sends and invalidates the block's caches (`0x10E228`: pan cache 0xFF7F, level caches 0xFFFF).
   - It queues the voice with `0x194848`.
   - The start pass `0x1948F4` first calls every queued voice's start callback. That runs `0x614A4` → `0x60D80` → `0x609D8` → `0x60674` → `0x10E280`, which writes all four sends at the new pan.
   - Only after that does it key the voices on (`0x95F2C`, voice +0x4A).

   A plain "old pan until the next 10 ms tick" software bug is therefore ruled out on this path.
2. **The RFX send registers are never cleared or rewritten when a voice ends or is stolen.** Only boot clears them (`0x10E198`, from `0x10E1D4`). Each channel keeps the last note's sends until its next note-on. Bug 1's reports follow from this if one of the following happens:
   - the card ramps (smooths) send changes, so the new attack passes through the old gains for a few ms;
   - the card misses or drops a register write under load (more notes made it worse in p3586).

   This fits razmo's hard-left → centre repro and bendjo's −48 dB attack on the old side. It also fits "Aux send 1 → Main cut the attacks". Without the RFX, the main chip path (`0x60784`) writes the chip's own pan registers, which the users never reported a problem with.
3. **E-mu's own code counts orphaned stereo partners.** The voice release/steal routine `0x194C6C` increments counters at `0x100071C0/C2/C4` when it meets a partner (+0x1A = 8) in an inconsistent state.
   - For `0x100071C2`, the partner's main voice is no longer stereo, and the routine returns without stopping the partner.
   - Note-on sets the partner flag (`0x5F4A8`: partner +0x1A = 8, +0x1E = −1) but nothing clears it when the main voice is next used for mono.
   - With the RFX, a partner's sends are written only from its main voice's stereo branch (`0x609D8` and the tick `0x60B7C`).
   - So an orphaned partner that is still sounding keeps the last stereo pan and level. That would match "mono after stereo plays at the old pan" and the jumping ChanVol bars. **Not proven:** whether an orphan can still be sounding needs a run-time check.
4. With the RFX fitted, `0x609D8` never calls the main chip pan writer `0x60784`. The RFX path (`0x10E280`) writes only the chip volume byte (+0x71) and the RFX sends.
5. The voice ↔ RFX block mapping is fixed at init (`0x194B34`: voice for channel n gets block n, chip n and chip n+1). There is no remapping bug there.

## Bugs 2–5

- Not traced. Bug 2 (bursts on buses with nothing routed) points at the card's DSP or plugin side more than at EOS's send writes.
- On the EOS side, the Multimode submix branch of `0x60334` / `0x60674` (channel send words `>> 5`, ×101/128) is worth a look.
- Bugs 3 and 5 are power-supply reports.

## Possible fixes (not built)

- **A. Clear sends at voice end:** when a voice is released or stolen, write its four RFX sends to 0, or invalidate the block so the next note writes everything. The attack can then never pass through a stale pan. The cost may be a softer first ms if the card ramps from 0.
- **B. Stop orphans:** in `0x194C6C`'s `0x100071C2` case, stop the orphaned partner, or have note-on clear the partner flag when the main voice is used for mono.
- **Before either fix:** reproduce on hardware with an RFX card, using razmo's steps with a recording (as for issue #5). Then add a probe that reads the `0x100071C0..C4` counters after the repro, which shows whether orphans occur.

## Build 4 probe and test (2026-11-05)

- **Probe:** `patches/rfxprobe/rfxprobe.s`, SysEx parameter 195, range 0..191. It takes 180 bytes at `0x1D8F3A`, in the tail of the hole `tools/build_lfock.py` frees.
  - 16 reads the counters at `0x100071C0` / `0x100071C2`.
  - 17 reads `0x100071C4` plus the live orphan partners.
  - 64 + n reads channel n: voice type, send 1 level cache, and pan cache (0xFF7F = invalidated, not yet written).
  - Emulator check: `tools/emu_rfxprobe.py`.
- **Test:** the pan test app's "RFX stuck pan" (`apps/eos-pantest/src/test.rs`), or `--tests rfx` on the command line. Each phase runs as follows:
  1. Hold notes until every channel has played at the old pan (voice Pan −64, then +63; optionally a stereo preset).
  2. Set Pan 0 and read the probe.
  3. Play single notes, measuring L/R over the first 5 ms and over 300–1000 ms after the onset.
  4. Read the probe again.
- **Verdicts:**
  - A note whose attack is more than 3 dB off-centre while its steady part is centred means a stale send at the attack (fix A).
  - A note whose steady part is off-centre is stuck (look at the orphan counts, fix B).
  - The probe's "last RFX pan = old" count shows whether the fill reached every channel.

## First tester data (issue #11, i-am-gor, E4 Platinum + RFX-32, build 4, app 0.4.0; 2026-11-06)
Recordings in `recordings/issue11/` (local). Tester's own bank: preset 000 a mono kick, 001 a stereo snare.
- **The kick lasts under 20 ms**, so the app's steady window (300–1000 ms) measured silence (−98 dB) and its
  "stayed off-centre" verdict means nothing here. The 5 ms attack window is valid (−24.5 dB).
- **Real effect at note start:** one side is silent for exactly 33 samples at 48 kHz (0.69 ms, ~30 samples at
  44.1 kHz, about one processing block). Meanwhile the other side plays about 3 dB louder than centre (hard-pan gain).
  After that, both sides are identical (L−R 0.0 dB from 5 ms on). That gives the ±3.0 dB attack readings.
  - After the Pan 63 fill: all 16 notes, R silent first, L leading.
  - After the Pan −64 fill and after the stereo fill: only notes 15 and 16. Note 15 has R silent first, note 16 has L
    silent first. The same notes are hit in both phases, so this looks tied to particular channels.
  - Direction is unexpected: after a hard-right fill the stale gains should be R on, L off, but L leads. Either the
    RFX L/R order is reversed against our model of 0x10E280, or the cause is something else. Not explained yet.
- **Probe:** no orphans (E-mu counters 0/0/0, live 0). Voice type reads 0 on all 128 channels at every read (the reads
  come after note-off, when the voices are free). The pan caches show the fill reached only 81 (−64) and 73 (63) of
  128 channels with his preset; test bank preset 004 is meant to fix that.
- **App bug:** "Report to GitHub" built a 10,101-character URL; GitHub answered 400 "request URL is too long".

Issue #10 (same tester, main pan via Sub 1, build 4): full range and centre 0.00 dB on voice Pan, Multimode Pan
and CC10, matching our hardware. Steps either side of centre differ by one table step (−8: +1.51, +8: −1.89 dB;
CC 65: −0.37 dB), from the −64..+63 index offset.

## Control run without an RFX card (Tony's E4, build 4, app 0.4.4; 2026-11-14)
`--tests rfx --program 4 --stuck-program 4 --no-load`, preset 004 "RFX Pan Sine" sent over MIDI, Main out to
Quantum 2626 inputs 19/20. 128-note fills at Pan −64 and +63, then 16 notes at Pan 0 each.
- All 32 notes: attack (first 5 ms) and steady L−R 0.00 dB (attack about −41 dB, steady −40.24 dB). No lean, no stuck pan.
- Probe: orphan counters 0/0/0; voice slots read unused, as expected without a card.
- So on the main chip pan path (no RFX), build 4 shows none of the attack lean seen in #11 (build 4 + RFX) and
  #13 (4.70, card unknown). #13's lean therefore comes from an RFX card or from 4.70 itself; jenlun's answer and
  build 4 re-run decide which.

## Code review after the control run (2026-11-14, Ghidra read-only; decompiles checked by hand at the key lines)
- `0x10E280` writes the chip volume, then all 4 sends. It writes both words of each send back to back, with no
  queue and no skip.
  - Word 0 = `0x10E794[(pan+64)^0x7F]`, which is L; word 1 is R.
  - Note-on writes (flag 1 or 2) set bit 15 (0x8000). Tick writes (`0x60B7C`, flag 0) leave it clear.
- `0x10E228` (called only from `0x60334`) invalidates the caches so that a match is impossible: pan 0xFF7F, which the
  −64..63 clamp can never produce, and levels 0xFFFF. It also invalidates the stereo partner block.
- `0x1948F4` runs every start callback (down to `0x10E280`) before any key-on (`0x95F2C`). No queueing gap, and no
  L/R swap in the code. Build 4 changes only the `0x10E794` data.
- Release/steal (`0x194C20` → `0x10DD04` → `0x10E970`) ramps the chip volume to 0 and never touches the sends.
- Register map `0x10E404`: even voices at 0x2xxx and odd voices at 0x0xxx (possibly the two R-Chips). `0x10E120`
  stores a second pointer at block+0x3E (base+0x200); no user of it was found in the RFX module.
- Card side: the per-voice sends look like FPGA or summing hardware; the RFXMixer DSP only sees 24 bus inputs. The
  only ramp found is the plugin parameter glide `0x163D48`.

**Leading explanation:** the card applies send writes about one 32-sample block late, so a voice's first block plays at
its channel's previous gains.
- Fits #11: a clean 33-sample step with one side silent and the other at the old hard-pan gain.
- Fits #13: under the 4.70 law the near side is 0 dB against −7.5 dB at centre, which averages to about 3–5 dB over
  5 ms.
- Fits the control run: the main chip applies its pan at once.

**#11's "reversed" direction:** the +63 fill reached only 73 of 128 channels. Missed channels still held −64 from the
first phase, which gives L loud and R silent. So it is probably stale channels, not an L/R swap (medium-high
confidence).

**Fix ranking changes:** clearing the sends at voice end (old fix A) would turn the stale pan into a silent first block
on both sides. The better fix is to wait 2 card blocks (about 1.4 ms) between the start callbacks and key-on in
`0x1948F4`, only when the RFX is present (`0x10004D88`).

**Tests:**
1. Level-only test: send 1 at 0%, then at 100%, at a fixed pan. A silent first block confirms the late latch without
   involving the pan code.
2. Build with the key-on delay.
3. Log each test note's channel and its pan cache (probe 64+n).
4. Bit-15 experiment.

## Card-side review: where the send words land (2026-11-14)
- **Location:** the per-voice RFX send words are **not** RFX card registers. They are in the main voice-chip register
  window.
  - Base `0x10004D78` = `0x08200000` (128 voices or RFX flag `0x100005F6`; otherwise `0x08204000`). It is set by
    `0x2A36C` → `0x10D980`.
  - Each voice's chip registers (`0x10EC0A[v]`) and its send words (`0x10E404[v]`, offsets 0x800–0xBB0) sit in the same
    8 KB block for all 128 voices. Checked against the binary.
  - The card's own windows are elsewhere: FPGA config `0x02504001`, status `0x02500000`, R-Chip DSPs
    `0x08300000` / `0x08304000`.
- **No code latches or ramps the sends:**
  - RFXMixer DSP code takes buses that are already summed, and has no per-voice gains, block copy or ramp.
  - The FPGA (FLEX EPF6016, 32,385 bytes at `0x1149A4`) can't be decoded, and the sends don't go to it anyway.
  - Bit 15 is set only at note-on by `0x10E280`; nothing reads it.
  - block+0x3E (base+0x200) is a dead field: it lands on another voice's sends for 64 voices.
- **No sync:** EOS never syncs key-on to the mixer frame. Amp registers have an "apply now" command (+0x46=1); send
  words have none.
- **Conclusion (inference, medium-high):** the one-frame staleness is inside the voice/mixer chip. It picks up send
  gains once per ~32-sample frame, so the first frame of a new voice is summed with the previous sends. The main pan
  path is clean because +0x46 applies it at once (control run).
- **Tests and patches that follow:**
  1. Stale length over many notes. If it spreads over 1–33 samples, the chip latches per frame and key-on is
     unsynced; a constant 33 means a fixed latency.
  2. Bit-15 builds.
  3. Fix candidate: a busy-wait of at least 2 frames (~1.4 ms) between the start callbacks and key-on in `0x1948F4`,
     only when RFX is fitted (`0x10004D88`).
  4. Log each test note's channel and its group (`ec0a[v]>>13`).

## Card control registers and what the RFX flag changes (2026-11-14)
**`0x02500000` (control, read-modify-write):**
- Bits 0–2 (+4) select a port for the per-chip-group config word at `0x08207FFE` (`0x10DD88`). It is written at boot
  only (`0x10E1D4`): ports 0,1 = 0x114, ports 2,3 = 0x14. Bit meanings are unknown.
- Bit 3: before R-Chip init (`0x2A3CC`).
- Bit 7: input-card pulse.
- Bits 4–5: ADAT sampling source.
- Bit 8: acknowledge for the status bit 4 poll (`0x4CA40`).

**`0x02500002` (status, read only):**
- Bit 1: input card. Bit 2: output card. Bit 3: output mode.
- Bit 4: polled from a background task (probably clock lock). Not a frame flag.

**`0x02500004`:** per-channel-pair source mux for voice channels 0–15 (table `0x19245C`), written per note by the
allocator `0x191AC0`. Card audio can replace those channels. It plays no part in gain timing.

**`0x02504001`:** FPGA configuration, boot only.

**DSP hooks `0x10006488..A0`:** GPR, program and TRAM upload only.

**Card detect:** `0x100005F6` = bit 0x8000 of `0x02300000` AND a successful FPGA load. What the flag turns on:
- base `0x08200000`, even on 64-voice units;
- 128 channels (voices 0–63 are dummies on 64-voice units);
- extra chip config bit 0x0202 on pages 0 and 2 only;
- the send-word code;
- the mux;
- R-Chip init.

Without the RFX nothing writes offsets 0x800–0xBBF.

**Conclusion:** on 128-voice units the sends are voice-chip registers (high confidence). On 64-voice units with an
RFX, channels 0–63 may be served by the card (open, does not affect the Platinum reports).

**Answers:**
- No voice-mixer frame or sync flag exists.
- No mode bit makes sends apply immediately. Untested: the 0x114/0x14 config word bits, and send-word bit 15.
- Time base for a key-on delay: the R-Chip sample counter at `0x08300054` (`0x16C254`:
  `(period-1) - (*(ctx+0x54) & 0xFFFFF)`; inferred to count samples). Wait at least 64 samples between the start
  callbacks and key-on in `0x1948F4`, only when `0x10004D88` is set.

## Issue #14 (jenlun, E6400 Ultra + RFX, build 4): the lean is a glide, not a stale frame (2026-11-14)

- Data: tester-data/issue14-jenlun (32 rfx_stuck WAVs, 48 kHz float, inputs 1/2 = main out).
- I measured attack L-R in 16-sample blocks after onset (scratchpad lean.py/shape.py). Every note, both directions:
  +70, +46, +31, +16, +11, +7, +5, +2.4 dB (blocks 0..7), then about 1.4 dB at 128 smp, about 0.45 at 160, and 0 by about 224 smp (4.7 ms).
- Spread across 32 notes: under 3 dB in block 0 and under 1 dB later. The curve is deterministic.
- Shape: the old pan holds fully for about the first 0.5 ms, then the gain moves toward the new pan with a time constant of about 40 samples. It settles in about 4.5 ms.
- So the RFX send gain is **smoothed (ramped) from its previous value**. That is not consistent with a single 32-sample frame latch. The non-RFX main path shows no lean (control run).
- Fix consequence: a 64-sample key-on delay is too short. Options:
  - (a) Delay key-on about 5 ms (240 smp at 48 kHz, timed with the R-Chip counter `0x16C254`) only when the channel's cached pan differs from the new pan. The cache comes from `0x10E280`.
  - (b) Write the sends to the new note's values as early as possible (at voice allocation).
  - (c) Accept it: the lean is under 5 ms.
- Multimode Pan / CC10 flat on #13 and #14: `0x609D8` adds channel pan (+0x62) only when the mode byte `0x10004F04 == 2` (Multi). The same code runs with and without RFX (`0x60784` vs `0x60674`). Likely cause: the tester's E4 is not in Multi MIDI mode. Asked in the #14 reply draft (not posted).
