# Fuzz filters on the stock E-mu filters (test build Fuzz6, 2026-10-24)

**Build:** `tools/build_fuzz.py build/eos471_beta.bin build/eos471_fuzz6.bin`, giving "EOS 4.71-b2 Fuzz6 T", checksum
0885a75c, `sysex/EOS471-b2-fuzz6-T.syx`. Engine: `patches/fuzz/fuzz.s`. Not released; not committed.

**What changed:**
- **E-mu filters back in place:** 0x65C00–0x67F98, their vtables and table 0x6875C are byte-identical to 4.70.
- **OB-Xa models removed from the firmware.** Their code stays in the repository; the original LP+Fuzz v5 is in
  `patches/lpfuzz/lpfuzz_v5_original.s` and tag v4.71-beta.2.

## Chip pairing with the zeros on
Pole 0 is a stage of its own, zero 1 pairs with pole 4, zero 5 with pole 8, and word 9 is the gain. The first
design (Fuzz8, 08858cb0) assumed (0,1)/(4,5). Its 2 Pole LP+Fuzz measured a +35 dB bass boost already at Q 0 (13
takes, `recordings/fz8_fast`). Fuzz8 is withdrawn.

## Design: each variant = the stock filter at q/2 + the LP+Fuzz drive
- **LP+Fuzz limits and laws:** high-frame F capped at 0xDF, word 9 = base − GOFF[q >> 4], level =
  ((q >> 1) · −20) >> 7.
- **The drive pair:** pole = the filter's resonant pole (follows the cutoff); zero starts on it and slides toward
  0xFFE0 by q/127 (the original law).

| Menu | Filter | Type | Recipe |
|---|---|---|---|
| 21 | 2 Pole LP+Fuzz | 0x04 | w0 = LP pole; drive w1/w4, with the drive pole's damping raised to X ≥ 0xC0 (smoother) |
| 22 | 4 Pole LP+Fuzz | 0x03 | w0 = LP pole; drive w1/w4 (the original design) |
| 23 | 6 Pole LP+Fuzz | 0x05 | As 4 Pole, plus a resonance-peak pair w5/w8 (zero = pole with no damping) |
| 24 | 2nd Ord HP+Fuzz | 0x0A | Stock HP pair w1/w4; drive w5/w8 (stock neutral pair) |
| 25 | 2nd Ord BP+Fuzz | 0x13 | Stock BP2, whose words 0/1/4 are E-mu's level compensation (−40 dB at cutoff 0). The drive is the band-pass pair w5/w8 itself: its zero slides up from E-mu's zero (Q 0 = stock BP2) |
| 26 | Contrary BP+Fuzz | 0x15 | Stock pole w0, stock w5/w8; drive w1/w4 (stock neutral pair) |

**Dropped:** the 4th-order HP and BP, which need both pairs for their shape.

## Test switch: parameter 195
0 is the LP+Fuzz design.

| Bit | Meaning |
|---|---|
| 0 | Fixed drive pole (X 0xC0, F per bits 2–3: 0x71 / 0x60 / 0x80 / 0x50) |
| 1 | New zero law (F + (q × 0x6F) >> 7) |
| 4 | No q/2 limit |

## Verified (emulator, `tools/emu_fuzz.py`: 79,287 checks, 0 failures)
1. **E-mu filters:** byte-identical to 4.70, and behaviour identical.
2. **Registry:** 28 entries in this order; type ↔ menu round-trips.
3. **Variants:** match a Python reference of each recipe for switch 0–31, every q, both cf modes, packQ, and the
   formatter.
4. **Chip model** (the real pairing):
   - each drive pair is transparent at Q 0;
   - HP2 / BP2 / CBP match the stock filter at Q 0, and the LP variants match their stand-alone pole;
   - the drive rises with Q and is ≥ +20 dB at Q 127 for cutoff ≤ 128.

   **This check fails the old Fuzz8 image** (58 failures).

**Other suites:** slice, slicer, port map, slew and pan pass.

## Hardware plan
- **Grid:** the reduced grid, menu 21–26 × cutoffs 0/32/64/96/128/160/192/240 × Q 0/16/…/112/127, at switch 0.
- **Sweeps:** the 6 s sweep, plus 20 s retakes at cutoff 0, Q ≥ 64.
- **Report:** level rise, clipping, THD.

## Fuzz6 on hardware (2026-10-25, switch 0)
Grid: menu 21-26 x cutoff 0,32,64,96,128,160,192,240 x Q 0,16,...,127, 6 s sweep (key 81), 20 s retakes at
cutoff 0 / Q >= 64. recordings/fz6_fast, fz6_slow, merged fz6_merged; tools/fuzz6_analysis.py (vs fr_fix_merged).
**Rig:** the E4 was on its 44.1 kHz fallback clock (ADAT word clock lost; Fuzz8 run too): sweeps played at
0.9194 x rate. Merged with `filter_fr_merge.py ... --rate 0.9194`; cutoffs read ~1.45 semitones lower than at 48 kHz.
- 4 Pole: does **not** match the original LP+Fuzz. Band levels (101-4064 Hz) are mostly 1-2 dB lower, up to
  10 dB lower at cut 0 Q 80 and cut 32/64 Q 112, and 3-5 dB higher at cut 0 Q 112-127; fuzz starts one Q step
  earlier at cutoff 96-160 (THD at cut 160 Q 127: -12.5 vs -18.1 dB). Not separable from the 44.1 kHz clock
  (original measured at 48 kHz) until re-measured at 48 kHz.
- 2 Pole: same rise, milder: fuzz from Q 80-127, none above cutoff 128.
- 2nd Ord HP: like the 4 Pole (rise +27-29, fuzz from Q 48 at low cutoffs to Q 127 at 160).
- 2nd Ord BP: rise +29 dB but fuzz only at cutoff <= 64 and Q >= 112.
- Contrary BP: most fuzz, clips at every cutoff at Q 127; quiet (-4..-9 dB) at Q 0 in the mids (its shape).
- 6 Pole: **fault** at Q 0: +33 dB peak near 100 Hz and clipping at cutoff <= 64, +26 dB hump at 96, so Q does
  little there; the chip model did not predict the third-section boost (PEAK on 5/8).
- All: little drive at cutoff >= 192, as the original LP+Fuzz (inherited, not a regression).

### 4 Pole re-measured at 48 kHz (2026-10-25; recordings/fz4p48_merged vs fr_fix_merged)
- Q 0-32: same as the original within 0.2 dB at every cutoff (the earlier 1-2 dB gap was the 44.1 kHz clock).
- Q >= 48: different. (Correction 2026-10-25: the Q 127 peak -15.9 vs -13.0 dBFS is the rig, not the filter: the
  original's run had its reference at -40.8 dBFS, today's runs -43.7; the original code on FuzzOB also peaks at
  -15.9. Band levels are relative to each run's reference, so the rest stands.)
  cutoff 0 passband up to +6 dB at Q 64-127; fuzz starts one Q step earlier at cutoff 96-160 (THD at cut 96 Q 64:
  -20 vs -45 dB; cut 128 Q 80: -20 vs -56; cut 160 Q 112: -18 vs -51); at cutoff 160-240, Q 96-127, 1-3 dB lower.

### Why the 4 Pole differs from the original (emulator, tools/fuzz_cmp_lp4.py)
- Same return value (level), same calls, same w9 and w1 law. Different base filter: the original LP+Fuzz runs on
  **build 2's 4 Pole Low-pass** (vtable 0x688A4 is not stock in build 2), which writes two different ladder
  sections: w0 = LADA (X falls with Q, e.g. 0x64 at Q 127) and w4 = LADB (X rises, 0x7F -> 0x89). Fuzz6 runs on the
  **stock** 4 Pole Low-pass, which writes the same section to w0 and w4 (X 0x7D -> 0x6D).
- So the drive pole (w4) is far more resonant in Fuzz6, and w0 slightly less. The original also copies LADB into
  w5 = w8 (cancelling pair); Fuzz6 writes neutral there (also cancelling).
- Chip model (paired zeros): Fuzz6 block peak gain is higher by +1.5 dB at Q 48 up to +6 dB at Q 127 (cutoff 0-128),
  +0.5..+4 dB at 160-192. That explains the earlier fuzz onset and the louder cutoff-0 passband measured.
- Not explained by the model: the 1-3 dB lower level at
  cutoff 160-240, Q 96-127 (the lower clipped output was the rig's 2.9 dB reference difference, see above).

## FuzzOB: five Fuzz filters on the OB-Xa models (test build, 2026-10-25)
`tools/build_fuzzob.py build/eos471_beta.bin build/eos471_fuzzob.bin` -> "EOS 4.71-b2 FuzzOB T", checksum 08859d7b,
`sysex/EOS471-b2-fuzzob-T.syx` (12,334 messages, ~9 min). Not sent, not committed. The 6 Pole is dropped: with the
zeros on the chip has only one plain low-pass stage, so a third section can't be a low-pass (Fuzz6's +33 dB fault).
- Base: OrigFilt's layout (build 2 rebuilt from beta1 with `--origfilt`, disk-unit compaction, stock E-mu code
  copied out, OB-Xa code in place) via `build_origfilt.prepare(nfz=5)`; OrigFilt still rebuilds byte-identical.
- Menu: 0-20 E-mu (stock), 21 2 Pole LP+Fuzz (0x04), 22 **4 Pole LP+Fuzz = build 2's original code** (0x03),
  23 2nd Ord HP+Fuzz (0x0A), 24 2nd Ord BP+Fuzz (0x13), 25 Contrary BP+Fuzz (0x15), 26 default.
- Engine `patches/fuzzob/fuzzob.s` (368 bytes, 6 sections): OB-Xa model at q/2, program, LP+Fuzz level laws.
  Programs = Fuzz6's on the OB-Xa bases, without the 0xDF cap (never acts: the capped words stay <= 0xD8):
  lp2 w4 = SMTH(w0), w1 = zlerp(w4); hp2 w8 = w4, w5 = zlerp(w8); bp2 w5 = zlerp(w5); cbp w4 = w0, w1 = zlerp(w4).
  DZER calls lpfuzz.s `zlerp`; formatParam idx 1 -> lpfuzz.s `lpf_fmt`.
- Space: compaction block remainder, two unused OB-Xa pieces (0x6627C-0x662D4 HP4 table, 0x65E62-0x65E9E old LP
  code: changed from stock, never executed/read by any remaining filter, no reference anywhere), string holes.
- Verified (`tools/emu_fuzzob.py`): E-mu vs 4.70 20,672 calls; registry 27; 4 Pole vs build 2 2,584 calls;
  engine vs reference + Q 0 transparency 6,280; reused bytes untouched; 29,590 checks, 0 failures; mutations 10/10.
  Other suites pass (unit compaction, slice, slicer, port map, slew, pan; Insert Silence flags the intended diffs).

### FuzzOB on hardware (2026-10-25, 48 kHz, recordings/fob_merged; tools/fuzz6_analysis.py --fuzzob)
Grid menu 21-25 x cutoff 0..240 (8) x Q 0..127 (9), 6 s sweep, 20 s retakes at cutoff 0 / Q >= 64. Reference
-43.7 / -44.1 dBFS (start / end), -44.0 for the retakes.
- **Menu 22 (original code) = the original LP+Fuzz:** every band (101-4064 Hz, all 72 settings) within 0.5 dB for
  95 % (median 0.3 dB, a constant offset; worst 4 dB at cutoff 0, the steep low-cutoff edge). Fuzz onset Q 48/48/64/
  80/96/127 and THD at Q 127 -5.3/-5.3/-5.3/-5.4/-8.0/-18.1 at cutoff 0-160, the same as the original run.
- 2 Pole: rise +29 dB, fuzz from Q 80-127 up to cutoff 128 (Q 0 at cutoff 0 is 1.6 dB under the reference).
- 2nd Ord HP: rise +29 dB, fuzz from Q 64 (cutoff 0-32) to Q 112 (cutoff 128); clean above.
- 2nd Ord BP: rise +29 dB at low cutoffs, fuzz only at cutoff 0-64 and Q 112-127; milder than the others.
- Contrary BP: fuzz at every cutoff (clips even at cutoff 240, Q 127). Its Q 0 "THD" at cutoff 128-160 is the noise
  floor (take peaks -53..-62 dBFS), not distortion.
- All except Contrary BP: little drive at cutoff >= 192, as the original LP+Fuzz.
