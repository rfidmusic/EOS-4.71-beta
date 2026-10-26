# Original E-mu filters back, OB-Xa models as new types (test build, 2026-10-24)

**Build:** `tools/build_origfilt.py build/eos471_beta.bin build/eos471_origfilt.bin`, giving "EOS 4.71-b2 OrigFilt T",
checksum 0885a54f, `sysex/EOS471-b2-origfilt-T.syx`. Base: build 2 with `--origfilt`, plus the disk-unit
compaction (notes/compaction.md). Not released; not committed.

## Menu (31 entries)

| Menu | Filters | Type IDs |
|---|---|---|
| 0–20 | The 21 E-mu filters of 4.70, with stock code, order and type IDs | stock |
| 21–28 | OB-Xa 2 Pole LP, 4 Pole LP, 6 Pole LP, 2nd Ord HP, 4th Ord HP, 2nd Ord BP, 4th Ord BP, Contrary BP | 0x04, 0x05, 0x06, 0x0A, 0x0B, 0x13, 0x14, 0x15 |
| 29 | 4 Pole LP+Fuzz | 0x03 |
| 30 | Default | 0x7F |

**Presets:**
- **Made on 4.70:** the E-mu filters again.
- **Made on beta1 / beta2 with the OB-Xa models:** they stored type IDs 0x00–0x12, so they now play the E-mu filters.
  Re-select the OB-Xa entry to get the OB-Xa sound back.

## How

| Piece | Where | Size |
|---|---|---|
| Stock code beta1 overwrote, LP group (the 0x65E18 helper and the 2/4/6-pole computeFrames/packQ; three `bsr.w` refitted) | .blkPM tail, 0x15F594 | 644 bytes |
| Stock code, HP/BP group (all calls absolute) | 0x7FB84 | 1,470 bytes |
| Stock table 0x6875C | 0x7FB44 | 64 bytes |
| OB-Xa vtables (the ctor list reaches 0x60000–0x7FFFE) | 0x7F9E4 | 8 × 44 bytes |

- **E-mu vtables:** back to their stock slots, pointing at the copies. The LP type/name methods are beta2's identical
  stubs.
- **Ctor:** the list holds (vtable − 0x60000) / 2 for 31 entries. The manager is 0x280 bytes with the count at 0x27C,
  the filter-type descriptor maxima are 29, and .slT moves to .blkPM.
- **Names and small methods:** in holes left by folding nine duplicate strings. Each dropped copy's only references are
  verified `pea.l` operands. 49 bytes are left over.

## Verified (emulator, `tools/emu_origfilt.py`)
- **E-mu filters against 4.70:** 20,672 calls, 0 failures. The calls cover type, name, computeFrames (modes 0/3,
  q 0–255, two block fills, two base gains), packQ, formatParam and the other slots.
- **OB-Xa entries against build 2:** 20,672 calls, 0 failures. Type and name are the new ones.
- **Registry:** 31 entries in the order above, the type table, and type ↔ menu round-trips.
- **LP+Fuzz against build 2:** 2,584 calls, 0 failures.
- **Planted bugs:** all caught (a flipped code bit, a table byte, a name character).
- **Other suites:** Slice, slicer, port map, slew, pan, the unit compaction and Insert Silence pass. emu_silence's
  diff whitelist flags the intended new changes.
