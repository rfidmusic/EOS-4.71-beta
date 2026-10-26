# 4 Pole LP+Fuzz: what the existing filter does (analysis 2026-10-24)

**Data:** `recordings/fr_fix_merged`, the E4 grid on build 2 (its LP+Fuzz is identical in OrigFilt; emulator
2,584 / 0). The run used 16 cutoffs × 16 Q, the 6 s sweep, and 20 s retakes at cutoff ≤ 16 / Q ≥ 64. Clip ceiling
−12.7 dBFS. Chart: `recordings/lpfuzz_analysis.png` (`tools/lpfuzz_analysis.py`).

## Structure (zeros on, SETMODE 0xC0)
Corrected 2026-10-24: Fuzz8 hardware takes show how the chip pairs words with the zeros on. Pole 0 is a stage of its
own (a normal 2-pole low-pass), zero 1 pairs with pole 4, zero 5 pairs with pole 8, and word 9 is the gain. E-mu's
HP4 has the same layout: pole 0 neutral, then DC zero over pole twice.

The OB-Xa 4-pole ladder runs at Q/2. The chip words are:

| Words | Contents | Role |
|---|---|---|
| 0 | Ladder pole A (LADA) | The stand-alone 2-pole low-pass at the cutoff |
| 1 / 4 | Zero 1 starts as LADA; pole 4 = LADB | The **drive pair**. At Q 0 LADA = LADB, so it is transparent. The zero slides toward 0xFFE0 as Q rises and boosts everything below it by about (f_zero / f_cutoff)² |
| 5 / 8 | Both LADB | Cancelled |
| 9 | LP4 gain law (base − GOFF[Q >> 4]) | Level |

So at Q 0 it is a 2-pole low-pass. The drive pole is at the cutoff, so the lower the cutoff, the bigger the boost.

## Measured behaviour
- **The fuzz is the chip clipping.** At every cutoff, audible distortion (THD > −30 dB) starts within one Q step of
  the output reaching the clip ceiling. Above that the level stops rising (+28…+29 dB over Q 0, +40 at cutoff 0),
  and THD sits at about −5 dB (hard clipping).
- **Onset by cutoff:**

| Cutoff | Fuzz starts at Q |
|---|---|
| 0–48 | 40–48 |
| 64–96 | 56–72 |
| 112–144 | 80–112 |
| 160 | 127 only |
| 176–240 | Never: the boost (+3…+18 dB) stays below the ceiling |

- **The onset is abrupt:** from clean (−49 dB) to −15 dB THD within about one or two Q steps (8–16), so the Fuzz knob
  acts more like a switch than a gradual drive.
- **Bass loss when driven:** 50 Hz is up to 13–15 dB below 101 Hz at high Q and low cutoffs, against 0–2 dB at Q 0.
- **Neither linear chip model predicts the level above the ceiling** (they keep rising to +50…+76 dB). Below the
  ceiling, the paired-section model ("a pole and its zero form one unscaled ratio") is closer than the per-stage law,
  especially at high cutoffs (`tools/fuzz_model.py`).

## What this means for the Fuzz variants
- **What a variant needs:** a boost that pushes its output about 24 dB above its Q 0 level. The fuzz then happens on
  its own, through the same chip clipping.
- **Which LP+Fuzz traits are deliberate choices:** "fuzz only below cutoff ~160" and the abrupt onset follow from the
  boost pole tracking the cutoff and from the zero law. A variant can keep them, for a family feel, or change them,
  for example a fixed low boost pole for fuzz at every cutoff, or a gentler zero law.
