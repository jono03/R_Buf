//////////////////////////////////////////////////////////////////////////////////
// trace_log.c (R_Buf project, firmware-spec section 3)
//
// Per-request trace log for host read slice requests.
//
// A host read goes through two requests:
//   A: slice request (reqSlotTag of the host read), becomes the TxDMA request
//   B: NAND request created by DataReadFromNand() (trigger -> READ_TRANSFER)
// Timestamps are collected per slot in TRACE_TMP (indexed by A's reqSlotTag) and
// written as one TRACE_REC when A's host DMA completion is confirmed.
// B -> A is remembered in traceOrigin[] (indexed by B's reqSlotTag).
//////////////////////////////////////////////////////////////////////////////////

#include "trace_log.h"

#if (TRACE_ENABLE == 1)

#include "xil_printf.h"
#include "xtime_l.h"
#include "memory_map.h"
#include "request_allocation.h"
#include "data_buffer.h"
#include "garbage_collection.h"

#define TRACE_ORIGIN_NONE	0xffff

typedef struct _TRACE_TMP {
	XTime tFetch;
	XTime tBuf;
	XTime tEnq;
	XTime tDieLast;
	XTime tIssue;
	XTime tTrigDone;
	XTime tXferIssue;
	XTime tNandDone;
	XTime tDmaStart;
	unsigned int lba;
	unsigned short flags;
	unsigned short aheadCnt;
	unsigned int schedAtIssue;
	unsigned int schedAtXfer;
	unsigned short schedTrig;
	unsigned short schedXfer;
	unsigned int valid;
} TRACE_TMP;

static TRACE_TMP traceTmp[AVAILABLE_OUNTSTANDING_REQ_COUNT];
static unsigned short traceOrigin[AVAILABLE_OUNTSTANDING_REQ_COUNT];
static XTime traceDieLastDone[USER_CHANNELS][USER_WAYS];
static XTime traceCurFetch;
static unsigned int traceSeq;
static unsigned int traceSchedCnt;
static unsigned int traceRecCountCache;

#define TRACE_HDR_PTR	((volatile TRACE_HDR*)TRACE_BASE_ADDR)
#define TRACE_REC_PTR	((volatile unsigned int*)(TRACE_BASE_ADDR + TRACE_HDR_BYTES))

static void TraceSyncHeader(void)
{
	volatile TRACE_HDR* hdr = TRACE_HDR_PTR;

	hdr->gcCnt = gcCnt;
	hdr->bufEvictCnt = bufEvictCnt;
	hdr->bufReadEvictCnt = bufReadEvictCnt;
	hdr->rbufReadAllocCnt = rbufReadAllocCnt;
	hdr->rbufWriteHitInvalidateCnt = rbufWriteHitInvalidateCnt;
}

void TraceInit(void)
{
	volatile TRACE_HDR* hdr = TRACE_HDR_PTR;
	unsigned int i;

	for(i = 0; i < AVAILABLE_OUNTSTANDING_REQ_COUNT; i++)
	{
		traceTmp[i].valid = 0;
		traceOrigin[i] = TRACE_ORIGIN_NONE;
	}
	for(i = 0; i < USER_CHANNELS * USER_WAYS; i++)
		traceDieLastDone[i / USER_WAYS][i % USER_WAYS] = 0;
	traceCurFetch = 0;
	traceSeq = 0;
	traceSchedCnt = 0;
	traceRecCountCache = 0;

	hdr->magic = TRACE_MAGIC;
	hdr->version = TRACE_FORMAT_VERSION;
	hdr->recCount = 0;
	hdr->stopFlag = 0;
	hdr->rbuf = RBUF_ENABLE;
	hdr->trace = TRACE_ENABLE;
	hdr->verify = VERIFY_PRINT;
	hdr->rbufEntries = RBUF_ENABLE ? RBUF_ENTRY_COUNT : 0;
	hdr->countsPerSecond = (unsigned int)COUNTS_PER_SECOND;
	hdr->timeShift = TRACE_TIME_SHIFT;
	hdr->maxRecords = TRACE_MAX_RECORDS;
	hdr->recBytes = sizeof(TRACE_REC);
	hdr->recOffset = TRACE_HDR_BYTES;
	hdr->dropped = 0;
	TraceSyncHeader();

	xil_printf("[ TRACE base=0x%08X max=%d shift=%d counts/s=%d ]\r\n",
		TRACE_BASE_ADDR, TRACE_MAX_RECORDS, TRACE_TIME_SHIFT, (unsigned int)COUNTS_PER_SECOND);
}

//B slot -> A slot, only while A is a live traced read
static unsigned int TraceOriginOf(unsigned int nandReqSlotTag)
{
	unsigned int a = traceOrigin[nandReqSlotTag];

	if(a == TRACE_ORIGIN_NONE || !traceTmp[a].valid)
		return TRACE_ORIGIN_NONE;
	return a;
}

//called whenever a request slot is taken from the free queue: drop any stale B->A link
void TraceSlotAlloc(unsigned int reqSlotTag)
{
	traceOrigin[reqSlotTag] = TRACE_ORIGIN_NONE;
}

void TraceSchedTick(void)
{
	traceSchedCnt++;
}

void TraceSetFetch(void)
{
	XTime_GetTime(&traceCurFetch);
}

void TraceBegin(unsigned int reqSlotTag, unsigned int reqCode, unsigned int startLba)
{
	TRACE_TMP* t;

	if(reqCode != REQ_CODE_READ)
		return;

	t = &traceTmp[reqSlotTag];
	t->tFetch = traceCurFetch;
	t->tBuf = 0;
	t->tEnq = 0;
	t->tDieLast = 0;
	t->tIssue = 0;
	t->tTrigDone = 0;
	t->tXferIssue = 0;
	t->tNandDone = 0;
	t->tDmaStart = 0;
	t->lba = startLba;
	t->flags = 0;
	t->aheadCnt = 0;
	t->schedAtIssue = 0;
	t->schedAtXfer = 0;
	t->schedTrig = 0;
	t->schedXfer = 0;
	t->valid = 1;
}

void TraceBufAlloc(unsigned int reqSlotTag)
{
	if(traceTmp[reqSlotTag].valid)
		XTime_GetTime(&traceTmp[reqSlotTag].tBuf);
}

void TraceEntry(unsigned int reqSlotTag, unsigned int bufEntry, unsigned int hit)
{
	TRACE_TMP* t = &traceTmp[reqSlotTag];

	if(!t->valid)
		return;

	if(hit)
		t->flags |= TRACE_F_BUF_HIT;
#if (RBUF_ENABLE == 1)
	if(dataBufMapPtr->dataBuf[bufEntry].inReadList)
		t->flags |= TRACE_F_RBUF_ENTRY;
#endif
}

void TraceUnmapped(unsigned int reqSlotTag)
{
	if(traceTmp[reqSlotTag].valid)
		traceTmp[reqSlotTag].flags |= TRACE_F_UNMAPPED;
}

void TraceLink(unsigned int nandReqSlotTag, unsigned int originReqSlotTag)
{
	if(traceTmp[originReqSlotTag].valid)
		traceOrigin[nandReqSlotTag] = originReqSlotTag;
	else
		traceOrigin[nandReqSlotTag] = TRACE_ORIGIN_NONE;
}

void TraceEnqueue(unsigned int nandReqSlotTag, unsigned int aheadCnt)
{
	unsigned int a = TraceOriginOf(nandReqSlotTag);

	if(a == TRACE_ORIGIN_NONE)
		return;

	XTime_GetTime(&traceTmp[a].tEnq);
	traceTmp[a].aheadCnt = (aheadCnt > 0xffff) ? 0xffff : aheadCnt;
}

void TraceTrigIssue(unsigned int nandReqSlotTag, unsigned int chNo, unsigned int wayNo)
{
	unsigned int a = TraceOriginOf(nandReqSlotTag);

	if(a == TRACE_ORIGIN_NONE)
		return;

	XTime_GetTime(&traceTmp[a].tIssue);
	traceTmp[a].tDieLast = traceDieLastDone[chNo][wayNo];
	traceTmp[a].schedAtIssue = traceSchedCnt;
}

void TraceTrigDone(unsigned int nandReqSlotTag)
{
	unsigned int a = TraceOriginOf(nandReqSlotTag);

	if(a != TRACE_ORIGIN_NONE)
	{
		unsigned int d = traceSchedCnt - traceTmp[a].schedAtIssue;

		XTime_GetTime(&traceTmp[a].tTrigDone);
		traceTmp[a].schedTrig = (d > 0xffff) ? 0xffff : d;
	}
}

void TraceXferIssue(unsigned int nandReqSlotTag)
{
	unsigned int a = TraceOriginOf(nandReqSlotTag);

	if(a != TRACE_ORIGIN_NONE)
	{
		XTime_GetTime(&traceTmp[a].tXferIssue);
		traceTmp[a].schedAtXfer = traceSchedCnt;
	}
}

void TraceNandDone(unsigned int nandReqSlotTag)
{
	unsigned int a = TraceOriginOf(nandReqSlotTag);

	if(a == TRACE_ORIGIN_NONE)
		return;

	{
		unsigned int d = traceSchedCnt - traceTmp[a].schedAtXfer;

		XTime_GetTime(&traceTmp[a].tNandDone);
		traceTmp[a].schedXfer = (d > 0xffff) ? 0xffff : d;
	}
	traceOrigin[nandReqSlotTag] = TRACE_ORIGIN_NONE;
}

void TraceDieDone(unsigned int chNo, unsigned int wayNo)
{
	XTime_GetTime(&traceDieLastDone[chNo][wayNo]);
}

void TraceDmaStart(unsigned int reqSlotTag)
{
	if(traceTmp[reqSlotTag].valid)
		XTime_GetTime(&traceTmp[reqSlotTag].tDmaStart);
}

//(t - base) >> TRACE_TIME_SHIFT as int32, clamped (flag b3). 0 means "not recorded".
static int TraceDiff(XTime t, XTime base, unsigned short* flags)
{
	long long d;

	if(t == 0)
		return 0;

	d = ((long long)t - (long long)base) >> TRACE_TIME_SHIFT;
	if(d > 2147483647LL)
	{
		*flags |= TRACE_F_SATURATED;
		return 2147483647;
	}
	if(d < -2147483647LL - 1)
	{
		*flags |= TRACE_F_SATURATED;
		return (-2147483647 - 1);
	}
	return (int)d;
}

void TraceDmaEnd(unsigned int reqSlotTag)
{
	TRACE_TMP* t = &traceTmp[reqSlotTag];
	volatile TRACE_HDR* hdr = TRACE_HDR_PTR;
	TRACE_REC rec;
	XTime tEnd;
	unsigned int i;
	volatile unsigned int* dst;
	unsigned int* src;

	if(!t->valid)
		return;

	XTime_GetTime(&tEnd);
	t->valid = 0;

	if(hdr->recCount >= TRACE_MAX_RECORDS)
	{
		hdr->stopFlag = 1;
		hdr->dropped++;
		return;
	}

	for(i = 0; i < sizeof(TRACE_REC); i++)
		((unsigned char*)&rec)[i] = 0;

	rec.seq = traceSeq++;
	rec.lba = t->lba;
	rec.tFetch = t->tFetch;
	rec.flags = t->flags;
	rec.aheadCnt = t->aheadCnt;
	rec.schedTrig = t->schedTrig;
	rec.schedXfer = t->schedXfer;
	rec.dBufAlloc = TraceDiff(t->tBuf, t->tFetch, &rec.flags);
	rec.dEnqueue = TraceDiff(t->tEnq, t->tFetch, &rec.flags);
	rec.dDieLastDone = TraceDiff(t->tDieLast, t->tFetch, &rec.flags);
	rec.dIssue = TraceDiff(t->tIssue, t->tFetch, &rec.flags);
	rec.dXferIssue = TraceDiff(t->tXferIssue, t->tFetch, &rec.flags);
	rec.dTrigDone = TraceDiff(t->tTrigDone, t->tFetch, &rec.flags);
	rec.dNandDone = TraceDiff(t->tNandDone, t->tFetch, &rec.flags);
	rec.dDmaStart = TraceDiff(t->tDmaStart, t->tFetch, &rec.flags);
	rec.dDmaEnd = TraceDiff(tEnd, t->tFetch, &rec.flags);

	//word-wise copy into the uncached log (aligned, no 64-bit accesses)
	dst = TRACE_REC_PTR + (hdr->recCount * (sizeof(TRACE_REC) / 4));
	src = (unsigned int*)&rec;
	for(i = 0; i < sizeof(TRACE_REC) / 4; i++)
		dst[i] = src[i];

	hdr->recCount++;
	traceRecCountCache = hdr->recCount;
	TraceSyncHeader();
}

#if (TRACE_UART_DUMP == 1)
//Fallback when JTAG cannot read the log: after the device has been idle for 5 s (no new record, nothing in flight),
//print the log once as hex text lines: "[TRC] H <19 words>" and "[TRC] R <idx> <16 words>" (tools/trace_uart2bin.py).
void TraceIdleDump(unsigned int idle)
{
	static XTime lastChange = 0;
	static unsigned int lastCnt = 0;
	static unsigned int dumped = 0;
	volatile TRACE_HDR* hdr = TRACE_HDR_PTR;
	volatile unsigned int* w;
	XTime now;
	unsigned int i, j, n, printed;

	if(dumped)
		return;

	XTime_GetTime(&now);
	if(!idle || traceRecCountCache != lastCnt)
	{
		lastCnt = traceRecCountCache;
		lastChange = now;
		return;
	}
	if(lastCnt == 0 || (now - lastChange) < (XTime)5 * COUNTS_PER_SECOND)
		return;

	dumped = 1;
	n = hdr->recCount;
	TraceSyncHeader();
	xil_printf("[TRC] BEGIN n=%d\r\n", n);

	w = (volatile unsigned int*)TRACE_BASE_ADDR;
	xil_printf("[TRC] H");
	for(j = 0; j < sizeof(TRACE_HDR) / 4; j++)
		xil_printf(" %08x", w[j]);
	xil_printf("\r\n");

	printed = 0;
	for(i = 0; i < n; i++)
	{
		w = TRACE_REC_PTR + i * (sizeof(TRACE_REC) / 4);
#if (TRACE_UART_MIN_MS > 0)
		{
			//dDmaEnd is word 10 of the record (offset 40)
			long long ticks = (long long)(int)w[10];
			long long limit = ((long long)TRACE_UART_MIN_MS * (long long)COUNTS_PER_SECOND / 1000) >> TRACE_TIME_SHIFT;
			if(ticks < limit)
				continue;
		}
#endif
		xil_printf("[TRC] R %d", i);
		for(j = 0; j < sizeof(TRACE_REC) / 4; j++)
			xil_printf(" %08x", w[j]);
		xil_printf("\r\n");
		printed++;
	}
	xil_printf("[TRC] END printed=%d\r\n", printed);
}
#else
void TraceIdleDump(unsigned int idle)
{
}
#endif

#endif
