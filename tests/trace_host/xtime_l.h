typedef unsigned long long XTime;
#define COUNTS_PER_SECOND 333333333
extern XTime fakeNow;
static inline void XTime_GetTime(XTime *p) { *p = fakeNow; }
