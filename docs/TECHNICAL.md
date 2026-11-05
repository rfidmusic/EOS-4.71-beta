# EOS 4.70 / 4.71-beta / 4.71-beta2: technical reference

## Layout (local workspace)
Not in the public repository (E-mu material or local data): `bin/`, `build/`, `ghidra/`, `notes/*.c`,
`recordings/`, built `.syx` files. Recreate `bin/eos470_flash_0x20000.bin` from your own EOS470.EXE
(`apps/eos-core/examples/check.rs` or `tools/eos_lz.py unpack`, floppy image at offset 5,668 of the EXE).

- `bin/eos470_flash_0x20000.bin` – decompressed OS image (0x1DFE80 bytes), loads at 0x00020000
- `ghidra/EOS470.gpr` – Ghidra project (language `68000:BE:32:Coldfire`), analysed, 8,481 functions
- `ghidra/*.tsv` – exported function list, string→function xrefs, peripheral access counts
- `ghidra_scripts/EosSetup.java` – memory map, vector table, MCF5206e register labels (pre-analysis)
- `ghidra_scripts/EosReport.java` – report exporter (post-analysis)
- `tools/eos_lz.py` – floppy codec: `unpack`, `fixsum`, `pack` (round trip verified bit-exact)
- `tools/cfdis.py` – quick capstone disassembler
- `tools/eos_midi.py` – MIDI File Dump OS download: build/check/send .syx (see `sysex/README.md`)
- `sysex/README.md` – flashing instructions and the Transwave sample guide
- `tools/eos_filter.py` – voice-filter coefficient model + response plots (`notes/filter_format.md`)
- `notes/*.md` – design notes, measurements and findings for every change
- `patches/*/` – assembler sources of all patches; `tools/build_*.py` – builders; `tools/emu_*.py` – emulator tests
- `.venv` – Python env (numpy, matplotlib, capstone, unicorn): `python3 -m venv .venv && .venv/bin/pip install numpy matplotlib capstone unicorn`
- `tools/ghidra_headless.sh` – analyzeHeadless with Homebrew JDK 21

## Floppy / flash image format
Header (0x200 bytes), all big-endian:

| off  | field |
|------|-------|
| 0x00 | magic `0x76543210` (raw) / `0x76543211` (Lz77-compressed floppy) |
| 0x04 | checksum = byte-sum of the first `len` bytes of the *raw* image, header included |
| 0x08 | ~checksum (so the checksum field's own bytes always sum to 4×255) |
| 0x0C | entry point (0x00020602) |
| 0x10 | length (raw image length; on floppy = compressed stream length) |
| 0x18 | name string `"EOS v4.70"` |

The compressed stream starts at floppy offset 0x200. Codec (from boot loader PL01 01f05, routine 0x18BE8):
MSB-first bits; `0`+8-bit literal, or `1`+8-bit distance+8-bit length; distance 0 ends the stream.
256-byte ring. If length > distance, the loader repeats the single byte at `distance` back (RLE),
so the encoder only uses overlapping copies for 1-byte runs.

The boot loader decompresses while reading the disk, verifies the checksum in RAM at 0x10200000,
writes the raw image to flash at 0x20000, then jumps to header+0x0C.

## Hardware (from reset code at 0x20602)
- CPU **Motorola MCF5206e** (ColdFire V2): MBAR=0x20000000, RAMBAR=0x107FE000 (8 KB SRAM)
- VBR=0x10000000, SSP=0x10800000 → 8 MB OS DRAM at 0x10000000
- CS0 flash at 0 (boot loader 0x0–0x1FFFF, EOS from 0x20000)
- Other chip selects: 0x02000000, 0x03000000 (most-used I/O, ~865 refs), 0x04000000,
  0x05000000, 0x06000000, 0x08000000 (0x08000800 heavily used)

## Patch workflow
```
python3 tools/eos_lz.py fixsum patched.bin patched.bin
python3 tools/eos_lz.py pack   patched.bin EOS_PATCHED.img
```
Repacking EOS 4.70 unchanged leaves ~96 KB free on a 1.44 MB disk.

## Building EOS 4.71-beta2 from source
Starting from the EOS 4.71-beta image (`build/eos471_beta.bin`, made from the stock 4.70 image in your EOS470.EXE):
```
python3 tools/build_beta2.py build/eos471_beta.bin build/eos471_beta2.bin   # also writes .syms.json
python3 tools/make_patch.py STOCK_4.70.bin build/eos471_beta2.bin apps/eos-core/data/eos471beta2.e4p
```
`build_beta2.py` checks every stock byte it replaces before patching. Its emulator suites, each run against stock:
`emu_lpfuzz_rel`, `emu_silence`, `emu_slice`, `emu_slew`, `emu_sloop`, `emu_portmap`, `emu_slicer` and `emu_pan`.
Design notes: `notes/lpfuzz.md`, `silence_insert.md`, `slice_design.md`, `slicer_design.md` and `pan_bug.md`.

Build 3 plus Lfo1Ck / Lfo2Ck is a separate image. `tools/build_lfock.py` starts from build 3 and writes the
startup name `EOS 4.71-beta2 b3+LfoCk` (checksum `0885e5b5`). `tools/emu_lfock.py` and `tools/emu_listorder.py`
test it. Design note: `notes/lfock.md`.
