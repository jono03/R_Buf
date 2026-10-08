//////////////////////////////////////////////////////////////////////////////////
// trace_log.h (R_Buf project, firmware-spec section 3)
//
// Per-request trace log for host read slice requests. Everything is compiled out
// when TRACE_ENABLE is 0 (hooks expand to nothing).
//
// Log layout in DRAM (uncached, read it with JTAG `xsct mrd`):
//   TRACE_BASE_ADDR + 0x0000 : TRACE_HDR  (4KB)
//   TRACE_BASE_ADDR + 0x1000 : TRACE_REC[TRACE_MAX_RECORDS]  (64B each)
// All time differences in a record are (XTime difference) >> TRACE_TIME_SHIFT,
// relative to tFetch (XTime counts, 64-bit). See header fields countsPerSecond/timeShift.
//////////////////////////////////////////////////////////////////////////////////

#ifndef TRACE_LOG_H_
#define TRACE_LOG_H_

#include "ftl_config.h"

#ifndef TRACE_BASE_ADDR
#define TRACE_BASE_ADDR			0x00300000	//RESERVED0 (uncached, unused), see memory_map.h / main.c
#endif
#ifndef TRACE_MAX_RECORDS
#define TRACE_MAX_RECORDS		500000
#endif
#ifndef TRACE_UART_DUMP
#define TRACE_UART_DUMP			0			//1 = dump the log over UART when the device has been idle for 5 s (fallback when JTAG dump does not work)
#endif
#ifndef TRACE_UART_MIN_MS
#define TRACE_UART_MIN_MS		0			//with TRACE_UART_DUMP: only records whose firmware-internal latency >= this many ms (0 = all)
#endif
#ifndef TRACE_TIME_SHIFT
#define TRACE_TIME_SHIFT		6			//unit = 64 XTime counts (about 0.19 us), int32 range about 413 s
#endif

#define TRACE_HDR_BYTES			0x1000
#define TRACE_MAGIC				0x45435254	//"TRCE"
#define TRACE_FORMAT_VERSION	3

//TRACE_REC.flags
#define TRACE_F_BUF_HIT			0x0001	//b0: buffer hit, no NAND request of its own
#define TRACE_F_RBUF_ENTRY		0x0002	//b1: the buffer entry belongs to the R-Buf read list
#define TRACE_F_GC_OVERLAP		0x0004	//b2: reserved (December)
#define TRACE_F_SATURATED		0x0008	//b3: a difference did not fit in int32 and was clamped
#define TRACE_F_UNMAPPED		0x0010	//b4: unmapped address, no NAND access

typedef struct _TRACE_REC {
	unsigned int  seq;				//record sequence number
	unsigned int  lba;				//start LBA of the host command
	unsigned long long tFetch;		//XTime when the read command handling started
	int dBufAlloc;					//all fields below: (t - tFetch) >> TRACE_TIME_SHIFT, may be negative
	int dEnqueue;					//PutToNandReqQ
	int dDieLastDone;				//completion of the previous request on that die (seen at trigger issue)
	int dIssue;						//IssueNandReq for REQ_CODE_READ (read trigger)
	int dNandDone;					//transfer completion confirmed (request done)
	int dDmaStart;					//host DMA issued
	int dDmaEnd;					//host DMA completion confirmed
	unsigned short flags;
	unsigned short aheadCnt;		//requests in the die queue when this read was inserted
	int dXferIssue;					//IssueNandReq for REQ_CODE_READ_TRANSFER
	int dTrigDone;					//trigger completion confirmed (reqCode becomes READ_TRANSFER)
	unsigned short schedTrig;		//(v3) SchedulingNandReq() calls between trigger issue and trigger done (clamped to 65535)
	unsigned short schedXfer;		//(v3) SchedulingNandReq() calls between transfer issue and transfer done
	unsigned char pad[4];
} TRACE_REC;

typedef char trace_rec_size_must_be_64[(sizeof(TRACE_REC) == 64) ? 1 : -1];

typedef struct _TRACE_HDR {
	unsigned int magic;
	unsigned int version;
	unsigned int recCount;			//records stored
	unsigned int stopFlag;			//1 = log full, recording stopped
	unsigned int rbuf;				//RBUF_ENABLE
	unsigned int trace;				//TRACE_ENABLE
	unsigned int verify;			//VERIFY_PRINT
	unsigned int rbufEntries;		//read entries (0 when R-Buf is off)
	unsigned int countsPerSecond;	//COUNTS_PER_SECOND of XTime
	unsigned int timeShift;			//TRACE_TIME_SHIFT
	unsigned int maxRecords;
	unsigned int recBytes;			//64
	unsigned int recOffset;			//TRACE_HDR_BYTES
	unsigned int gcCnt;				//counters (copied at every record)
	unsigned int bufEvictCnt;
	unsigned int bufReadEvictCnt;
	unsigned int rbufReadAllocCnt;
	unsigned int rbufWriteHitInvalidateCnt;
	unsigned int dropped;			//reads whose record was lost (log full)
} TRACE_HDR;

#if (TRACE_ENABLE == 1)

void TraceInit(void);
void TraceSlotAlloc(unsigned int reqSlotTag);
void TraceSchedTick(void);
void TraceIdleDump(unsigned int idle);
void TraceSetFetch(void);
void TraceBegin(unsigned int reqSlotTag, unsigned int reqCode, unsigned int startLba);
void TraceBufAlloc(unsigned int reqSlotTag);
void TraceEntry(unsigned int reqSlotTag, unsigned int bufEntry, unsigned int hit);
void TraceUnmapped(unsigned int reqSlotTag);
void TraceLink(unsigned int nandReqSlotTag, unsigned int originReqSlotTag);
void TraceEnqueue(unsigned int nandReqSlotTag, unsigned int aheadCnt);
void TraceTrigIssue(unsigned int nandReqSlotTag, unsigned int chNo, unsigned int wayNo);
void TraceTrigDone(unsigned int nandReqSlotTag);
void TraceXferIssue(unsigned int nandReqSlotTag);
void TraceNandDone(unsigned int nandReqSlotTag);
void TraceDieDone(unsigned int chNo, unsigned int wayNo);
void TraceDmaStart(unsigned int reqSlotTag);
void TraceDmaEnd(unsigned int reqSlotTag);

#define TRACE_INIT()							TraceInit()
#define TRACE_SLOT_ALLOC(tag)					TraceSlotAlloc(tag)
#define TRACE_SCHED_TICK()						TraceSchedTick()
#define TRACE_IDLE_DUMP(idle)					TraceIdleDump(idle)
#define TRACE_SET_FETCH()						TraceSetFetch()
#define TRACE_BEGIN(tag, code, lba)				TraceBegin((tag), (code), (lba))
#define TRACE_BUF_ALLOC(tag)					TraceBufAlloc(tag)
#define TRACE_ENTRY(tag, entry, hit)			TraceEntry((tag), (entry), (hit))
#define TRACE_UNMAPPED(tag)						TraceUnmapped(tag)
#define TRACE_LINK(nandTag, originTag)			TraceLink((nandTag), (originTag))
#define TRACE_ENQUEUE(nandTag, ahead)			TraceEnqueue((nandTag), (ahead))
#define TRACE_TRIG_ISSUE(nandTag, ch, way)		TraceTrigIssue((nandTag), (ch), (way))
#define TRACE_TRIG_DONE(nandTag)				TraceTrigDone(nandTag)
#define TRACE_XFER_ISSUE(nandTag)				TraceXferIssue(nandTag)
#define TRACE_NAND_DONE(nandTag)				TraceNandDone(nandTag)
#define TRACE_DIE_DONE(ch, way)					TraceDieDone((ch), (way))
#define TRACE_DMA_START(tag)					TraceDmaStart(tag)
#define TRACE_DMA_END(tag)						TraceDmaEnd(tag)

#else

#define TRACE_INIT()							do {} while(0)
#define TRACE_SLOT_ALLOC(tag)					do {} while(0)
#define TRACE_SCHED_TICK()						do {} while(0)
#define TRACE_IDLE_DUMP(idle)					do {} while(0)
#define TRACE_SET_FETCH()						do {} while(0)
#define TRACE_BEGIN(tag, code, lba)				do {} while(0)
#define TRACE_BUF_ALLOC(tag)					do {} while(0)
#define TRACE_ENTRY(tag, entry, hit)			do {} while(0)
#define TRACE_UNMAPPED(tag)						do {} while(0)
#define TRACE_LINK(nandTag, originTag)			do {} while(0)
#define TRACE_ENQUEUE(nandTag, ahead)			do {} while(0)
#define TRACE_TRIG_ISSUE(nandTag, ch, way)		do {} while(0)
#define TRACE_TRIG_DONE(nandTag)				do {} while(0)
#define TRACE_XFER_ISSUE(nandTag)				do {} while(0)
#define TRACE_NAND_DONE(nandTag)				do {} while(0)
#define TRACE_DIE_DONE(ch, way)					do {} while(0)
#define TRACE_DMA_START(tag)					do {} while(0)
#define TRACE_DMA_END(tag)						do {} while(0)

#endif

#endif /* TRACE_LOG_H_ */
