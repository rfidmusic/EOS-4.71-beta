| Lfo1Ck / Lfo2Ck cord destinations (notes/lfock.md).
| The beta2 LFO tick hook (0x61BF4, jmp lfo_tick) is retargeted here. The cord summer writes its
| running sum into the gap between the two LFOs (voice+0x1A4 for LFO 1, voice+0x1A6 for LFO 2).
| A positive or zero sum leaves Rate alone. A negative sum is the depth: magnitude 4032 (a controller
| at CC 127 through panel amount -100) is 1/32, and smaller depths are the slower lengths, in 16
| even steps. 4032 = (127<<5)*(127<<5)>>12.
| The sync body at 0x2040E expects d0 = 0x8000|0x2000|div (key sync). LFO 2's gap keeps the stock
| init 1, so that word is one count higher.
| FUN_00061BC0 saves only d5-d7/a5, and the sync body saves d2-d4 only after its own entry, so this
| prologue saves d2-d3 around the divide and restores them before the jump. 5206e movem has no
| predecrement. divu.l into d0 encodes a remainder divide on 5206e; the quotient form uses d3.
| move.w into a data register does not sign-extend.
| Hooks (build_lfock.py): 0x61BF4 jmp cord_tick; 0x5F7E0 jsr lfo_bind; 0xCDAC2 jsr rate_enter;
| 0xCDB8C jsr rate_built; the two Rate descriptors' setter -> rate_set. Dest 98 / 107, flags 0x200.
| The note start writes long 1 across both gaps. lfo_bind writes 0x40004001 instead when the
| note's preset is the one on screen (EDIT_VOICE), so the tick knows whose note it is: a gap
| word of 0x2000 or more is such a note, and 0x4000 is taken off before use. Other presets'
| notes sound their division without touching the readout. The sum of one full cord is 4032,
| so the ranges stay apart up to two full-depth cords on one LFO.
| While the gap word is negative the stored Rate byte becomes 128+division (the existing Rate names)
| and rate_set does not write. The copy rate_set reads is two words at 0x100003E8, not the preset
| voice: the preset header is 284 bytes and voice+0x1A4 is past it. The sounding path still reads
| the gap on the runtime voice. A zone (0x10004089 clear) is left untouched. The saved Rate belongs
| to the preset in 0x100003E0; editing a different preset drops that save, and the previous preset
| keeps the division it was showing. Voice+0x4A and voice+0x4E are live pointers, so this code
| does not store anything there. The LFO page paints the Rate byte when it opens; rate_show asks it to
| paint again. The same paint reads the Rate widget's enable byte. Clearing it is what greys Tempo
| while the clock is external, so that byte is cleared while this LFO's gap word is negative.
| The cord stays in force through MIDI Stop and through a missing beat clock. The sum going
| zero or positive is what puts the saved Rate back. That sum is written only while a note
| sounds, so leaving the Cords page would leave Rate grey until the next note. The LFO page
| opener (0xCDA70, pages 0x12 and 0x13) calls rate_enter where it stores the page id. A cord
| with a negative amount aimed at this LFO can still hold Rate; amount zero or above, or no
| such cord, puts the saved Rate back before the page is drawn.

        .equ    LFO_TICK,      0x00020400
        .equ    SYNC_BODY,     0x0002040E
        .equ    LFO2_TICK_RET, 0x00061D70
        .equ    FULL,          4032
        .equ    RATE_SET,      0x00069F80
        .equ    LFO_FMT,       0x00068BF0
        .equ    EDIT_VOICE,    0x100040AC   | preset screen's voice, or a 22-byte zone
        .equ    FULL_VOICE,    0x10004089   | 1 when EDIT_VOICE is the preset voice
        .equ    HOLD,          0x100003EC   | saved Rates, magic at +2. Vector 251, flash zero.
        .equ    MIRROR,        0x100003E8   | LFO1 gap, LFO2 at +2. Vector 250, flash zero.
        .equ    OWNER,         0x100003E0   | preset voice the saved Rates belong to
        .equ    PAGE_ID,       0x1000415C   | preset page being shown
        .equ    PAGE_OBJ,      0x10004D64   | object of the screen currently up
        .equ    PAGE_CACHE,    0x102C327C   | built pages; the opener's moveq #-11 makes the index page-11
        .equ    SCREEN_VT,     0x000B2D1C   | cached LFO page object. Its page pointer is the long at +0x38.
        .equ    CORDS,         0xBC         | 24 x {src, dst, amt, pad} on the preset voice. Amounts are -100..100.
        .equ    BIND,          0x4000       | gap-word base for a note of the preset on screen
        .equ    BIND_LONG,     0x40004001   | both gaps, written where stock writes long 1

        .section .lfk,"ax"
        .balign 4
| d1 is 0 for LFO 2 from here on, in every routine below that takes it.
        .globl  cord_tick
cord_tick:
        move.l  0x10(%sp),%d1
        subi.l  #LFO2_TICK_RET,%d1
        beq.s   2f
        move.w  0x1C(%a5),%d0           | LFO 1 gap (voice+0x1A4)
        bra.s   3f
2:      move.w  -2(%a5),%d0             | LFO 2 gap (voice+0x1A6)
3:      ext.l   %d0
        cmpi.l  #BIND/2,%d0
        blt.s   6f                      | another preset's note: sound only
        subi.l  #BIND,%d0
        bsr     rate_publish            | panel shows the edited voice's Rate byte
6:      tst.l   %d0
        bmi.s   4f
        jmp     LFO_TICK                | zero or positive: Rate path
4:      lea     -8(%sp),%sp
        movem.l %d2-%d3,(%sp)
        tst.l   %d1
        bne.s   5f
        subq.l  #1,%d0                  | undo the stock long-1 in the low half
5:      bsr.s   cord_div
        ori.l   #0xA000,%d0             | bit 15 active, bit 13 key sync
        tst.l   %d1
        bne.s   7f
        ori.l   #0x4000,%d0             | LFO 2 note-tick base
7:      movem.l (%sp),%d2-%d3
        lea     8(%sp),%sp
        jmp     SYNC_BODY

| Replaces the note start's move.l #1,(a4)+ at 0x5F7E0, a4 = amp+0x1A4, a3 = preset+0x9C.
| A note of the preset on screen starts its gaps at BIND, so its ticks are the ones that
| drive the Rate readout. Other presets' notes keep the stock 1 and only sound.
        .globl  lfo_bind
lfo_bind:
        move.l  #BIND_LONG,%d0
        lea     -0x9C(%a3),%a0
        cmpa.l  EDIT_VOICE,%a0
        beq.s   1f
        moveq   #1,%d0
1:      move.l  %d0,(%a4)+
        rts

| d0 = sign-extended gap word, already adjusted for LFO 2. Negative. Returns the division in d0.
| Clobbers d2-d3. The caller has saved them.
cord_div:
        neg.l   %d0
        subq.l  #1,%d0
        lsl.l   #4,%d0
        move.l  %d0,%d3
        moveq   #63,%d2
        lsl.l   #6,%d2                  | FULL
        divu.l  %d2,%d3
        move.l  %d3,%d0
        cmpi.l  #15,%d0
        bls.s   1f
        moveq   #15,%d0
1:      rts

| d0 = the gap sum, sign-extended, d1 = 0 for LFO 2. Puts 128+division into the
| edited voice's Rate byte while the sum is negative, and puts the original byte back when
| it is not. The panel redraws that byte; the sounding path does not read it while overridden.
| Preserves d0, d1 and a5. rate_ui is the same entry, used by the page open.
        .globl  rate_ui
        .globl  rate_publish
rate_ui:
rate_publish:
        lea     -24(%sp),%sp
        movem.l %d0-%d3/%a0-%a1,(%sp)
        move.l  EDIT_VOICE,%a0
        move.l  %a0,%d2
        beq.w   9f
        tst.b   FULL_VOICE
        beq.w   .Ldone                  | a zone is 22 bytes; its Rate is not here
        lea     HOLD,%a1
        moveq   #0,%d2
        move.b  2(%a1),%d2
        cmpi.l  #0xC3,%d2
        beq.s   1f
        move.w  #-1,(%a1)
        move.b  #0xC3,%d2
        move.b  %d2,2(%a1)
1:      cmp.l   OWNER,%a0
        beq.s   .Lown
        move.l  %a0,OWNER
        move.w  #-1,(%a1)
.Lown:  tst.l   %d1
        bne.s   2f
        move.w  %d0,(MIRROR-HOLD+2)(%a1)
        addq.l  #1,%a1
        moveq   #0,%d3
        move.w  #0x9E,%d3
        bra.s   3f
2:      move.w  %d0,(MIRROR-HOLD)(%a1)
        moveq   #0,%d3
        move.w  #0x96,%d3
3:      adda.l  %d3,%a0
        tst.w   %d0
        bmi.s   4f
        moveq   #0,%d2
        move.b  (%a1),%d2
        cmpi.l  #0xFF,%d2
        beq.s   9f
        bsr.s   rate_put
7:      move.b  #0xFF,(%a1)
        bra.s   9f
4:      move.b  (%a1),%d2
        extb.l  %d2
        addq.l  #1,%d2                  | 0xFF: nothing saved yet
        bne.s   5f
        move.b  (%a0),(%a1)             | keep the Rate this cord is covering
5:      move.l  (%sp),%d0
        tst.l   %d1
        bne.s   6f
        subq.l  #1,%d0
6:      bsr     cord_div
        addi.l  #128,%d0
        moveq   #0,%d2
        move.b  %d0,%d2
        bsr.s   rate_put
9:      move.l  (%sp),%d0
        move.l  4(%sp),%d1              | rate_show reuses d1; the tick return is the saved one
        bsr.s   rate_tone
.Ldone: movem.l (%sp),%d0-%d3/%a0-%a1
        lea     24(%sp),%sp
        rts

| d2 is the Rate byte to show. Redraws only when the byte changes.
rate_put:
        moveq   #0,%d3
        move.b  (%a0),%d3
        cmp.l   %d2,%d3
        beq.s   1f
        move.b  %d2,(%a0)
        bsr.s   rate_show
1:      rts

| d0.w = this LFO's gap sum, d1 = 0 for LFO 2. Grey this page's Rate widget while the sum
| is negative. A rebuilt page comes back enabled, so the widget byte itself is the record.
rate_tone:
        move.l  PAGE_ID,%d2
        moveq   #0x12,%d3
        tst.l   %d1
        bne.s   1f
        addq.l  #1,%d3
1:      cmp.l   %d3,%d2
        bne.s   9f
rate_sign:                              | d0.w sign only; the page is known to be this one
        tst.w   %d0
        bmi.s   2f
        moveq   #1,%d0
        bra.s   3f
2:      moveq   #0,%d0
3:      bsr.s   rate_grey
        beq.s   9f
        bsr.s   rate_show
9:      rts

| d0 = 1 to show Rate normally, 0 to grey it. Returns Z set when the widget is already that way.
| The cached object is the field list. Its container's first child is Rate. The paint reads
| byte +0x3A, and a focused field also has +0x24 set.
rate_grey:
        move.l  %d0,%d2
        bsr.s   rate_slot
        move.l  %a0,%d0
        beq.s   9f
        move.l  (%a0),%d0
        cmpi.l  #SCREEN_VT,%d0
        bne.s   7f
        move.l  0x30(%a0),%d0
        beq.s   9f
        movea.l %d0,%a0
        move.l  0x0C(%a0),%d0
        beq.s   9f
        movea.l %d0,%a0
        moveq   #0,%d0
        move.b  0x3A(%a0),%d0
        cmp.l   %d2,%d0
        beq.s   9f
        move.b  %d2,0x3A(%a0)
        bne.s   8f
        clr.b   0x24(%a0)
8:      moveq   #1,%d0
        rts
7:      moveq   #0,%d0
9:      rts

| The open LFO page (id 0x12 or 0x13) reads its fields again, the same way re-opening it does.
| Preserves a5. No page object means there is nothing to draw.
rate_show:
        bsr.s   rate_slot
        move.l  %a0,%d1
        beq.s   9f
        move.l  %a5,-(%sp)
        pea     3
        move.l  %d0,-(%sp)
        jsr     0xCC1CC
        addq.l  #8,%sp
        movea.l (%sp)+,%a5
9:      rts

| Page object of the open LFO page in a0, and its cache index in d0. a0 is 0 when the open
| page is not an LFO page, and when that cached page is not the screen currently up. Opening a
| page stores its object at PAGE_OBJ; another screen replaces that long or clears it. Redrawing
| from the tick otherwise calls the page open, which switches to LFO 1 wherever you were.
rate_slot:
        bsr.s   rate_page
        move.l  %a0,%d1
        beq.s   2f
        cmp.l   PAGE_OBJ,%d1
        beq.s   2f
        suba.l  %a0,%a0
2:      rts

| The cached object of the open LFO page in a0, or 0. Cache index in d0. Clobbers d1.
rate_page:
        move.l  PAGE_ID,%d0
        subi.l  #0x12,%d0
        moveq   #1,%d1
        cmp.l   %d1,%d0
        bhi.s   1f
        addq.l  #7,%d0
        movea.l #PAGE_CACHE,%a0
        move.l  (%a0,%d0.l*4),%a0
        rts
1:      suba.l  %a0,%a0
        rts

| (descriptor, value). While this LFO's gap copy is negative the stored Rate is left alone.
| The descriptor's +0x10 is the Rate offset, 0x96 or 0x9E. The copy lives in RAM, not the
| voice, so no voice lookup is needed. The getter stays the stock zero.
        .globl  rate_set
rate_set:
        movea.l 4(%sp),%a1
        moveq   #0,%d1
        move.w  0x10(%a1),%d1
        move.w  MIRROR,%d0
        cmpi.l  #0x9E,%d1
        bne.s   .Lsetgo
        move.w  MIRROR+2,%d0
.Lsetgo:
        tst.w   %d0
        bmi.s   .Lsetheld
        jmp     RATE_SET
.Lsetheld:
        rts

| Replaces the opener's cache store (0xCDB8C: move.l a5,(a4,d6.l*4); lea 20(sp),sp) after a page
| is built for the first time. The new page's Rate widget is enabled, so grey it now when this
| LFO's gap copy is negative. The cached open stores the page at PAGE_OBJ first; this path
| never did, so store it here for rate_slot. d6 is the cache index, 7 for LFO 1 and 8 for LFO 2.
| The displaced lea is done by moving the return address up before the rts.
        .globl  rate_built
rate_built:
        move.l  %a5,(%a4,%d6.l*4)
        move.l  %a5,PAGE_OBJ
        move.l  %d2,-(%sp)
        move.w  MIRROR,%d0
        moveq   #8,%d1
        cmp.l   %d1,%d6
        bne.s   1f
        move.w  MIRROR+2,%d0
1:      bsr     rate_sign
        move.l  (%sp)+,%d2
        move.l  (%sp),20(%sp)
        lea     20(%sp),%sp
        rts

| The LFO opener's move.l d7,PAGE_ID and add.l d7,d6. d7 is the page, d6 arrived as -11.
| Both survive the refresh that rate_open may run. The opener still uses them afterwards.
        .globl  rate_enter
rate_enter:
        move.l  %d7,PAGE_ID
        add.l   %d7,%d6
        lea     -12(%sp),%sp
        movem.l %d2/%d6-%d7,(%sp)
        bsr     rate_open
        movem.l (%sp),%d2/%d6-%d7
        lea     12(%sp),%sp
        rts

| Release this page's Rate when the preset no longer has a negative-amount cord aimed at
| it. The gap word can still be the sum from the last note. A negative amount whose
| controller is idle stays held until that note's cord pass, which is what sums it.
| The hook runs before the opener stores the cached page at PAGE_OBJ (0xCC1CC does that), so
| this stores it first. Otherwise rate_slot sees the previous screen and the cached widget
| stays grey after the release.
        .globl  rate_open
rate_open:
        move.l  PAGE_ID,%d0
        moveq   #0x12,%d1
        cmp.l   %d1,%d0
        beq.s   .Lopen1
        addq.l  #1,%d1
        cmp.l   %d1,%d0
        bne.s   .Lopen9
        moveq   #107,%d2                | Lfo2Ck
        bra.s   .Lscan
.Lopen1:
        moveq   #98,%d2                 | Lfo1Ck
.Lscan:
        move.l  EDIT_VOICE,%a0
        move.l  %a0,%d0
        beq.s   .Lopen9
        lea     CORDS(%a0),%a0
        moveq   #24,%d1
.Lcord:
        tst.b   (%a0)
        beq.s   .Lnext
        moveq   #0,%d0
        move.b  1(%a0),%d0
        cmp.l   %d2,%d0
        bne.s   .Lnext
        tst.b   2(%a0)                  | panel amount. Zero and above never engage.
        bmi.s   .Lopen9
.Lnext:
        addq.l  #4,%a0
        subq.l  #1,%d1
        bne.s   .Lcord
        bsr     rate_page
        move.l  %a0,%d0
        beq.s   .Lgap
        move.l  %a0,PAGE_OBJ
.Lgap:  moveq   #0,%d0                  | idle gap. LFO 2 keeps the stock 1.
        moveq   #1,%d1
        cmpi.l  #98,%d2
        beq.s   .Lpub
        moveq   #1,%d0
        moveq   #0,%d1                  | LFO 2
.Lpub:
        bsr     rate_ui
.Lopen9:
        rts
