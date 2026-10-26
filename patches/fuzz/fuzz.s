| Fuzz filters on the stock E-mu filters, built like the 4 Pole LP+Fuzz of EOS 4.71-beta2 (test build;
| tools/build_fuzz.py, notes/fuzz.md).
|
| The chip with the zeros on (SETMODE 0xC0): pole word 0 is a stage of its own (a normal 2-pole low-pass); zero 1
| pairs with pole 4 and zero 5 with pole 8, each pair one ratio Z(s) / P(s); word 9 is the gain. The LP+Fuzz drive
| is such a pair: the pole is the filter's resonant pole at the cutoff and the zero starts on it (transparent at
| Q 0) and slides toward 0xFFE0 (X 0xFF, F 0xE0) as Q rises, so the pair boosts everything below the zero by about
| (f_zero / f_cutoff)^2 and drives the chip into clipping.
|
| Each Fuzz filter is a vtable (a copy of its stock filter's vtable with type / name / computeFrames / packQ /
| formatParam replaced by the methods below) followed by its parameters, read through the object the filter
| manager passes first to every method: this -> vtable; vtable + 0x2C:
|   +0x2C byte type ID   +0x2D byte flags (bit 0: smooth drive pole, its X raised to at least 0xC0)
|   +0x2E byte SETMODE flags after the stock filter (0: none)
|   +0x30 long name      +0x34 long base vtable (the stock filter)
|   +0x38 program: byte (op << 4 | dst word), byte src word, ..., 0xFF
| computeFrames / packQ: the stock filter with q / 2 (the LP+Fuzz resonance limit), the program, then the LP+Fuzz
| level laws: word 9 = base gain - GOFF[q >> 4], return value (voice level) = ((q >> 1) * -20) >> 7.
| Program ops:
|   1 CAP  dst: high-frame F (byte 3) capped at 0xDF (the LP+Fuzz limit)
|   2 COPY dst <- src
|   3 PEAK dst <- src with both X bytes 0xFF (a zero at the pole's frequency, no damping: a resonance peak pair)
|   4 DPOL dst: the drive pole: the src word (it follows the cutoff), or fixed (switch bit 0)
|   5 DZER dst: the drive zero from the last drive pole and q
|   6 NEUT dst: neutral (0xFFCFFFCF)
| Test switch SW = parameter 195 (0..31, RAM vector slot 249, zero at boot). 0 = the LP+Fuzz design.
|   bit 0 fixed drive pole (X 0xC0, F per bits 2-3: 0x71 / 0x60 / 0x80 / 0x50, about 1 kHz / 690 / 1.4 k / 490 Hz)
|   bit 1 new zero law: each frame's zero F = min(0xE0, pole F + (q * 0x6F) >> 7), X as the pole
|   bit 4 no q / 2 (the full stock resonance)
| ColdFire 5206e: no cmpi.b / cmp.b #imm; movem only (An) / d16(An).

        .equ    SETMODE,   0x10D3B0
        .equ    STRCPY,    0x1A6C4C
        .equ    SPRINTF,   0x1A6EA0
        .equ    FMT_D,     0x68CB0            | "%d"
        .equ    SW,        0x100003E4
        .equ    GAINBASE,  0x10004D7C
        .equ    GOFF,      0x6871C            | stock: 0x00020000 * k

        .section .fzc,"ax"
        .globl  fz_type, fz_name, fz_cf, fz_pq, fz_fmt, fz_swget, fz_swset

| computeFrames(this, blk, mode, q, struct)
fz_cf:  lea     -16(%sp),%sp
        movem.l %d2-%d3/%a2-%a3,(%sp)
        movea.l 20(%sp),%a3                  | this
        movea.l (%a3),%a2                    | vtable
        move.l  32(%sp),%d2                  | q
        bsr     baseq
        move.l  36(%sp),-(%sp)               | struct
        move.l  %d0,-(%sp)                   | q for the stock filter
        move.l  36(%sp),-(%sp)               | mode (28 + 8)
        move.l  36(%sp),-(%sp)               | blk (24 + 12)
        move.l  %a3,-(%sp)
        movea.l 0x34(%a2),%a0
        movea.l 0x14(%a0),%a0
        jsr     (%a0)
        lea     20(%sp),%sp
        movea.l 24(%sp),%a0
        move.l  %d2,%d1
        bsr     prog
        bsr     level
        move.l  %d0,%d3
        moveq   #0,%d0
        move.b  0x2E(%a2),%d0
        beq.s   1f
        move.l  %d0,-(%sp)                   | SETMODE(blk, mode, flags)
        move.l  32(%sp),-(%sp)               | mode (28 + 4)
        move.l  32(%sp),-(%sp)               | blk (24 + 8)
        jsr     SETMODE
        lea     12(%sp),%sp
1:      move.l  %d3,%d0
        movem.l (%sp),%d2-%d3/%a2-%a3
        lea     16(%sp),%sp
        rts

| packQ(this, blk, q, struct): q is a byte argument (low byte of the long)
fz_pq:  lea     -16(%sp),%sp
        movem.l %d2-%d3/%a2-%a3,(%sp)
        movea.l 20(%sp),%a3
        movea.l (%a3),%a2
        moveq   #0,%d2
        move.b  31(%sp),%d2                  | q (the long at 28)
        bsr     baseq
        move.l  32(%sp),-(%sp)               | struct
        move.l  %d0,-(%sp)
        move.l  32(%sp),-(%sp)               | blk (24 + 8)
        move.l  %a3,-(%sp)
        movea.l 0x34(%a2),%a0
        movea.l 0x18(%a0),%a0
        jsr     (%a0)
        lea     16(%sp),%sp
        movea.l 24(%sp),%a0
        move.l  %d2,%d1
        bsr     prog
        bsr     level
        movem.l (%sp),%d2-%d3/%a2-%a3
        lea     16(%sp),%sp
        rts

| baseq: d2 = q -> d0 = q / 2 (switch bit 4 set: q). Clobbers d1.
baseq:  move.l  %d2,%d0
        move.l  SW,%d1
        btst    #4,%d1
        bne.s   1f
        lsr.l   #1,%d0
1:      rts

| level: a0 = blk, d2 = q -> word 9 = GAINBASE - GOFF[q >> 4]; d0 = ((q >> 1) * -20) >> 7. Clobbers d1, a1.
level:  move.l  %d2,%d1
        lsr.l   #4,%d1
        lea     GOFF,%a1
        move.l  GAINBASE,%d0
        sub.l   (%a1,%d1.l*4),%d0
        move.l  %d0,0x24(%a0)
        move.l  %d2,%d0
        lsr.l   #1,%d0
        moveq   #-20,%d1
        muls.l  %d1,%d0
        asr.l   #7,%d0
        rts

| prog: a0 = blk, a2 = vtable, d1 = q. Runs the program at 0x38(a2). Keeps a0; clobbers d0, d1, a1.
prog:   lea     -24(%sp),%sp
        movem.l %d2-%d6/%a4,(%sp)
        lea     0x38(%a2),%a4
        move.l  %d1,%d6                      | q
        moveq   #0,%d5                       | the last drive pole
1:      moveq   #0,%d2
        move.b  (%a4)+,%d2
        moveq   #0,%d3
        move.b  (%a4)+,%d3
        move.l  %d2,%d4
        lsr.l   #4,%d4                       | op
        moveq   #15,%d0
        and.l   %d0,%d2
        lsl.l   #2,%d2                       | dst offset
        lsl.l   #2,%d3                       | src offset
        cmp.l   %d0,%d4
        beq.s   9f                           | 0xF: end
        move.l  (%a0,%d3.l),%d0              | the source word
        subq.l  #1,%d4
        bne.s   2f
        moveq   #0,%d1                       | 1 CAP
        move.b  %d0,%d1
        cmpi.l  #0xDF,%d1
        bls.s   8f
        andi.l  #0xFFFFFF00,%d0
        ori.l   #0xDF,%d0
        bra.s   8f
2:      subq.l  #1,%d4
        beq.s   8f                           | 2 COPY
        subq.l  #1,%d4
        bne.s   4f
        ori.l   #0xFF00FF00,%d0              | 3 PEAK
        bra.s   8f
4:      subq.l  #1,%d4
        bne.s   5f
        bsr     dpole                        | 4 DPOL
        move.l  %d0,%d5
        bra.s   8f
5:      subq.l  #1,%d4
        bne.s   6f
        move.l  %d5,%d0                      | 5 DZER
        move.l  %d6,%d1
        jsr     dzero                        | (in .fzv: too far for bsr)
        bra.s   8f
6:      move.l  #0xFFCFFFCF,%d0              | 6 NEUT
8:      move.l  %d0,(%a0,%d2.l)
        bra.s   1b
9:      movem.l (%sp),%d2-%d6/%a4
        lea     24(%sp),%sp
        rts

| dpole: d0 = source word, a2 = vtable -> d0 = drive pole word. Clobbers d1, a1.
dpole:  move.l  SW,%d1
        btst    #0,%d1
        bne.s   2f                           | switch bit 0: fixed pole
        btst    #0,0x2D(%a2)
        beq.s   9f                           | the source word itself (follows the cutoff)
        move.l  %d0,%d1                      | smooth: each frame's X raised to at least 0xC0
        andi.l  #0xFF000000,%d1
        cmpi.l  #0xC0000000,%d1
        bcc.s   1f
        andi.l  #0x00FFFFFF,%d0
        ori.l   #0xC0000000,%d0
1:      move.l  %d0,%d1
        andi.l  #0x0000FF00,%d1
        cmpi.l  #0x0000C000,%d1
        bcc.s   9f
        andi.l  #0xFFFF00FF,%d0
        ori.l   #0x0000C000,%d0
        bra.s   9f
2:      lsr.l   #2,%d1
        moveq   #3,%d0
        and.l   %d0,%d1
        lea     dpf(%pc),%a1
        moveq   #0,%d0
        move.b  (%a1,%d1.l),%d0              | F
        ori.l   #0xC000,%d0                  | X 0xC0
        move.l  %d0,%d1
        swap    %d1
        or.l    %d1,%d0                      | both frames
9:      rts
dpf:    .byte   0x71, 0x60, 0x80, 0x50

| formatParam(this, idx, value, labelbuf, valuebuf): idx 1 -> "Fuzz" / "%d", else the stock filter's formatter
fz_fmt: move.l  8(%sp),%d0
        moveq   #1,%d1
        cmp.l   %d1,%d0
        beq.s   1f
        movea.l 4(%sp),%a0
        movea.l (%a0),%a0
        movea.l 0x34(%a0),%a0
        movea.l 0x1C(%a0),%a0
        jmp     (%a0)
1:      pea     fz_fuzz
        move.l  0x14(%sp),-(%sp)             | labelbuf (0x10 + 4)
        jsr     STRCPY
        addq.l  #8,%sp
        move.l  0xc(%sp),-(%sp)              | value
        pea     FMT_D
        move.l  0x1c(%sp),-(%sp)             | valuebuf (0x14 + 8)
        jsr     SPRINTF
        lea     12(%sp),%sp
        rts

fz_type:
        movea.l 4(%sp),%a0
        movea.l (%a0),%a0
        moveq   #0,%d0
        move.b  0x2C(%a0),%d0
        rts

fz_name:
        movea.l 4(%sp),%a0
        movea.l (%a0),%a0
        move.l  0x30(%a0),%d0
        rts

| ---- .fzv (the old LP+Fuzz area, inside 0x60000-0x7FFFE, the reach of the ctor list (vt - 0x60000) / 2):
|      the small methods, then the vtables, parameters and names ----
        .section .fzv,"ax"
| dzero: d0 = drive pole word, d1 = q -> d0 = drive zero word. Clobbers d1.
dzero:  lea     -16(%sp),%sp
        movem.l %d2-%d4/%d6,(%sp)
        move.l  SW,%d2
        btst    #1,%d2
        beq.s   5f                           | default: the original LP+Fuzz law
        move.l  %d1,%d2                      | switch bit 1: new law: F + (q * 0x6F) >> 7, at most 0xE0, in both frames
        mulu.w  #0x6F,%d2
        lsr.l   #7,%d2                       | dF
        move.l  %d0,%d4
        moveq   #0,%d0
        moveq   #16,%d6                      | frame shift: 16 (low frame, upper half), then 0
1:      move.l  %d4,%d3
        lsr.l   %d6,%d3
        andi.l  #0xFFFF,%d3                  | X:F
        move.l  %d3,%d1
        andi.l  #0xFF,%d1                    | F
        add.l   %d2,%d1
        cmpi.l  #0xE0,%d1
        bls.s   2f
        move.l  #0xE0,%d1
2:      andi.l  #0xFF00,%d3
        or.l    %d1,%d3
        lsl.l   %d6,%d3
        or.l    %d3,%d0
        subi.l  #16,%d6
        bpl.s   1b
        bra.s   9f
5:      move.l  %d0,%d4                      | original law: each byte a + (t - a) * q / 127, t from 0xFFE0FFE0
        moveq   #0,%d0
        moveq   #24,%d6
6:      move.l  %d4,%d2
        lsr.l   %d6,%d2
        andi.l  #0xFF,%d2
        move.l  #0xFFE0FFE0,%d3
        lsr.l   %d6,%d3
        andi.l  #0xFF,%d3
        sub.l   %d2,%d3
        muls.w  %d1,%d3
        divs.w  #127,%d3
        ext.l   %d3
        add.l   %d2,%d3
        andi.l  #0xFF,%d3
        lsl.l   #8,%d0
        or.l    %d3,%d0
        subq.l  #8,%d6
        bpl.s   6b
9:      movem.l (%sp),%d2-%d4/%d6
        lea     16(%sp),%sp
        rts

| parameter 195 (test switch): getter(desc), setter(desc, v)
fz_swget:
        move.l  SW,%d0
        rts
fz_swset:
        move.l  8(%sp),%d0
        bpl.s   1f
        moveq   #0,%d0
1:      moveq   #31,%d1
        and.l   %d1,%d0
        move.l  %d0,SW
        rts

        .include "fz_vt.inc"
fz_fuzz: .asciz "Fuzz"
