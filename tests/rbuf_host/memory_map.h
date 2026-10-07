#include <stdlib.h>
#include "data_buffer.h"
#define LSA_NONE 0xffffffff
#define REQ_SLOT_TAG_NONE 0xffff
#define REQ_CODE_READ 1
#define REQ_CODE_WRITE 2
typedef struct { unsigned int logicalSliceAddr, reqCode, prevBlockingReq, nextBlockingReq; } REQ;
typedef struct { REQ reqPool[8]; } REQPOOL;
extern REQPOOL *reqPoolPtr;
extern unsigned char mem[1<<20];
#define DATA_BUFFER_MAP_ADDR (mem)
#define DATA_BUFFFER_HASH_TABLE_ADDR (mem+4096)
#define TEMPORARY_DATA_BUFFER_MAP_ADDR (mem+16384)
