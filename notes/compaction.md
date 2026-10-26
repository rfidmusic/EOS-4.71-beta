# Compacting stock EOS 4.70 code for space (survey 2026-10-24)

Goal: contiguous free space for new code, such as the original filters (all eight about 4 KB; the three low-pass
about 970 bytes). Free now: 662 bytes at 0x15F582. There is no flash above the OS (notes/resident_flash.md), and no
zero/0xFF run is free.

## Candidates, best first

### 1. Disk unit table: 90 identical records, about 1,958 bytes contiguous
- **What it is:** 0x7F9CE–0x8018A in flash, 90 records of 22 bytes, all identical: `0000` followed by pointers
  0x7F89C, 0x7F8A8, 0x7F8B4, 0x7F8B8, 0x7F898.
- **How it is read:** `base + 22 × unit` (unit from `$14` of the device struct). The surrounding code handles
  512-byte sectors and the 0x55AA boot signature: a per-unit disk driver table.
- **The idea:** zero the offset at each indexing site (the multiply), so every unit reads record 0 (identical
  bytes). Records 1–89 then become free.
- **Indexing sites so far** (`movea.l #$7F9CE/$7F9D8/$7F9DC`):

| Site | How it multiplies |
|---|---|
| 0x80C72 | `lsl #2` then `muls.l d1,d0` at 0x80C90 |
| 0x85246 | `muls.l -$c(a6),d0` at 0x85264, then `$e(a3,d0.l)` |
| 0x86098 | `muls.w #$16,d0` at 0x860B4 |
| 0x8AEDE, 0x84E58, 0x84F28, 0x85394 | `muls.l d1,d0` |

- **Still to prove:** no other readers. Several (d16,PC) hits point into the array (from 0x781C4, 0x7AF8E, 0x7BB46,
  0x7BB62, 0x7B596, 0x7D1E0, 0x7D6EC, 0x7D70E, 0x7D736, 0x7868A) and need checking; they may be false positives
  from data. Then run each site in the emulator against stock for every unit 0–89.
- **Risk:** low if every reader is patched, since the content is identical. Out-of-range units would read record 0
  instead of the code that follows the array, which was a stock bug path anyway.

### 2. Duplicate strings: about 5 KB, scattered
- **What it is:** 335 groups of identical, referenced strings, such as "Cancel" ×4, "Can't Allocate ObjMgr!" ×3,
  "Empty Sequence" ×4 and "Enter preset name:" ×3. Folding copies and repointing absolute references frees about
  5.1 KB.
- **Limit:** the freed holes are 5–40 bytes each, where the copies were. That is only useful for small pieces, so it
  is no help for a 1–4 KB block.
- **Risk:** each repointed reference must be a real instruction operand, not a data word that happens to match.

### 3. RIFX parser 0x15C33C: about 430 bytes, inside one function
- **What it is:** the parser builds each 4-character tag one byte at a time (`move.b`/`extb`/`lsl`/`or`, about
  36 bytes), 13 times. A single long read gives the same value for ASCII tags.
- **Limit:** the space is spread through the function unless the function is rebuilt and moved. It is RFX code (the
  plugin images it parses stay untouched).

### Not candidates
- **0x5A834:** parameter descriptor tables.
- **0x14353C:** the PC-keyboard key table.
- **0x161584:** record tables.
- **Unreferenced functions:** a naive scan flags 1,238, but it includes live code (notes/optimization.md).

## Candidate 1: proved in the emulator (2026-10-24, not flashed)

**References.** Of 697 raw hits into 0x7F9CE–0x8018A, only 21 are real: `movea.l #imm` loads of five addresses.

| Address | Meaning | Sites |
|---|---|---|
| 0x7F9CE | table A | 4 |
| 0x7F9D8 | table A +10 | 1 |
| 0x7F9DC | table A +14 | 10 |
| 0x7FDAC | table B, which starts at record 45 | 2 |
| 0x7FDBA | table B +14 | 4 |

So there are two tables of 45 identical records. The other hits are false positives:
- pairs of 16-bit displacements read as one long (`$8(a6),$10(a5)` gives 0x00080010);
- `btst`/`bclr #7,-x(a6)` encodings;
- `beq.b` opcodes caught by the (d16,PC) scan;
- three bitmap words at 0x3A9EA, 0x3AE68 and 0x3E5B8 (pixel-art graphics).

**Sites.** Every site does `movea.l #table,aN`, then `muls` (unit × 22), then `adda.l d0,aN` or a `d(aN,d0.l)` load,
and after that only `movea.l d(aN),a0; jsr (a0)`.

**Patch** (`tools/unitcompact.py`):
- the 19 `adda.l d0,aN` become `nop`;
- the two indexed loads become `d(aN)` (0x85270 `$e(a3)`, 0x8740A `$2(a4)`);
- table B's two addresses are repointed to table A.

d0 and the condition codes are unchanged from stock. 54 bytes change, all at the sites. 0x7F9E4–0x8018A
(**1,958 bytes**) is freed. The stock checks cover all 90 records, every site's `movea` operand and every patched
instruction. It applies unchanged to 4.70 and to 4.71-beta2 build 2.

**Test** (`tools/emu_unitcompact.py STOCK.bin`):
- **Method:** the freed block is filled with 0xA5. For each site, each unit 0–44 (forced at the `muls`) and two
  random machine states, the site's real code runs in both images. Every call is stepped over and its target and
  data registers recorded.
- **Result:** 1,890 runs, 0 failures, on stock 4.70 and on build 2.
- **Planted bug** (one `adda` left in place): 88 failures, which is units 1–44 × 2 states, the call landing in the
  0xA5 fill.

**Hardware, first test (2026-10-24): saving to SCSI froze.**
- **Image:** "EOS 4.71-b2 UnitTest" (08889587).
- **Worked:** boot, load, directory and floppy.
- **Cause:** two table reads were missed. The function at 0x85246 reads `$e(a3,d0.l)` a second time at 0x852B2. The
  function at 0x873E2 reads `$e(a4,d0.l)` at 0x87772 with the offset saved in -8(a6), on a branch (0x8770E) that
  skips a4's reassignment.
- **Why they were missed:** the site scan was linear and stopped at the first reassignment. The emulator test
  returned 0 from every stepped-over call, so the success paths never ran. With a SCSI unit other than 0, the save
  path jumped into the 0xA5 fill. The floppy is unit 0.

**Fix:**
- **Patch:** 0x852B2 and 0x87772 are patched too (23 instructions at 21 sites).
- **Check:** `unitcompact.indexed_uses` now walks every branch path from each site until the register is reassigned.
  It finds exactly these 23 uses, and `apply()` refuses an image with any left.
- **Emulator test:** skipped calls now return 0, 1 or -1, the unit is forced at every table multiply, and six machine
  states are used. 17,010 runs, 0 failures. Removing either new fix gives failures: 352 for 0x852B2, 2 for 0x87772.
  0x87772 is on a rare path, so the walk is the main guard.
- **Test image:** "EOS 4.71-b2 UnitTest2" (checksum 08889579, `sysex/EOS471-beta2-b2-unittest2.syx`). It is build 2
  plus this compaction, with the freed block filled with 0xA5.

**Hardware, second test (2026-10-24): passed.** On UnitTest2 (08889579), with the freed block still filled with
0xA5, the user tested boot, SCSI save, load, directory and floppy. All worked. Not separately exercised: the FLASH
Disk / Resident FLASH paths.

The 1,958 bytes are not used by anything yet.

## Release gate: drive tests on UnitTest2 (freed block filled with 0xA5)

Use backed-up or scratch media. Any missed table reader jumps into the fill and freezes, so a freeze is a fail.

| # | Test | Passed? |
|---|---|---|
| 1 | SCSI ID 0, partition 0: load bank, save bank, directory, delete, rename | OK (save, load, directory) |
| 2 | Another SCSI ID (for example 2 or 5): the same as test 1 | OK (2026-10-24, user: "all SCSI IDs work"; one drive, ID changed) |
| 3 | A partitioned drive: load and save on partitions 2–4 (units ID×4 + 1…3) | OK |
| 4 | Two drives at once: copy a bank or sample between them | Not possible on this E4 |
| 5 | Floppy: load, save, format, boot from floppy | Load and save OK; format and boot not done (no floppy disk to hand) |
| 6 | CD-ROM (if available): mount, directory, load a bank | OK (2026-10-24) |
| 7 | Zip / removable SCSI (if available): load, save, swap the disk while EOS runs | Not reported |
| 8 | IDE drive (if fitted): mount, load, save | Not reported |
| 9 | Format a SCSI disk or partition (scratch only) | OK (2026-10-24, user: "format works") |
| 10 | Disk Utilities: check or repair, mount/rescan drives, change the current drive | OK |
| 11 | Resident FLASH / FLASH Disk: copy RAM to Resident, load from Resident, compact | Not applicable on this E4: RAM->F says "Flash Heap Full" even with < 1 MB of samples. RAM->F copies samples to flash sample numbers (1000+), which need Sound FLASH, and the About screen shows no Sounds key (no Sound FLASH/ROM fitted). This path does not use the unit tables |
| 12 | Power-on with drives attached: "Mounting SCSI drive" for every ID present; and with no drives | OK |
| 13 | Error paths: save to a write-protected floppy, load with no disk, unplug a drive before access | OK |

**Pass:** every row works as on build 2 (0886960e), with no freeze. Only then can the compaction go into a release.
