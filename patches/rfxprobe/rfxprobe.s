| RFXPROBE: read the voice and RFX send state behind the "stuck / random pan" reports over SysEx
| (tools/build_b4.py, notes/rfx_bugs.md). No hooks: only the getter/setter of SysEx parameter 195 (descriptor
| 0x25AF4, dormant in stock), as in patches/ramprobe/ramprobe.s.
|
| Parameter 195 (0..191): set a command, then read the latched long 11 bits per get (low, mid, high).
| Send 0 before each command so the same command can repeat.
|   16      E-mu's orphan-partner counters: 0x100071C0 (word, high half) and 0x100071C2 (word, low half)
|   17      0x100071C4 (word) in the high half; the low half = live orphan partners now (scan below)
|   64 + n  channel n (0..127; an empty slot reads 0): bits 31-28 voice type (+0x1A: 1 mono, 2/4 stereo main, 8 partner),
|           27-16 send 1 level cache (block +0x0C, 0xFFF after note-on invalidation),
|           15-0 pan cache (block +0x32: last pan 0x10E280 wrote, 0xFF7F after invalidation)
| Live orphan = a voice of type 8 whose main voice (struct - 0x3FE) is no longer stereo (+0x1A & 6 == 0): the
| case 0x194C6C counts in 0x100071C2 and then leaves running.
| Voice structs: 0x102E9298[n] (0x194B34, set at boot together with their RFX block +0x72); empty (0) slots are
| skipped.
|
| State: two longs at the far end of the malloc heap block (as RAMPROBE; used only when the 2.6 MB heap is full).
| ColdFire 5206e: no cmpi.b / cmp.b #imm; no byte ops on memory.

        .equ    LATCH,     0x1029E390        | the piece counter follows at +4
        .equ    VOICES,    0x102E9298
        .equ    CNT,       0x100071C0

        .section .rfxp,"ax"
        .globl  xp_get, xp_set

| getter(desc) -> d0 = the next 11 bits of the latch
xp_get: lea     LATCH,%a0
        move.l  4(%a0),%d1
        addq.l  #1,4(%a0)
        move.l  (%a0),%d0
        mulu.w  #11,%d1
        lsr.l   %d1,%d0
        andi.l  #0x7FF,%d0
        rts

| setter(desc, v)
xp_set: move.l  8(%sp),%d0
        lea     LATCH,%a1
        clr.l   4(%a1)
        lea     VOICES,%a0
        moveq   #16,%d1
        sub.l   %d1,%d0
        bne.s   1f
        move.l  CNT,(%a1)                    | 16: c0:c2
        rts
1:      subq.l  #1,%d0
        bne.s   3f
        move.l  %d2,-(%sp)                   | 17: live orphans, c4 in the high half
        moveq   #0,%d2
        moveq   #127,%d1
2:      movea.l (%a0)+,%a1
        move.l  %a1,%d0
        beq.s   21f
        moveq   #8,%d0
        cmp.l   0x1A(%a1),%d0
        bne.s   21f
        moveq   #6,%d0
        and.l   -0x3E4(%a1),%d0              | main voice (struct - 0x3FE) +0x1A
        bne.s   21f
        addq.l  #1,%d2
21:     subq.l  #1,%d1
        bpl.s   2b
        move.l  CNT+4,%d0
        clr.w   %d0
        or.l    %d2,%d0
        move.l  %d0,LATCH
        move.l  (%sp)+,%d2
        rts
3:      moveq   #47,%d1                      | d0 = v - 17; 64 + n -> n
        sub.l   %d1,%d0
        bcs.s   9f
        moveq   #127,%d1
        cmp.l   %d1,%d0
        bhi.s   9f
        clr.l   (%a1)                        | empty slot reads 0
        lsl.l   #2,%d0
        movea.l (%a0,%d0.l),%a0              | voice
        move.l  %a0,%d0
        beq.s   9f
        move.l  0x1A(%a0),%d0                | type
        moveq   #28,%d1
        lsl.l   %d1,%d0
        movea.l 0x72(%a0),%a0                | RFX block
        move.w  0x0C(%a0),%d1                | send 1 level cache
        andi.l  #0xFFF,%d1
        swap    %d1
        or.l    %d1,%d0
        move.w  0x32(%a0),%d0                | pan cache (low word)
        move.l  %d0,(%a1)
9:      rts
