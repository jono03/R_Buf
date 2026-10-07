typedef unsigned long long XTime;
#define COUNTS_PER_SECOND 1000000ULL
static inline void XTime_GetTime(XTime *t){ static XTime c; *t = (c += 3000000ULL); }
