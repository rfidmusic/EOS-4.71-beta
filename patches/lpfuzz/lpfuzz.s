| EOS 4.71: interpolated resonance steps + "4 Pole LP+Fuzz" filter (test build, "EOS 4.71 LPFuzz T").
|
| Space: the filter registry constructor 0x67F98 is rewritten as a loop over a vtable list (words + 0x60000)
| and jumps into the stock tail 0x683F0; everything below lives in the freed bytes up to 0x683F0.
| The menu list grows to 23 filters: the builder moves the count from manager + 0x258 to + 0x25C (ctor tail,
| FUN_00068458, FUN_000684A0) and the allocation from 0x25C to 0x260; both filter-type descriptors go 20 -> 21.
|
| 1. Resonance interpolation. The OB-Xa pole tables are indexed with Q >> 2 (32 steps) or Q >> 3 (16 steps,
|    LADB and the HP/BP B tables). lerp() blends each byte (X, F of both frames) between entry i and i + 1 by
|    the remaining Q bits: v = a + (((b - a) * f) >> shift), so Q values that are multiples of 4 / 8 give the
|    table entries exactly. Hooks: OB-Xa LP words (0x65E5A, jmp words_i) and HP/BP/Contrary BP apply's table
|    part (0x6684E, jmp apply_i). Switch bit 0 off: f = 0, i.e. the stock 4.71 tables.
|
| 2. "4 Pole LP+Fuzz" v5 (type 0x03). With the zero stages active (SETMODE 0x80, written to the previous block) a
|    pole word and its zero word act as one section poly_zero / poly_pole, without the pole's w0^2 normalisation; v4
|    (fixed zeros) therefore always had an overload peak at the pole frequency, even at Q 0. v5 makes section 0/1
|    transparent at Q 0 (zero word = the ladder pole word, poly / poly = 1) and moves the zero toward X 0xFF /
|    F 0xE0 as Q rises, so Q dials the peak and passband boost in. Q labelled "Fuzz":
|    - words 0/4: the OB-Xa 4-pole ladder at Q/2 (LP4 computeFrames/packQ); low-frame F capped 0xDF, high-frame F
|      capped 0xDF (bit 4: 0x90);
|    - word 1 (bit 1): zero = word 0 + (0xFFE0FFE0 - word 0) * Q / 127 per byte; SETMODE(blk, mode, 0xC0) on
|      computeFrames. Bit 1 off: word 1 neutral, no SETMODE (the plain ladder at Q/2);
|    - word 5: neutral, or (bit 2) a copy of word 4 (section 4/5 transparent);
|    - word 8: neutral, or (bit 3) a copy of word 4 (a normal, unity-gain pole pair: no zero partner);
|    - word 9: the LP4 gain (base - GOFF[Q >> 4]).
| Release build (assembled with --defsym RELEASE=1): the switch reads become the constant RELSW = 15 (interpolation
| on, moving zero, word 5 = word 4, word 8 pole, high-frame cap 0xDF) and the parameter-195 handlers are left out.
| Test build: switch SW = parameter 195 (0..31; RAM vector slot 249, zero at boot).

        .equ    SETMODE,   0x10D3B0
        .equ    MALLOC,    0x2AFDC
        .equ    CTOR_TAIL, 0x683F0
        .equ    CTOR_EXIT, 0x68420
        .ifdef  ORIGFILT
        .equ    COUNT,     0x27C              | 31-entry menu list (originals + 8 OB-Xa + LP+Fuzz + default)
        .else
        .equ    COUNT,     0x25C
        .endif
        .equ    SVF,       0x65FB0            | OB-Xa SVF[32], LADA[32] follows at +128
        .equ    LADB16,    0x6875C
        .equ    LP4_CF,    0x65E40
        .equ    LP4_PQ,    0x65E4E
        .equ    LP_FMT,    0x65D24
        .equ    STRCPY,    0x1A6C4C
        .equ    SPRINTF,   0x1A6EA0
        .equ    FMT_D,     0x68CB0            | "%d"
        .equ    SW,        0x100003E4
        .equ    NEUTRAL,   0xFFCFFFCF
        .equ    GAINBASE,  0x10004D7C
        .equ    GOFF,      0x6871C
        .ifdef  NFZ
        .equ    NVT,       22 + NFZ           | 21 E-mu filters, NFZ Fuzz filters, the default
        .else
        .ifdef  ORIGFILT
        .equ    NVT,       31
        .else
        .equ    NVT,       23
        .endif
        .endif

        .equ    RELSW,     15

| LDSW reg: the switch value (test build) or the frozen release value
        .macro  LDSW reg
        .ifdef  RELEASE
        moveq   #RELSW,\reg
        .else
        move.l  SW,\reg
        .endif
        .endm

        .section .ctor,"ax"
        .globl  _start
_start:
ctor:   lea     -16(%sp),%sp
        movem.l %d7/%a3-%a5,(%sp)
        movea.l 20(%sp),%a3
        move.l  %a3,%d0
        bne.s   1f
        jmp     CTOR_EXIT                    | d0 = 0
1:      clr.l   COUNT(%a3)
        moveq   #0,%d7
2:      pea     4.w
        jsr     MALLOC
        addq.l  #4,%sp
        movea.l %d0,%a5
        tst.l   %d0
        beq.s   3f
        lea     vtlist(%pc),%a0
        moveq   #0,%d0
        move.w  (%a0,%d7.l*2),%d0
        .ifdef  ORIGFILT
        add.l   %d0,%d0                      | entries are (vtable - 0x60000) / 2: reach 0x60000..0x7FFFE
        .endif
        addi.l  #0x60000,%d0
        move.l  %d0,(%a5)
3:      move.l  COUNT(%a3),%d0
        lea     (%a3,%d0.l*4),%a0
        move.l  %a5,0x200(%a0)
        addq.l  #1,%d0
        move.l  %d0,COUNT(%a3)
        addq.l  #1,%d7
        moveq   #NVT,%d1
        cmp.l   %d1,%d7
        blt.s   2b
        movea.l %a5,%a4                      | last object (the 0x7F default)
        movea.l %a3,%a5
        jmp     CTOR_TAIL                    | d0 = count

        .align  2
        .ifdef  NFZ
| (vtable - 0x60000) / 2: the 21 E-mu filters (stock code, build_fuzz.py), then NFZ Fuzz filters (filled in by
| build_fuzz.py), the default. LP+Fuzz below is not listed (its code is unused in this build).
vtlist: .word   0x8878/2,0x88A4/2,0x88D0/2,0x88FC/2,0x8928/2,0x89D8/2,0x8A04/2,0x8A30/2,0x8954/2,0x8980/2
        .word   0x89AC/2,0x8A5C/2,0x8A88/2,0x8AB4/2,0x8AE0/2,0x8B0C/2,0x8B38/2,0x87DC/2,0x8B64/2,0x8B94/2
        .word   0x8BC4/2
        .rept   NFZ
        .word   0                            | a Fuzz filter
        .endr
        .word   0x884C/2                     | default (type 0x7F) stays last
        .else
        .ifdef  ORIGFILT
| (vtable - 0x60000) / 2. The 21 E-mu filters (the first eight back to the original E-mu code, build_origfilt.py),
| then the eight OB-Xa models (filled in by build_origfilt.py), LP+Fuzz (build_lpfuzz.py), the default.
vtlist: .word   0x8878/2,0x88A4/2,0x88D0/2,0x88FC/2,0x8928/2,0x89D8/2,0x8A04/2,0x8A30/2,0x8954/2,0x8980/2
        .word   0x89AC/2,0x8A5C/2,0x8A88/2,0x8AB4/2,0x8AE0/2,0x8B0C/2,0x8B38/2,0x87DC/2,0x8B64/2,0x8B94/2
        .word   0x8BC4/2
        .word   0,0,0,0,0,0,0,0              | OB-Xa 2/4/6 Pole LP, HP2, HP4, BP2, BP4, Contrary BP
        .word   0                            | LP+Fuzz
        .word   0x884C/2                     | default (type 0x7F) stays last
        .else
vtlist: .word   0x8878,0x88A4,0x88D0,0x88FC,0x8928,0x89D8,0x8A04,0x8A30,0x8954,0x8980      | + 0x60000
        .word   0x89AC,0x8A5C,0x8A88,0x8AB4,0x8AE0,0x8B0C,0x8B38,0x87DC,0x8B64,0x8B94
        .word   0x8BC4
        .word   0                            | lpf_vt - 0x60000 (filled in by the builder)
        .word   0x884C                       | default (type 0x7F) stays last
        .endif
        .endif

        .ifndef RELEASE
| ---- parameter 195: getter(desc) / setter(desc, v) ----
sw_get: move.l  SW,%d0
        rts
sw_set: move.l  8(%sp),%d0
        bpl.s   1f
        moveq   #0,%d0
1:      moveq   #31,%d1
        and.l   %d1,%d0
        move.l  %d0,SW
        rts

        .endif

| ---- lerp: a0 = table, d0 = q (0..127), d1 = shift, d2 = last index. Out d0; clobbers d1, d2 only. ----
lerp:   lea     -24(%sp),%sp
        movem.l %d3-%d7/%a1,(%sp)
        move.l  %d0,%d3
        lsr.l   %d1,%d3                      | i
        moveq   #1,%d4
        lsl.l   %d1,%d4
        subq.l  #1,%d4
        and.l   %d0,%d4                      | f
        .ifndef RELEASE
        LDSW    %d5
        btst    #0,%d5
        bne.s   1f
        moveq   #0,%d4                       | interpolation off
        .endif
1:      move.l  (%a0,%d3.l*4),%d0            | a
        tst.l   %d4
        beq.s   9f
        cmp.l   %d2,%d3
        bcc.s   9f                           | last entry: no next
        move.l  4(%a0,%d3.l*4),%d6           | b
        moveq   #0,%d7                       | result
        moveq   #24,%d2
        movea.w #4,%a1
2:      move.l  %d0,%d3
        lsr.l   %d2,%d3                      | a byte
        move.l  %d6,%d5
        lsr.l   %d2,%d5                      | b byte
        sub.l   %d3,%d5
        muls.l  %d4,%d5
        asr.l   %d1,%d5
        add.l   %d3,%d5                      | a + ((b - a) * f >> shift)
        lsl.l   #8,%d7
        andi.l  #0xFF,%d5
        or.l    %d5,%d7
        lsl.l   #8,%d0
        lsl.l   #8,%d6
        subq.l  #1,%a1
        move.l  %a1,%d5
        bne.s   2b
        move.l  %d7,%d0
9:      movem.l (%sp),%d3-%d7/%a1
        lea     24(%sp),%sp
        rts

| ---- OB-Xa LP words (replaces 0x65E5A): in d7 = P, d1 = q; out d0 = w0, d1 = w4, d5 = w8; a0/a1 scratch ----
words_i:
        lea     -16(%sp),%sp
        movem.l %d2-%d3/%d6/%a2,(%sp)
        move.l  %d1,%d6
        andi.l  #0x7F,%d6
        moveq   #6,%d0
        cmp.l   %d0,%d7
        bne.s   1f
        moveq   #120,%d0                     | 6-pole: index cap 30
        cmp.l   %d0,%d6
        ble.s   1f
        move.l  %d0,%d6
1:      lea     SVF,%a0
        move.l  %d6,%d0
        moveq   #2,%d1
        moveq   #31,%d2
        bsr     lerp
        move.l  %d0,%d3                      | SVF
        move.l  #NEUTRAL,%d1
        move.l  %d1,%d5
        moveq   #2,%d0
        cmp.l   %d0,%d7
        bne.s   2f
        move.l  %d3,%d0                      | 2-pole: SVF, N, N
        bra.s   9f
2:      moveq   #4,%d0
        cmp.l   %d0,%d7
        beq.s   3f
        move.l  %d3,%d5                      | 6-pole: w8 = SVF
3:      lea     LADB16,%a0
        move.l  %d6,%d0
        moveq   #3,%d1
        moveq   #15,%d2
        bsr     lerp
        movea.l %d0,%a2                      | LADB
        lea     SVF+128,%a0
        move.l  %d6,%d0
        moveq   #2,%d1
        moveq   #31,%d2
        bsr     lerp                         | LADA
        move.l  %a2,%d1
9:      movem.l (%sp),%d2-%d3/%d6/%a2
        lea     16(%sp),%sp
        rts

| ---- HP/BP/Contrary BP table part (replaces 0x6684E): a0 = blk, a1 = desc, d1 = q; clobbers d0, d2, a2, a3 ----
apply_i:
        lea     -12(%sp),%sp
        movem.l %d1/%d3-%d4,(%sp)
        move.l  %d1,%d4                      | q
        movea.l %a0,%a3                      | blk
        movea.l (%a1),%a0                    | table A: (q >> shiftA), 32 entries
        move.l  %d4,%d0
        moveq   #0,%d1
        move.b  9(%a1),%d1
        moveq   #31,%d2
        bsr     lerp
        moveq   #0,%d2
        move.b  8(%a1),%d2
        move.l  %d0,(%a3,%d2.l)
        moveq   #0,%d2
        move.b  10(%a1),%d2                  | table B offset (0xFF: none)
        cmpi.l  #0xFF,%d2
        beq.s   3f
        move.l  %d2,%d3
        movea.l 4(%a1),%a0
        move.l  %d4,%d0
        moveq   #0,%d1
        move.b  11(%a1),%d1
        moveq   #0,%d2
        move.b  14(%a1),%d2                  | last index = step mask
        bsr     lerp
        move.l  %d0,(%a3,%d3.l)
3:      movea.l %a3,%a0
        movem.l (%sp),%d1/%d3-%d4
        lea     12(%sp),%sp
        rts

| ==== 4 Pole LP+Fuzz ====
lpf_type:
        moveq   #3,%d0
        rts
lpf_name:
        move.l  #lpf_str,%d0
        rts

| computeFrames(this, blk, mode, q, struct): LP4 at q/2, then the fuzz words; zeros on -> SETMODE 0xC0
lpf_cf: move.l  20(%sp),-(%sp)               | struct
        move.l  20(%sp),%d0                  | q
        lsr.l   #1,%d0
        move.l  %d0,-(%sp)
        move.l  20(%sp),-(%sp)               | mode
        move.l  20(%sp),-(%sp)               | blk
        move.l  20(%sp),-(%sp)               | this
        jsr     LP4_CF
        lea     20(%sp),%sp
        move.l  16(%sp),%d0                  | level compensation: the LP4 packQ law at q/2, (q/2 * -20) >> 7,
        lsr.l   #1,%d0                       | instead of LP4 computeFrames' stepped table (RGAIN[(q/2) >> 3]),
        moveq   #-20,%d1                     | which jumped 2 dB at Q 112 and disagreed with packQ by 1-2 dB
        muls.l  %d1,%d0
        asr.l   #7,%d0
        move.l  %d0,-(%sp)
        movea.l 12(%sp),%a0                  | blk
        move.l  20(%sp),%d1                  | q
        bsr     fuzz
        .ifndef RELEASE
        LDSW    %d0
        btst    #1,%d0
        beq.s   1f
        .endif
        pea     0xC0.w                       | zero stages active
        move.l  20(%sp),-(%sp)               | mode (12 + 4 + 4)
        move.l  20(%sp),-(%sp)               | blk (8 + 4 + 8)
        jsr     SETMODE
        lea     12(%sp),%sp
1:      move.l  (%sp)+,%d0
        rts

| packQ(this, blk, q, x): q is a byte argument
lpf_pq: move.l  16(%sp),-(%sp)               | x
        moveq   #0,%d0
        move.b  19(%sp),%d0                  | q (12 + 4 + 3)
        lsr.l   #1,%d0
        move.l  %d0,-(%sp)
        move.l  16(%sp),-(%sp)               | blk
        move.l  16(%sp),-(%sp)               | this
        jsr     LP4_PQ
        lea     16(%sp),%sp
        move.l  %d0,-(%sp)
        movea.l 12(%sp),%a0                  | blk
        moveq   #0,%d1
        move.b  19(%sp),%d1                  | q
        bsr     fuzz
        move.l  (%sp)+,%d0
        rts

| fuzz: a0 = blk (ladder already in words 0/4), d1 = q. Caps words 0/4, writes words 1, 5, 8, 9.
| Clobbers d0, d1, a1.
fuzz:   lea     -16(%sp),%sp
        movem.l %d2-%d5,(%sp)
        move.l  %d1,%d5
        andi.l  #0x7F,%d5                    | q
        .ifndef RELEASE
        LDSW    %d2
        move.l  #0xDF,%d3                    | FH
        btst    #4,%d2
        beq.s   1f
        move.l  #0x90,%d3
        .endif
1:      movea.l %a0,%a1
        bsr     fcap                         | word 0
        lea     0x10(%a0),%a1
        bsr     fcap                         | word 4
        .ifndef RELEASE
        move.l  #NEUTRAL,%d0                 | word 1: moving zero (bit 1) or neutral
        btst    #1,%d2
        beq.s   2f
        .endif
        move.l  (%a0),%d0
        move.l  %d5,%d1
        bsr     zlerp
2:      move.l  %d0,4(%a0)
        .ifndef RELEASE
        move.l  #NEUTRAL,%d0                 | word 5: copy of word 4 (bit 2) or neutral
        btst    #2,%d2
        beq.s   3f
        .endif
        move.l  0x10(%a0),%d0
3:      move.l  %d0,0x14(%a0)
        .ifndef RELEASE
        move.l  #NEUTRAL,%d0                 | word 8: copy of word 4 (bit 3) or neutral
        btst    #3,%d2
        beq.s   4f
        move.l  0x10(%a0),%d0
        .endif
4:      move.l  %d0,0x20(%a0)
        move.l  GAINBASE,%d0                 | word 9: LP4 gain at q/2 (base - GOFF[q >> 4])
        move.l  %d5,%d1
        lsr.l   #4,%d1
        lea     GOFF,%a1
        sub.l   (%a1,%d1.l*4),%d0
        move.l  %d0,0x24(%a0)
        movem.l (%sp),%d2-%d5
        lea     16(%sp),%sp
        rts

| zlerp: d0 = word, d1 = q (0..127) -> d0: each byte a + (t - a) * q / 127, t = the byte of 0xFFE0FFE0.
| Clobbers d1 only.
zlerp:  lea     -16(%sp),%sp
        movem.l %d2-%d4/%d6,(%sp)
        move.l  %d0,%d4
        moveq   #0,%d0
        moveq   #24,%d6
1:      move.l  %d4,%d2
        lsr.l   %d6,%d2
        andi.l  #0xFF,%d2                    | a
        move.l  #0xFFE0FFE0,%d3
        lsr.l   %d6,%d3
        andi.l  #0xFF,%d3                    | t
        sub.l   %d2,%d3
        muls.w  %d1,%d3
        divs.w  #127,%d3
        ext.l   %d3
        add.l   %d2,%d3
        andi.l  #0xFF,%d3
        lsl.l   #8,%d0
        or.l    %d3,%d0
        subq.l  #8,%d6
        bpl.s   1b
        movem.l (%sp),%d2-%d4/%d6
        lea     16(%sp),%sp
        rts

| fcap: a1 = word (X_lo F_lo X_hi F_hi), d3 = FH: F_lo above 0xDF -> 0xDF, F_hi above FH -> FH. Clobbers d0.
fcap:
        .ifndef RELEASE
        moveq   #0,%d0
        move.b  1(%a1),%d0
        cmpi.l  #0xDF,%d0
        bls.s   1f
        moveq   #-33,%d0                     | 0xDF
        move.b  %d0,1(%a1)
1:      moveq   #0,%d0
        move.b  3(%a1),%d0
        cmp.l   %d3,%d0
        bls.s   2f
        move.b  %d3,3(%a1)
2:      rts
        .else
| release: high-frame F capped at 0xDF only (the low frame never exceeds 0x08 in the OB-Xa ladder tables)
        moveq   #0,%d0
        move.b  3(%a1),%d0
        cmpi.l  #0xDF,%d0
        bls.s   2f
        moveq   #-33,%d0                     | 0xDF
        move.b  %d0,3(%a1)
2:      rts
        .endif
        .align  2

| formatParam(this, idx, value, labelbuf, valuebuf): idx 1 -> "Fuzz" / "%d", else the LP formatter
lpf_fmt:
        move.l  8(%sp),%d0
        moveq   #1,%d1
        cmp.l   %d1,%d0
        beq.s   1f
        jmp     LP_FMT
1:      pea     fuzz_str
        move.l  0x14(%sp),-(%sp)             | labelbuf (0x10 + 4)
        jsr     STRCPY
        addq.l  #8,%sp
        move.l  0xc(%sp),-(%sp)              | value
        pea     FMT_D
        move.l  0x1c(%sp),-(%sp)             | valuebuf (0x14 + 8)
        jsr     SPRINTF
        lea     12(%sp),%sp
        rts

lpf_str:  .asciz  "4 Pole LP+Fuzz"
fuzz_str: .asciz  "Fuzz"
        .align  4
lpf_vt:
        .include "lpf_vt.inc"
end_of_ctor:
