# RFX mixing, sends and pan in EOS 4.70 (traced 2026-11-04)

Sources: Ghidra decompiles of 0x10DD04–0x10EC0A (CHIP/RFX mixer module), 0x60334 and 0x60674 (voice side);
tables dumped from `bin/eos470_flash_0x20000.bin`; hardware check against GitHub issue #5 (E4 Platinum with
RFX-32, Bus1 → Sub Out 1, preset with a dry mono voice, EOS 4.71-beta2 b3+LfoCk).

## Code

| Function | Role |
|---|---|
| `0x10E1D4` | Boot: if the RFX card is present (`0x2AC4C`), configures card ports 0–3, builds the per-voice RFX blocks and clears the send registers; sets the RFX flag `0x10004D88 = 1`. |
| `0x10E120` | Builds 128 per-voice RFX blocks at `0x1030DDC4 + 0x42·i`: register pointers from `0x10E404[i]` (+0 and +0x200) and the voice chip address. |
| `0x10E198` | Clears 8 send words per voice. |
| `0x60334` | Note-on send setup: four sends per voice. Level = `0x61890[send %]`; destination bus = `0x614F8[dest]`. Multimode channel sends use the channel word `>> 5`, scaled by 101/128 to −101..100. Then `0x10E228` fills each send's L/R destination codes from `0x10E754` / `0x10E774`. |
| `0x60674` | Note-on and every amp tick (from `0x609D8`, `0x60B7C`): stores volume, final pan and flags in the voice's RFX block, adds send modulation, calls `0x10E280`. |
| `0x10E280` | The RFX voice writer: volume byte → chip +0x71; pan clamped −64..63; for each of the 4 sends, if level or pan changed: L = `(level + 0x10E794[(pan+64)^0x7F]) >> 4`, R = `(level + 0x10E794[pan+64]) >> 4`, each → `0x10E504[idx] + 0x10004D84` (0 stays 0), OR destination code (+0x8000 for flagged voices) → two RFX registers. |
| `0x10DE10` | Sets the send offset `0x10004D84` to −0x60 or −0x1D (called from boot code `0x24FF4`). |
| `0x10EA48`, `0x10DE60`, `0x10EB2C` | Non-voice channels (audition/preview/monitor: callers in UIWIDG, BEAT, SAMPLING, RFXHOST, ARP, DUNIT). Pan law `0x10F10C` (±128) through curve `0x10EE0C` to the chip volume bytes, or with RFX to `0x10E504`; `0x10EB2C` uses the byte law `0x10ED0A`. |

## Table checks

| Table | Check | Result |
|---|---|---|
| `0x10E794` RFX pan law (128 words) | Byte-identical to the main chip's `0x61590` | Same table, same stock centre pair −322/−311 |
| `0x10E504` RFX gain (256 words) | 0, then 292 + 2i | Exact; monotonic. With the offset: 196..771, so it never spills into the destination bits (≥ 0x400) |
| `0x61890` send % → level (−101..100) | Fit 4096 + 853.7·log10(k/100) | Exact at every value checked (1% = 2389 … 100% = 4096): an amplitude law, **42.68 units per dB**, so one `0x10E504` step (16 units) = **0.375 dB**. 100% (4096) clamps to 4095 in `0x10E280`: −0.02 dB, harmless. Negative side: an attenuation tail −10 … −18695 |
| `0x10E404`, `0x10EC0A`, `0x10E714`/`0x10E734` | Voice index ↔ register maps | All 128 unique; `0x10DFF4(0x10EC0A[i]) == i` for every voice; the two page tables are identical |
| `0x10E754` / `0x10E774` / `0x10E704` | Destination codes | L = `0x10E704[k] << 10`, R = `(0x10E704[k] + 2) << 10` for all 16 |
| `0x614F8`, `0x61990`, `0x61528` | Bus maps | 0, 2, 3, 4, 5, 6, 7, 10–15; [0, 1]; 15, 1 |
| `0x10F10C` (±128 words), `0x10EE0C`, `0x10ED0A` | Monotonic | Yes |

## Findings

1. **The RFX pan law is about 2.5× too steep (stock E-mu bug).** `0x10E794` is a copy of the main chip's sine-law
   table, which is built for chip units of about 0.15 dB (−311 >> 4 = −20 units ≈ −3 dB at centre). On the RFX path
   the same values index `0x10E504`, whose steps are 0.375 dB. So centre is **−7.5 dB** per side instead of −3 dB,
   and a sound panned from hard to centre loses about 4.5 dB of power.
   - Hardware confirms it: the model `((0xFFF + t) >> 4) · 0.375 dB` matches issue #5 within 0.15 dB at every pan
     from −48 to +48 (for example −8: measured −5.26 / −9.40 dB, model −5.25 / −9.38).
   - Only voices routed through the RFX card are affected. The main chip path (`0x60784`) uses the table at its
     intended scale.
   - A fix would be a separate RFX table of `round(t · 0.1505 / 0.375)`, giving −3 dB at centre.
2. **The centre imbalance is still there on the RFX path in every 4.71 build.** Build 2/3's `PAN_FIX` patched
   entries 63/64 of `0x61590` only; `0x10E794` still has −322/−311. Centre lands one step apart: **0.375 dB right
   louder** (issue #5 measured 0.39 dB). The pan test app's note says "about 0.24 dB", which is the main-output
   figure.
3. **Non-voice channels, minor:** the `0x10F10C` law's centre pair (−2078/−2055) is 23/128 of a step apart, so it is
   level-dependent and at most one step. The `0x10ED0A` byte law has centre −1/0, so one side is one volume-byte
   unit quieter. Both are on audition/monitor paths only.

## Fix (next build, 2026-11-05)

`tools/build_beta2.py` (`RFX_PAN`) rewrites `0x10E794` in place, with no code change: each entry is the fixed main law
`0x61590` (with PAN_FIX) scaled to RFX units, `(t * 105) >> 8`, and entry 0 is kept at −4096 (silent). The near side
at hard pan stays 0 dB, and centre is −3.0 dB on both sides (8 steps; −316·105 >> 8 = −130), which matches the main
outputs. A voice moved between Main and an RFX bus keeps its level at every pan. The far side is still silent.
The build checks first that `0x10E794` is still the stock copy of `0x61590` and that its only reference
(`movea.l #$10e794,a5` at `0x10E2FE`) is in place.

Proof:
- `build/eos471_beta2_b3_rfxpan.bin` ("EOS 4.71-b2 b3+RfxPan", checksum `0885a41f`) differs from build 3 only in the
  header (name, checksum) and `0x10E794`–`0x10E893`.
- `tools/emu_rfxpan.py build/eos471_beta2_b3.bin build/eos471_beta2_b3_rfxpan.bin` runs the real `0x10E280` in both
  images: every pan −64..63, 10 send levels, both send offsets. That is 3,072 send writes each, with 0 mismatches
  against the model.
  - Build 3 gives −7.5 / −7.125 dB at centre (as measured in issue #5).
  - The fixed image gives −3.0 / −3.0 dB at centre and 0 dB / silent at hard pan.
- Not yet measured on hardware.
