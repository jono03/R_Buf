#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "memory_map.h"
extern P_DATA_BUF_HASH_TABLE dataBufHashTablePtr;
unsigned char mem[1<<20]; REQPOOL pool; REQPOOL *reqPoolPtr=&pool;
static void check(void){
  int n=AVAILABLE_DATA_BUFFER_ENTRY_COUNT, seen[256]={0}, cnt;
  DATA_BUF_LRU_LIST *ls[2]={&dataBufLruList,&rbufLruList};
  for(int l=0;l<(RBUF_ENABLE?2:1);l++){ cnt=0; unsigned e=ls[l]->headEntry,p=DATA_BUF_NONE;
    while(e!=DATA_BUF_NONE){ assert(dataBufMapPtr->dataBuf[e].prevEntry==p); assert(!seen[e]++); 
      if(RBUF_ENABLE){ assert(dataBufMapPtr->dataBuf[e].inReadList==(l==1)); if(l==1) assert(!dataBufMapPtr->dataBuf[e].dirty);} 
      p=e; e=dataBufMapPtr->dataBuf[e].nextEntry; cnt++; }
    assert(p==ls[l]->tailEntry); }
  for(int i=0;i<n;i++) assert(seen[i]==1);
  /* no duplicate LSA, hash finds each valid entry */
  for(int i=0;i<n;i++){ unsigned a=dataBufMapPtr->dataBuf[i].logicalSliceAddr; if(a==LSA_NONE)continue;
    for(int j=i+1;j<n;j++) assert(dataBufMapPtr->dataBuf[j].logicalSliceAddr!=a);
    unsigned h=dataBufHashTablePtr->dataBufHash[FindDataBufHashTableEntry(a)].headEntry,f=0;
    while(h!=DATA_BUF_NONE){ if(h==(unsigned)i)f=1; h=dataBufMapPtr->dataBuf[h].hashNextEntry;} assert(f);}
}
int main(){
  InitDataBuf(); check(); srand(1);
  for(int it=0;it<200000;it++){
    unsigned lsa=rand()%100, code=(rand()%2)?REQ_CODE_READ:REQ_CODE_WRITE;
    reqPoolPtr->reqPool[0].logicalSliceAddr=lsa; reqPoolPtr->reqPool[0].reqCode=code;
    unsigned e=CheckDataBufHit(0);
    if(e==DATA_BUF_FAIL){ e=AllocateDataBuf(code);
      dataBufMapPtr->dataBuf[e].dirty=DATA_BUF_CLEAN; /* stands in for EvictDataBufEntry */
      dataBufMapPtr->dataBuf[e].logicalSliceAddr=lsa; PutToDataBufHashList(e); }
    if(code==REQ_CODE_WRITE){ assert(!RBUF_ENABLE || !dataBufMapPtr->dataBuf[e].inReadList); dataBufMapPtr->dataBuf[e].dirty=DATA_BUF_DIRTY; }
    else if(RBUF_ENABLE && dataBufMapPtr->dataBuf[e].inReadList) assert(!dataBufMapPtr->dataBuf[e].dirty);
    if(it%1000==0) check();
  }
  check(); printf("RBUF_ENABLE=%d ok readAlloc=%u writeHitInval=%u\n",RBUF_ENABLE,rbufReadAllocCnt,rbufWriteHitInvalidateCnt); return 0; }
