typedef struct { unsigned int inReadList : 1; } DBE;
typedef struct { DBE dataBuf[128]; } DBM;
extern DBM *dataBufMapPtr;
extern unsigned int bufEvictCnt, bufReadEvictCnt, rbufReadAllocCnt, rbufWriteHitInvalidateCnt;
