| Cord destination list: show Lfo2Ck (107) before Lag0in (106). Notes: notes/lfock.md.
| Stored ids do not change. The stock walkers already treat the visit index as the id, so each
| one swaps 106 and 107 at the point it copies that index, and the found entry returns the
| swapped id. Visit position n maps to id n, except 106 -> 107 and 107 -> 106.
| Hooks (build_lfock.py): bsr over move.l d7,d6; movea.l a1,a5 at 0x62D22 and 0x62D86
| (the moveq #0,d0; move.b d6,d0 that follows is left in place). move.l d7,d0 at 0x62D48 and
| 0x62DAC becomes move.l d6,d0. bsr replaces move.b 0x17(sp),d1 at 0x62CA0; the stock bne
| still tests the byte. Those three bsrs land on jmp trampolines at 0x66B24, because the
| routines live outside bsr.w range. The jmp does not push, so rts returns to the walker.

        .section .idsw,"ax"
        .globl  id_swap
id_swap:
        move.l  %d7,%d6
        moveq   #106,%d0
        cmp.l   %d0,%d7
        beq.s   1f
        addq.l  #1,%d0
        cmp.l   %d0,%d7
        bne.s   2f
1:      bchg    #0,%d6                 | 106 and 107 differ only in bit 0
2:      movea.l %a1,%a5
        rts

| bsr pushes the return address, so the id byte stock reads at 0x17(sp) is at 0x1B(sp).
| moveq clears d1 first: cmp.b is illegal on the 5206e, and a dirty high word would miss.
| tst.l leaves Z set for the stock bne when the id is 0.
        .section .revid,"ax"
        .globl  rev_id
rev_id:
        moveq   #0,%d1
        move.b  0x1B(%sp),%d1
        moveq   #106,%d0
        cmp.l   %d0,%d1
        beq.s   1f
        moveq   #107,%d0
        cmp.l   %d0,%d1
        bne.s   2f
1:      bchg    #0,%d1
2:      tst.l   %d1
        rts
