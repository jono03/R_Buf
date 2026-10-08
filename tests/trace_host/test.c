#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "trace_log.h"
#include "xtime_l.h"
#include "data_buffer.h"

XTime fakeNow;
DBM dm; DBM *dataBufMapPtr = &dm;
unsigned int bufEvictCnt = 1, bufReadEvictCnt = 2, rbufReadAllocCnt = 3, rbufWriteHitInvalidateCnt = 4, gcCnt = 5;
extern char traceMem[];

static int fails = 0;
#define CHECK(c) do { if(!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while(0)

static volatile TRACE_HDR *H(void) { return (volatile TRACE_HDR*)traceMem; }
static TRACE_REC *R(int i) { return (TRACE_REC*)(traceMem + TRACE_HDR_BYTES + i * 64); }

int main(void)
{
	TRACE_REC *r;

	dm.dataBuf[3].inReadList = 1;
	dm.dataBuf[20].inReadList = 0;
	TRACE_INIT();
	CHECK(H()->magic == TRACE_MAGIC && H()->version == 3 && H()->recBytes == 64 && H()->recOffset == 0x1000);
	CHECK(H()->timeShift == 0 && H()->rbufEntries == 8 && H()->gcCnt == 5);

	/* read 1: miss, own NAND request (A=5, B=9), die queue wait */
	fakeNow = 1000; TRACE_SET_FETCH();
	TRACE_BEGIN(5, 0x08, 1234);
	fakeNow = 1100; TRACE_BUF_ALLOC(5);
	TRACE_ENTRY(5, 3, 0);
	TRACE_LINK(9, 5);
	fakeNow = 1500; TRACE_ENQUEUE(9, 2);
	fakeNow = 1600; TRACE_DIE_DONE(0, 1);
	TRACE_SCHED_TICK(); TRACE_SCHED_TICK();
	fakeNow = 2000; TRACE_TRIG_ISSUE(9, 0, 1);
	TRACE_SCHED_TICK(); TRACE_SCHED_TICK(); TRACE_SCHED_TICK();
	fakeNow = 3000; TRACE_TRIG_DONE(9);
	for(int k = 0; k < 4; k++) TRACE_SCHED_TICK();
	fakeNow = 3500; TRACE_XFER_ISSUE(9);
	for(int k = 0; k < 5; k++) TRACE_SCHED_TICK();
	fakeNow = 4000; TRACE_NAND_DONE(9);
	fakeNow = 4200; TRACE_DMA_START(5);
	fakeNow = 5000; TRACE_DMA_END(5);
	CHECK(H()->recCount == 1);
	r = R(0);
	CHECK(r->seq == 0 && r->lba == 1234 && r->tFetch == 1000);
	CHECK(r->dBufAlloc == 100 && r->dEnqueue == 500 && r->dDieLastDone == 600);
	CHECK(r->dIssue == 1000 && r->dTrigDone == 2000 && r->dXferIssue == 2500);
	CHECK(r->dNandDone == 3000 && r->dDmaStart == 3200 && r->dDmaEnd == 4000);
	CHECK(r->flags == TRACE_F_RBUF_ENTRY && r->aheadCnt == 2);
	CHECK(r->schedTrig == 3 && r->schedXfer == 5);
	CHECK(r->schedDieQ == 2 && r->schedXferWait == 4);

	/* write request must be ignored */
	TRACE_BEGIN(6, 0x00, 77);
	fakeNow = 6000; TRACE_DMA_END(6);
	CHECK(H()->recCount == 1);

	/* stale B tag after completion must not touch the next read (A=7 reuses nothing) */
	fakeNow = 7000; TRACE_SET_FETCH();
	TRACE_BEGIN(7, 0x08, 4000);
	fakeNow = 7100; TRACE_BUF_ALLOC(7);
	TRACE_ENTRY(7, 20, 1);			/* buffer hit on a write-list entry */
	TRACE_ENQUEUE(9, 0);			/* B=9 was cleared at NAND_DONE -> ignored */
	fakeNow = 7300; TRACE_DMA_START(7);
	fakeNow = 7400; TRACE_DMA_END(7);
	CHECK(H()->recCount == 2);
	r = R(1);
	CHECK(r->seq == 1 && r->flags == TRACE_F_BUF_HIT && r->dEnqueue == 0 && r->dIssue == 0 && r->dNandDone == 0);
	CHECK(r->dBufAlloc == 100 && r->dDmaStart == 300 && r->dDmaEnd == 400);

	/* unmapped read */
	fakeNow = 8000; TRACE_SET_FETCH();
	TRACE_BEGIN(8, 0x08, 5000);
	fakeNow = 8050; TRACE_BUF_ALLOC(8);
	TRACE_ENTRY(8, 3, 0);
	TRACE_UNMAPPED(8);
	fakeNow = 8100; TRACE_DMA_START(8);
	fakeNow = 8200; TRACE_DMA_END(8);
	r = R(2);
	CHECK((r->flags & TRACE_F_UNMAPPED) && (r->flags & TRACE_F_RBUF_ENTRY) && r->dDmaEnd == 200);

	/* B linked to a non-traced A (write RMW read) is ignored */
	TRACE_LINK(10, 6);
	fakeNow = 9000; TRACE_ENQUEUE(10, 1); TRACE_TRIG_ISSUE(10, 0, 0);
	CHECK(H()->recCount == 3);

	/* stale B->A link: B slot 20 linked to live A=15, then B slot is re-allocated (TRACE_SLOT_ALLOC) */
	fakeNow = 500; TRACE_SET_FETCH();
	TRACE_BEGIN(15, 0x08, 7000);
	TRACE_LINK(20, 15);
	TRACE_SLOT_ALLOC(20);				/* slot 20 reused by some other request */
	fakeNow = 600; TRACE_ENQUEUE(20, 9);	/* must not touch A=15 */
	fakeNow = 700; TRACE_DMA_END(15);
	CHECK(H()->recCount == 4);
	r = R(3);
	CHECK(r->lba == 7000 && r->dEnqueue == 0 && r->aheadCnt == 0 && r->dDmaEnd == 200);

	/* link to an A that finished first (valid=0) is ignored, even if the slot number is reused by a new read */
	fakeNow = 800; TRACE_SET_FETCH();
	TRACE_BEGIN(16, 0x08, 8000);
	TRACE_LINK(21, 16);
	fakeNow = 850; TRACE_DMA_END(16);		/* A done, record 5 */
	TRACE_BEGIN(16, 0x08, 8001);			/* new read in the same slot (no TRACE_SLOT_ALLOC for 21 yet) */
	TRACE_SLOT_ALLOC(21);
	fakeNow = 860; TRACE_ENQUEUE(21, 4);
	fakeNow = 900; TRACE_DMA_END(16);		/* record 6 */
	CHECK(H()->recCount == 6);
	r = R(5);
	CHECK(r->lba == 8001 && r->dEnqueue == 0 && r->aheadCnt == 0);

	/* saturation: 100 s with shift 0 does not fit */
	fakeNow = 1000; TRACE_SET_FETCH();
	TRACE_BEGIN(11, 0x08, 6000);
	fakeNow = 1000ULL + 5000000000ULL; TRACE_DMA_END(11);
	r = R(6);
	CHECK((r->flags & TRACE_F_SATURATED) && r->dDmaEnd == 2147483647);

	/* log full: max records is 4 in this test build, the saturation record was the 4th */
	CHECK(H()->recCount == 7 && H()->stopFlag == 0);
	fakeNow = 10; TRACE_SET_FETCH();
	TRACE_BEGIN(12, 0x08, 1); fakeNow = 20; TRACE_DMA_END(12);
	CHECK(H()->recCount == 8 && H()->stopFlag == 0);
	TRACE_BEGIN(13, 0x08, 2); fakeNow = 30; TRACE_DMA_END(13);
	CHECK(H()->recCount == 8 && H()->stopFlag == 1 && H()->dropped == 1);
	TRACE_BEGIN(14, 0x08, 3); fakeNow = 40; TRACE_DMA_END(14);
	CHECK(H()->recCount == 8 && H()->dropped == 2);

	printf(fails ? "TRACE HOST TEST FAILED (%d)\n" : "TRACE HOST TEST PASSED\n", fails);
	return fails != 0;
}
