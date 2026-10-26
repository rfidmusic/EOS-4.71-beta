# Disk unit dispatch tables in EOS 4.70 (decoded 2026-10-24)

The tables that `tools/unitcompact.py` folds (notes/compaction.md, candidate 1).

## Units
- **Range:** a unit is 0–44 (`0x8018C` rejects unit ≥ 45).
- **Meaning:** SCSI ID = unit ÷ 4 and partition = unit mod 4 (`0x801FC`, `0x8018C`), so IDs 0–11, with only
  partition 0 of ID 11.
- **ID 11 (0x0B) is the floppy drive.** The block driver sends it to `0x41B30`, in the floppy module next to "No
  Floppy Disk", "Disk Write Protected", "Floppy CRC Error" and the other floppy errors. IDs 0–10 are SCSI. The same
  module also mounts IDE drives ("Mounting IDE drive: %1d", "Mounting SCSI drive: %1d").
- **Per-ID state in RAM:** 0x8A bytes per ID at `0x1030CE5C`. +0x22 is "present"; +0x2E + 0x18 × partition is the
  partition's start LBA (`0x8018C` returns it, −1 if absent).
- **Drive letters:** `0x80214` turns a letter into a unit, (letter − 'A') ÷ 4.

## The tables
- **Layout:** table A at `0x7F9CE` and table B at `0x7FDAC`, 45 records each of 22 bytes, all identical. Each
  record is `0000` followed by five function pointers:

| Field | Function | What it does |
|---|---|---|
| +2 | `0x7F89C` | Clears the flag `0x102BFF44`, returns 1 (OK) |
| +6 | `0x7F8A8` | Sets the flag `0x102BFF44`, returns 1 |
| +10 | `0x7F8B4` | Returns 1 (always OK) |
| +14 | `0x7F8B8` | The block read/write driver, described below |
| +18 | `0x7F898` | Returns 0 |

- **The block driver `0x7F8B8(unit, lba, buffer, count, write)`:**
  1. Unless the flag `0x102BFF44` is set, it adds the partition start (`0x8018C(unit)`) to the LBA.
  2. It maps unit → ID (`0x801FC`).
  3. ID 11 goes to the floppy driver `0x41B30`, inside the lock `0x7CE74` / `0x7CE7C`.
  4. Any other ID: select the target (`0x113014`), then SCSI read (`0x1133B8`, CDB 0x08/0x28 via `0x110010`) or write (`0x113470`, CDB 0x0A/0x2A via `0x110050`;
     corrected 2026-10-25, the two were swapped here before).
  5. It returns 1 on success.
  6. Errors are reported through `0x7F878` with the message table at `0x84238`.

## Why the tables can be folded
- **One driver for everything:** every record holds the same five pointers, so every unit reaches the same generic
  driver.
- **The drive comes from the argument:** the drive actually used is the **unit argument** the caller pushes (for
  example `move.l d5,-(a7)` from `$a(a6)` before `jsr (a0)`), never the record's position.
- **The record pointer is only used to fetch:** on every path from the 21 table loads, the table register is used
  only to fetch a field (35 fetches), or is copied for a fetch (`movea.l a3,a4` at 0x86312 / 0x863B2, followed by
  `$e(a4)`). The indexed reads that the compaction rewrites are the only other use. It is never passed, compared or
  written.
- **So nothing about which drive is accessed changes:** reading every unit's pointers from record 0 gives the same
  five addresses, and the unit argument still selects the drive.

## Callers (E-mu disk filesystem layer)

| Function | What it is |
|---|---|
| `0x80948` | Reads the "E-MU SYS" volume header |
| `0x85D28` | Checks the 0x55AA partition signature |
| `0x84CF0`, `0x84FD0`, `0x87358`, `0x893AC`, `0x89DF8`–`0x8B5F8` | Block, directory and allocation routines that call the driver for a unit |
| `0x80578`, `0x80720` | Use table B |
