/* UART dump test: build with -DTRACE_UART_DUMP=1; output goes to stdout, then tools/trace_uart2bin.py + trace_parse.py */
#include <stdio.h>
#include "trace_log.h"
#include "xtime_l.h"
#include "data_buffer.h"

XTime fakeNow;
DBM dm; DBM *dataBufMapPtr = &dm;
unsigned int bufEvictCnt = 1, bufReadEvictCnt = 0, rbufReadAllocCnt = 3, rbufWriteHitInvalidateCnt = 4, gcCnt = 0;

int main(void)
{
	int i;
	TRACE_INIT();
	for(i = 0; i < 3; i++)
	{
		fakeNow = 1000000ULL * (i + 1);
		TRACE_SET_FETCH();
		TRACE_BEGIN(5 + i, 0x08, 1000 + i);
		TRACE_BUF_ALLOC(5 + i);
		TRACE_LINK(30 + i, 5 + i);
		TRACE_ENQUEUE(30 + i, i);
		TRACE_TRIG_ISSUE(30 + i, 0, 0);
		fakeNow += 20000; TRACE_TRIG_DONE(30 + i);
		TRACE_XFER_ISSUE(30 + i);
		fakeNow += 20000; TRACE_NAND_DONE(30 + i);
		TRACE_DMA_START(5 + i);
		fakeNow += 4000 + (i == 2 ? 900000000ULL : 0); TRACE_DMA_END(5 + i);
	}
	/* busy: no dump; idle but < 5 s: no dump; idle > 5 s: one dump; again: nothing */
	fakeNow = 2000000000ULL; TRACE_IDLE_DUMP(0);
	fakeNow += 1000;         TRACE_IDLE_DUMP(1);
	fakeNow += 1000;         TRACE_IDLE_DUMP(1);
	fakeNow += 10ULL * 333333333ULL; TRACE_IDLE_DUMP(1);
	TRACE_IDLE_DUMP(1);
	return 0;
}
