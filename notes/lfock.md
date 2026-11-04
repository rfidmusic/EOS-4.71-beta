# Lfo1Ck / Lfo2Ck on build 3

The cord behaviour is the one hardware-tested on the released beta2 (`0886a24c`, flashed image `088667ba`). This note is only where that code sits on build 3.

Build 3 leaves 41 bytes in its tracked holes, and the port-map tail is the restored E-mu low-pass. The cord body is 750 bytes and stays one piece.

RFX Chorus and RFX UltraChorus contain the same 992-byte coefficient table and `%d-%d msec` string. UltraChorus addresses its copy with four `movea.l #imm` / `lea pc@(imm)` stubs, at `0x1D7730`, `0x1D7AE2`, `0x1D7B8C` and `0x1D8B16`. Subtracting `0x2E20` from each immediate points them at Chorus's copy. Nothing else refers to UltraChorus's copy. The `rts` at `0x1D8C18` is the end of a live function and stays. The 988 bytes at `0x1D8C1C` take the cord, then `id_swap` and `rev_id`.

The list walkers are more than 32 KB away from that hole. `0x62D22` and `0x62D86` `bsr.w` to `jmp id_swap` at `0x66B24`. `0x62CA0` `bsr.w` to `jmp rev_id` at `0x66B2A`. The `moveq #$40; rts` stub at `0x66B38` stays, and so does the pointer at `0x68A68`.

The other hooks are the ones the beta2 image used: `0x61BF4` jumps to `cord_tick`, `0x5F7E0` calls `lfo_bind`, `0xCDAC2` calls `rate_enter`, `0xCDB8C` calls `rate_built`, and the two Rate setters call `rate_set`. Names `Lfo1Ck` / `Lfo2Ck` are at `0x201AE`. Destinations 98 and 107 were the empty offset `0x1E`.

`tools/build_lfock.py` writes the image. The startup name is `EOS 4.71-beta2 b3+LfoCk`, checksum `0885e5b5`. A build without the cord is build 3 itself, name `EOS 4.71-beta2 build 3`, checksum `08859e24`. The flasher patch is `apps/eos-core/data/eos471b3lfock.e4p`.

UltraChorus is the effect whose table moved. Chorus is unchanged. A missed reader would show up as UltraChorus losing its shared curve or its `%d-%d msec` text, not as a cord failure.
