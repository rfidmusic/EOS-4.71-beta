| Fuzz filters on the OB-Xa models, built like the 4 Pole LP+Fuzz of EOS 4.71-beta2 (test build;
| tools/build_fuzzob.py, notes/fuzz.md). The 4 Pole LP+Fuzz itself is the original code (lpfuzz.s), unchanged.
|
| The chip with the zeros on (SETMODE 0xC0): pole word 0 is a stage of its own; zero 1 pairs with pole 4 and zero 5
| with pole 8, each pair one ratio Z(s) / P(s); word 9 is the gain. The drive is such a pair: the zero starts on its
| pole (transparent at Q 0) and slides toward 0xFFE0 as Q rises (the original zlerp law), boosting everything below
| the zero and driving the chip into clipping.
|
| Each Fuzz filter is a vtable (build 2's OB-Xa vtable with its own type / name stubs and the methods below in
| computeFrames / packQ / formatParam) whose slot 11 (+0x2C) points at its parameter block:
|   +0 long base computeFrames   +4 long base packQ   +8 long base formatParam
|   +12 byte SETMODE flags after the base filter (0: none)
|   +14 program: byte (op << 4 | dst word), byte src word, ..., 0xFF
| computeFrames / packQ: the OB-Xa model with q / 2 (the LP+Fuzz resonance limit), the program, then the LP+Fuzz
| level laws: word 9 = base gain - GOFF[q >> 4], return value = ((q >> 1) * -20) >> 7.
| Program ops:
|   1 COPY dst <- src
|   2 SMTH dst <- src with each frame's X raised to at least 0xC0 (a milder drive pole)
|   3 DZER dst <- zlerp(src, q): the drive zero
| (No high-frame F cap at 0xDF as in the original LP+Fuzz: the OB-Xa bases used here stay at or below 0xD8 for
| every q / 2, both modes, so it would never act; tools/build_fuzzob.py.)
| Every routine has its own section (the builder places them in separate holes), so calls between them are jsr.
| ColdFire 5206e: no cmpi.b / cmp.b #imm; movem only (An) / d16(An).
| Defined on the command line: ZLERP (lpfuzz.s zlerp), LPF_FMT (lpfuzz.s formatParam: idx 1 -> "Fuzz" / "%d").

        .equ    SETMODE,   0x10D3B0
        .equ    GAINBASE,  0x10004D7C
        .equ    GOFF,      0x6871C            | stock: 0x00020000 * k
        .globl  fz_cf, fz_pq, fz_fmt

| computeFrames(this, blk, mode, q, struct)
        .section .fz_cf,"ax"
fz_cf:  lea     -16(%sp),%sp
        movem.l %d2-%d3/%a2-%a3,(%sp)
        movea.l 20(%sp),%a3                  | this
        movea.l (%a3),%a2
        movea.l 0x2C(%a2),%a2                | parameters
        move.l  32(%sp),%d2                  | q
        move.l  %d2,%d0
        lsr.l   #1,%d0
        move.l  36(%sp),-(%sp)               | struct
        move.l  %d0,-(%sp)                   | q / 2 for the OB-Xa model
        move.l  36(%sp),-(%sp)               | mode (28 + 8)
        move.l  36(%sp),-(%sp)               | blk (24 + 12)
        move.l  %a3,-(%sp)
        movea.l (%a2),%a0
        jsr     (%a0)
        lea     20(%sp),%sp
        movea.l 24(%sp),%a0
        jsr     prog
        move.l  %d0,%d3
        moveq   #0,%d0
        move.b  12(%a2),%d0
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
        .section .fz_pq,"ax"
fz_pq:  lea     -16(%sp),%sp
        movem.l %d2-%d3/%a2-%a3,(%sp)
        movea.l 20(%sp),%a3
        movea.l (%a3),%a2
        movea.l 0x2C(%a2),%a2
        moveq   #0,%d2
        move.b  31(%sp),%d2                  | q (the long at 28)
        move.l  %d2,%d0
        lsr.l   #1,%d0
        move.l  32(%sp),-(%sp)               | struct
        move.l  %d0,-(%sp)
        move.l  32(%sp),-(%sp)               | blk (24 + 8)
        move.l  %a3,-(%sp)
        movea.l 4(%a2),%a0
        jsr     (%a0)
        lea     16(%sp),%sp
        movea.l 24(%sp),%a0
        jsr     prog
        movem.l (%sp),%d2-%d3/%a2-%a3
        lea     16(%sp),%sp
        rts

| prog: a0 = blk, a2 = parameters, d2 = q. Runs the program at 14(a2), then the level laws (d0 = the return value).
| Keeps a0, a2, d2; clobbers d1, a1.
        .section .fz_prog,"ax"
prog:   lea     -16(%sp),%sp
        movem.l %d3-%d5/%a4,(%sp)
        lea     14(%a2),%a4
1:      moveq   #0,%d4
        move.b  (%a4)+,%d4
        moveq   #0,%d3
        move.b  (%a4)+,%d3
        move.l  %d4,%d5
        lsr.l   #4,%d5                       | op
        moveq   #15,%d0
        and.l   %d0,%d4
        lsl.l   #2,%d4                       | dst offset
        lsl.l   #2,%d3                       | src offset
        cmp.l   %d0,%d5
        beq.s   9f                           | 0xF: end
        move.l  (%a0,%d3.l),%d0              | the source word
        subq.l  #1,%d5
        beq.s   8f                           | 1 COPY
        subq.l  #1,%d5
        bne.s   4f
        jsr     smth                         | 2 SMTH
        bra.s   8f
4:      move.l  %d2,%d1                      | 3 DZER
        jsr     ZLERP                        | d0 = word, d1 = q -> d0; clobbers d1 only
8:      move.l  %d0,(%a0,%d4.l)
        bra.s   1b
9:      jsr     level
        movem.l (%sp),%d3-%d5/%a4
        lea     16(%sp),%sp
        rts

| smth: d0 = word -> d0 with each frame's X (bytes 0 and 2) at least 0xC0. Clobbers d1.
        .section .fz_smth,"ax"
smth:   move.l  %d0,-(%sp)
        moveq   #0,%d1
        move.b  (%sp),%d1                    | low-frame X
        cmpi.l  #0xC0,%d1
        bcc.s   1f
        moveq   #-64,%d1                     | 0xC0
        move.b  %d1,(%sp)
1:      moveq   #0,%d1
        move.b  2(%sp),%d1                   | high-frame X
        cmpi.l  #0xC0,%d1
        bcc.s   2f
        moveq   #-64,%d1
        move.b  %d1,2(%sp)
2:      move.l  (%sp)+,%d0
        rts

| level: a0 = blk, d2 = q -> word 9 = GAINBASE - GOFF[q >> 4]; d0 = ((q >> 1) * -20) >> 7. Clobbers d1, a1.
        .section .fz_level,"ax"
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

| formatParam(this, idx, value, labelbuf, valuebuf): idx 1 -> the original LP+Fuzz formatter ("Fuzz" / "%d"),
| else the OB-Xa model's formatter
        .section .fz_fmt,"ax"
fz_fmt: moveq   #1,%d1
        cmp.l   8(%sp),%d1
        beq.s   1f
        movea.l 4(%sp),%a0
        movea.l (%a0),%a0
        movea.l 0x2C(%a0),%a0
        movea.l 8(%a0),%a0
        jmp     (%a0)
1:      jmp     LPF_FMT
