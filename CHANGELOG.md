# Changelog: EOS 4.70 → EOS 4.71-beta

## EOS 4.71-beta2 build 3

Header name **EOS 4.71-beta2 build 3**, image checksum `08859e24`. Includes everything in EOS 4.71-beta2 build 2
except the OB-Xa filter models in the filter list. Apps v0.3.0 build it by default; build 2 stays available.
Checked in the emulator (`tools/emu_fuzzob.py`, 29,590 checks: E-mu's filters against EOS 4.70, the 4 Pole LP+Fuzz
against build 2, the other Fuzz filters against a reference) and measured on an E4 Ultra with the sine-sweep grid
(`notes/fuzz.md`).

### Changed: E-mu's own filters are back
- **Why:** after multiple tests and retuning, the OB-Xa filter models offered too little at too much cost.
- The 21 filters of EOS 4.70 are back with E-mu's own code, order and type numbers, and sound exactly as in 4.70.
- **Presets from the earlier betas:** presets saved in 4.71-beta, 4.71-beta2 or build 2 that used a lowpass,
  highpass or bandpass filter (the OB-Xa models) now play E-mu's filter of the same name. They can sound
  different: E-mu's cutoff calibration and resonance instead of the OB-Xa's. Presets made in EOS 4.70 sound as
  they did there.
- Going with the OB-Xa models: their cutoff calibration, the smoother resonance steps of 4.71-beta2, build 2's
  high-pass level trim at high Q, and the 4th Order High-pass distortion at cutoff 240 / Q 127.

### New: Fuzz filters
Five Fuzz filters at the end of the filter list, after Peak/Shelf Morph. **Q** is shown as **Fuzz**. At Fuzz 0
each one is its plain filter; as Fuzz rises, a drive stage pushes the E4's filter chip into clipping, with up to
about +29 dB of gain.

> **Be mindful of gain: the Fuzz filters get LOUD.** Turn the voice volume down before turning Fuzz up.

| Filter | Built on | Fuzz (measured, sine sweep) |
|---|---|---|
| 2 Pole LP+Fuzz | OB-Xa 2-pole lowpass, milder drive pole | from Fuzz 80–127, up to cutoff 128 |
| 4 Pole LP+Fuzz | unchanged from build 2 (same type number) | from Fuzz 48 at low cutoffs to Fuzz 127 at cutoff 160 |
| 2nd Ord HP+Fuzz | OB-Xa 2-pole high-pass | from Fuzz 64 at low cutoffs to Fuzz 112 at cutoff 128 |
| 2nd Ord BP+Fuzz | OB-Xa band-pass | the mildest: cutoffs 0–64, Fuzz 112–127 |
| Contrary BP+Fuzz | the betas' Contrary Band-pass | the strongest: from Fuzz 48–80 at every cutoff |

- All but the Contrary BP+Fuzz have little drive above a cutoff of 192.
- The **4 Pole LP+Fuzz** is build 2's filter, unchanged: presets that use it play the same. Only its place in the
  list changes (second of the five).
- The 4th Order High-pass and Band-pass have no Fuzz version: they leave no free stage for the drive.

### Internal
- To make room: the disk-unit tables are folded into one record, and nine duplicate strings are merged. Drives
  work as before. Tested on an E4 Ultra: all SCSI IDs, CD-ROM, format, load, save and directory. Floppy format and
  boot were not tested.

### Apps v0.3.0
- EOS Flasher builds build 3 by default; build 2 and 4.71-beta stay selectable.
- New patch format: E-mu code that build 3 moves to a new place is copied within your own 4.70 when the OS is
  built, instead of being shipped. The patch holds only this project's bytes (6,597) and the copy steps.

## EOS 4.71-beta2 build 2

Header name **EOS 4.71-beta2 build 2**, image checksum `0886960e`. Includes everything in EOS 4.71-beta2 (build 1,
`0886a24c`); only the filter levels below change. Apps v0.2.1 build it by default. Checked in the emulator
(`tools/emu_filterfix.py`: every Q, note-on and real-time, with Master Headroom 0 and 15) and measured on an E4
Ultra with the sine-sweep grid (`notes/filter_survey_beta2.md`).

### Fixed: high-pass filters ran hot at high Q
- **Problem:** in beta1 and beta2 the 2nd and 4th Order High-pass kept the same level at every Q, so at high Q
  they came out up to about 10 dB louder than in EOS 4.70. The 4th Order High-pass came within 3 dB of the
  filter chip's clipping point at 15 cutoff/Q settings.
- **Fix:** the filter's input level is now lowered as Q rises, through the same gain word that Master Headroom
  uses. The cut grows with Q², so low Q is almost unchanged. It applies at note-on and when Q moves in real time.
  Master Headroom still works on top of it.

| Filter | Cut at Q 64 | Q 96 | Q 112 | Q 127 |
|---|---|---|---|---|
| 2nd Order High-pass | −1.2 dB | −2.9 dB | −4.2 dB | −5.9 dB |
| 4th Order High-pass | −1.8 dB | −4.9 dB | −7.4 dB | −11.8 dB |
| Contrary Band-pass | −0.6 dB | −1.3 dB | −1.8 dB | −2.3 dB |

- **4th Order High-pass:** settings within 3 dB of the clipping point fell from 15 to 5. At Q 127 the peak at low
  and medium cutoffs is now at or below EOS 4.70's (cutoffs 48 / 96 / 144: +11.8 / +17.3 / +21.7 dB against
  stock's +25.8 / +23.2 / +19.8).
- **Known behaviour:** at cutoff 240 with Q 127, the 4th Order High-pass distorts: a strong extra tone near
  3.2 kHz appears (THD about −4 dB). It reproduces on every take and is kept as part of the filter's character.
  Neighbouring settings are clean or mildly coloured: cutoffs 240–248 at Q 116–124 measure THD −48 to −35 dB.
- **Contrary Band-pass:** the small trim does not stop it reaching the clipping point at high cutoffs and medium
  Q. EOS 4.70's Contrary Band-pass does the same, so it is left as is.

### Fixed: LP+Fuzz level stepped at note-on
- **Problem:** at note-on the 4 Pole LP+Fuzz set its output level from a 16-step table, while real-time Q changes
  used a smooth curve. Between Q 104 and Q 112 this left a 0.7–2 dB dip at cutoffs 176–240.
- **Fix:** note-on now uses the same smooth curve. The dip is gone. Q 32 and Q 96–104 sit 1–1.5 dB lower at
  note-on than before, matching what a real-time Q move already gave. The fuzz itself is unchanged.

## EOS 4.71-beta2

Header name **EOS 4.71-beta2**, image checksum `0886a24c`. Includes everything in EOS 4.71-beta. Every change was
checked in the emulator against stock code paths and tested on an E4 Ultra.

### New: 4 Pole LP+Fuzz filter
- A new filter type, last in the filter list (after Peak/Shelf Morph), so all other filter numbers are unchanged.
  It is the OB-Xa 4-pole ladder (half its resonance curve) with a drive stage that overloads the E4's filter chip.
- Q (shown as Fuzz) raises the drive: clean at Q 0, clipping near the cutoff and then across the passband as Q
  rises at low and medium cutoffs. It stays clean at high cutoffs (200 and up). Frequency and Q work in real time.

### New: smooth resonance on the OB-Xa filters
- The OB-Xa lowpass, highpass and band-pass models interpolate between their resonance table entries, so Q
  changes smoothly. In 4.71-beta it moved in steps of 4 or 8; on the E4 the largest step halved.

### New: Sample Edit Insert Silence
- Utils → Silnc inserts 4 samples of silence at the chosen point (with undo), the lead-in loops and wavetables need.

### New: 'Slice cord destination
- Plays one equal-length slice of a sample per key (or controller step), counted from the zone's original key.
  The slice length is the sample's loop. Set at note-on; works with the loop on or off, mono or stereo.

### New: Beat Munger Slice key
- Turns Beat Munger's slice points into one new sample per slice and a new preset, with slice 1 on key 36 and each
  slice on its own key at its original pitch.
- Each cut is placed 11 ms before Beat Munger's onset, which lags the attack, and then snapped back to the nearest
  zero crossing within 6 ms.
- The source loop, the clipboard and the Sample Edit selection are kept. Nothing changes if there are not enough
  free sample slots, presets or memory.
- Code space comes from rewriting the plugin port-map builders as a table-driven loop (2,236 → 196 bytes,
  identical behaviour).

### Changed: WTScan (formerly SLpScn)
- Notes start at the current loop position instead of the sample start.
- Fast source moves glide, at most 64 samples per 10 ms, so fast envelopes and wheel moves no longer burst.

### Apps
- **EOS Flasher** builds EOS 4.71-beta2 (default), EOS 4.71-beta or the original 4.70 from your EOS470.EXE.
- **EOS Pan Test** also reports whether the pan centre is balanced, and lists 4.71-beta2 as a firmware choice.
- Both are available for macOS 11+ (universal), macOS 10.13 High Sierra+ (Intel), Windows and Linux (Flatpak).

### Fixed: centre pan leaned slightly right
- In EOS 4.70 and 4.71-beta, a centred pan (0, CC10 64) came out one gain step louder on the right (about
  0.24 dB measured).
- **Cause:** E-mu's pan gain table has 128 entries, so the true centre falls between entries 63 and 64. Pan 0
  reads entry 64 for one side and entry 63 for the other.
- **Fix:** beta2 gives those two entries the same value. Centre is now exactly balanced, and every other pan
  setting is unchanged.

Pan schemes compared (gain steps of about 0.24 dB; L − R = left minus right):

| Setting | EOS 4.70 | EOS 4.71-beta (beta1) | EOS 4.71-beta2 |
|---|---|---|---|
| Hard left | at −32 (CC10 32); −33…−64 do nothing | at −64 (CC10 0) | at −64 (CC10 0) |
| −32 (CC10 32) | hard left | about 16 dB left | about 16 dB left |
| −1 (CC10 63) | 2 steps left-heavy | 1 step left-heavy | **balanced** |
| 0 (CC10 64) | 1 step right-heavy (−0.24 dB) | 1 step right-heavy (−0.24 dB) | **balanced (0 dB)** |
| +32 (CC10 96) | hard right | about 16 dB right | about 16 dB right |
| Hard right | at +32 (CC10 96); +33…+63 do nothing | at +63 (CC10 127) | at +63 (CC10 127) |
| Pan gain table entries 63 / 64 | −322 / −311 | −322 / −311 | −316 / −316 |

Verified in the emulator, running the real pan routine for every pan and level against stock, and on the E4
(Quantum 19/20, preset 000 sine).

| Measured L − R on the E4 | Voice Pan | CC10 |
|---|---|---|
| Centre | 0.00 dB at −1 and 0 (beta1: −0.24 dB at 0) | 0.00 dB at 63 and 64 |
| One step either side | +0.77 dB at −2, −0.79 dB at +1 | −0.78 dB at 65 |

### Renamed: SLpScn → WTScan
- The transwave/wavetable scan cord destination **SLpScn** is now called **WTScan**. Only the name has changed;
  beta1 presets play unchanged.

---

## EOS 4.71-beta

EOS 4.71-beta is an unofficial update of E-mu's EOS 4.70 for the Emulator IV family **Ultra** models
(ColdFire MCF5206e), built by patching the original 4.70 image. It is not made, supported or endorsed by
E-mu Systems / Creative. Header name **EOS 4.71-beta**, image checksum `0887f4e6`.

Everything below was verified in an instruction-level emulator (stock vs patched code paths) and on an
E-mu E4 Ultra with an RFX card, with measurements recorded from its outputs.

## New

### Filters: Oberheim OB-Xa (CEM3320) models
- **2 Pole Lowpass, 4 Pole Lowpass, 6 Pole Lowpass** now model the OB-Xa filters built on the CEM3320:
  the 2-pole is the state-variable filter, the 4-pole the transistor-style ladder, the 6-pole the ladder
  followed by the 2-pole on the same cutoff. Names, menu positions and preset compatibility are unchanged.
- The cutoff now follows the displayed frequency at high resonance (stock drifted up to ~25 % sharp at
  the bottom of the range). Resonance peaks are matched to the stock maxima (about 19 / 39 / 46 dB), so
  E-mu's level compensation still fits and existing presets keep their balance.
- **2nd Order High-pass, 4th Order High-pass, 2nd Order Band-pass, 4th Order Band-pass** use the same
  OB-Xa pole pairs; their cutoff/centre follows the display (stock HP corners sat 25–60 % below it).
  Band-pass levels match stock within ~2 dB at low and medium resonance; the 4th-order band-pass has a
  ~+15 dB resonant peak at full resonance.
- **Contrary Band-pass** keeps its stock character (the zero that moves against the cutoff and the stock
  resonance law) with the centre frequency calibrated to the display.
- Not modelled: analog saturation and self-oscillation (the E4's filter hardware is linear).

### LFO tempo sync
- **LFO 1 and LFO 2 Rate** continue past 18.01 Hz into 16 tempo divisions:
  `4bars, 2bars, 1bar, 1/2., 1/2, 1/4., 1/2T, 1/4, 1/8., 1/4T, 1/8, 1/16., 1/8T, 1/16, 1/16T, 1/32`
  (values 128–143 over MIDI/SysEx).
- The tempo comes from the master clock: the internal sequencer/arpeggiator tempo, or incoming MIDI
  clock when the Clock Source is External (phase-locked to MIDI Start).
- **Sync = Key Sync** restarts the cycle at note-on; **Sync = Free Run** locks all voices to the song grid.
- In sync mode the Rate cords, Variation and LFO trigger are ignored; Shape, Delay and all destinations work.
- Measured accuracy: within ±0.06 % of the MIDI clock at 60–140 BPM; Free Run phase spread 0.2°.

### New LFO shape: "saw down"
- Shape 16, a falling sawtooth (shape 2 "sawtooth" rises).

### Transwave / wavetable scanning: cord destination "SLpScn"
- New cord destination **SLpScn** slides a sample's loop window through the sample while the note plays
  (Ensoniq-style transwave). +100 from a full-scale source moves the loop from frame 1 to the sample end,
  −100 towards the start; the loop always stays inside the sample. See `docs/transwave-guide.md` for how to
  build samples: **at least 2 samples of silence before the first frame** (a loop cannot start
  before sample 2), equal frames, frames × frame size ≤ 32,768.

### MIDI clock: keeps running when the clock stops ("flywheel")
- With Clock Source External, **synced LFOs, the Ck clock modulation sources (CkDwhl … Ck16th), the
  arpeggiator and Beats keep running at the last MIDI tempo when the MIDI clock stops** (DAW stopped),
  instead of freezing. The song sequencer still stops with the DAW.
- On Continue, synced LFOs snap back onto the DAW's grid; MIDI Start resets them to bar 1.
- Short dropouts (missing clocks under 250 ms) are caught up so the LFOs stay on the grid.

## Fixed

### Pan reached hard left/right at half range (EOS 4.70 bug)
- **Voice Pan, Multimode (mixer) Pan, MIDI CC10 and AmpPan cords** now use their full range. In 4.70 the
  pan sum was scaled twice too large, so ±32 (CC10 32/96) was already hard left/right and the outer half of
  every pan control did nothing. Now ±64 (CC10 0/127) is hard, ±32 is about 16 dB between the sides.
- Verified on the main outputs and the sub outputs 1–3. (A 0.25 dB right-heavy centre offset from E-mu's
  pan table remains; fixed in beta2, see above.)
- Test it yourself with the **EOS Pan Test** app and the bank in `testbank/` (see README).

### MIDI clock counted twice
- With Clock Source External, the master clock advanced on the incoming MIDI clock **and** on EOS's own
  internal clock stream, so the sequencer, arpeggiator and Ck sources ran at internal + external tempo
  (60 BPM MIDI clock played like 180 BPM). Only clocks from the MIDI inputs are counted now.

### Clock sources frozen after power-on
- After power-on the master clock rate stayed 0 until the arpeggiator/sequencer tempo was edited, so the
  Ck sources (and anything else on the master clock) did not move. The clock now starts at the arpeggiator
  tempo on the first note.

## Faster
- **Cord processing**: each voice's 10 ms control tick tested all 24 cord slots; it now stops after the last
  cord in use (results identical). On a 64-voice test preset: cord stage −29 %, whole voice tick −6.7 %,
  CPU used by voice control 64 % → 60 %. Confirmed sound-identical by an in-session A/B null test.

## Known limitations
- MIDI Song Position Pointer is not followed by the synced LFOs (Continue resumes from the stop point).
- While the MIDI clock is stopped the flywheel runs within about 0.2 % (LFOs) / 2 % (Ck sources) of the last tempo.
- Ultra models only (as EOS 4.70). Back up your work before flashing; to go back, flash the original 4.70.
