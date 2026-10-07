//////////////////////////////////////////////////////////////////////////////////
// data_buffer.c for Cosmos+ OpenSSD
// Copyright (c) 2017 Hanyang University ENC Lab.
// Contributed by Yong Ho Song <yhsong@enc.hanyang.ac.kr>
//				  Jaewook Kwak <jwkwak@enc.hanyang.ac.kr>
//
// This file is part of Cosmos+ OpenSSD.
//
// Cosmos+ OpenSSD is free software; you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation; either version 3, or (at your option)
// any later version.
//
// Cosmos+ OpenSSD is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
// See the GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Cosmos+ OpenSSD; see the file COPYING.
// If not, see <http://www.gnu.org/licenses/>.
//////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////////////////////////
// Company: ENC Lab. <http://enc.hanyang.ac.kr>
// Engineer: Jaewook Kwak <jwkwak@enc.hanyang.ac.kr>
//
// Project Name: Cosmos+ OpenSSD
// Design Name: Cosmos+ Firmware
// Module Name: Data Buffer Manager
// File Name: data_buffer.c
//
// Version: v1.0.0
//
// Description:
//   - manage data buffer used to transfer data between host system and NAND device
//////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////////////////////////
// Revision History:
//
// * v1.0.0
//   - First draft
//
// * v1.1.0 (2026-10-07, R_Buf project)
//   - Add optional R-Buf: split the LRU list into read/write lists (RBUF_ENABLE)
//   - Print R-Buf status at boot and every 65536 read allocations
//////////////////////////////////////////////////////////////////////////////////


#include "xil_printf.h"
#include <assert.h>
#include "memory_map.h"


P_DATA_BUF_MAP dataBufMapPtr;
DATA_BUF_LRU_LIST dataBufLruList;
DATA_BUF_LRU_LIST rbufLruList;
unsigned int rbufReadAllocCnt;
unsigned int rbufWriteHitInvalidateCnt;
P_DATA_BUF_HASH_TABLE dataBufHashTablePtr;
P_TEMPORARY_DATA_BUF_MAP tempDataBufMapPtr;

void InitDataBuf()
{
	int bufEntry;

	dataBufMapPtr = (P_DATA_BUF_MAP) DATA_BUFFER_MAP_ADDR;
	dataBufHashTablePtr = (P_DATA_BUF_HASH_TABLE)DATA_BUFFFER_HASH_TABLE_ADDR;
	tempDataBufMapPtr = (P_TEMPORARY_DATA_BUF_MAP)TEMPORARY_DATA_BUFFER_MAP_ADDR;

	for(bufEntry = 0; bufEntry < AVAILABLE_DATA_BUFFER_ENTRY_COUNT; bufEntry++)
	{
		dataBufMapPtr->dataBuf[bufEntry].logicalSliceAddr = LSA_NONE;
		dataBufMapPtr->dataBuf[bufEntry].prevEntry = bufEntry-1;
		dataBufMapPtr->dataBuf[bufEntry].nextEntry = bufEntry+1;
		dataBufMapPtr->dataBuf[bufEntry].dirty = DATA_BUF_CLEAN;
		dataBufMapPtr->dataBuf[bufEntry].blockingReqTail =  REQ_SLOT_TAG_NONE;

		dataBufHashTablePtr->dataBufHash[bufEntry].headEntry = DATA_BUF_NONE;
		dataBufHashTablePtr->dataBufHash[bufEntry].tailEntry = DATA_BUF_NONE;
		dataBufMapPtr->dataBuf[bufEntry].hashPrevEntry = DATA_BUF_NONE;
		dataBufMapPtr->dataBuf[bufEntry].hashNextEntry = DATA_BUF_NONE;
	}

#if (RBUF_ENABLE == 1)
	//R-Buf: the first RBUF_ENTRY_COUNT entries form the read list, the rest the write list
	for(bufEntry = 0; bufEntry < AVAILABLE_DATA_BUFFER_ENTRY_COUNT; bufEntry++)
		dataBufMapPtr->dataBuf[bufEntry].inReadList = (bufEntry < RBUF_ENTRY_COUNT);

	dataBufMapPtr->dataBuf[0].prevEntry = DATA_BUF_NONE;
	dataBufMapPtr->dataBuf[RBUF_ENTRY_COUNT - 1].nextEntry = DATA_BUF_NONE;
	rbufLruList.headEntry = 0;
	rbufLruList.tailEntry = RBUF_ENTRY_COUNT - 1;

	dataBufMapPtr->dataBuf[RBUF_ENTRY_COUNT].prevEntry = DATA_BUF_NONE;
	dataBufMapPtr->dataBuf[AVAILABLE_DATA_BUFFER_ENTRY_COUNT - 1].nextEntry = DATA_BUF_NONE;
	dataBufLruList.headEntry = RBUF_ENTRY_COUNT;
	dataBufLruList.tailEntry = AVAILABLE_DATA_BUFFER_ENTRY_COUNT - 1;
#else
	dataBufMapPtr->dataBuf[0].prevEntry = DATA_BUF_NONE;
	dataBufMapPtr->dataBuf[AVAILABLE_DATA_BUFFER_ENTRY_COUNT - 1].nextEntry = DATA_BUF_NONE;
	dataBufLruList.headEntry = 0 ;
	dataBufLruList.tailEntry = AVAILABLE_DATA_BUFFER_ENTRY_COUNT - 1;
#endif

	for(bufEntry = 0; bufEntry < AVAILABLE_TEMPORARY_DATA_BUFFER_ENTRY_COUNT; bufEntry++)
		tempDataBufMapPtr->tempDataBuf[bufEntry].blockingReqTail =  REQ_SLOT_TAG_NONE;

#if (RBUF_ENABLE == 1)
	xil_printf("[ R-Buf ON: read entries %d of %d ]\r\n", RBUF_ENTRY_COUNT, AVAILABLE_DATA_BUFFER_ENTRY_COUNT);
#else
	xil_printf("[ R-Buf OFF ]\r\n");
#endif
}

//LRU list that the entry belongs to (always the write/unified list when R-Buf is disabled)
static DATA_BUF_LRU_LIST* LruListOf(unsigned int bufEntry)
{
#if (RBUF_ENABLE == 1)
	if(dataBufMapPtr->dataBuf[bufEntry].inReadList)
		return &rbufLruList;
#endif
	return &dataBufLruList;
}

static void RemoveFromLru(DATA_BUF_LRU_LIST* list, unsigned int bufEntry)
{
	unsigned int prev = dataBufMapPtr->dataBuf[bufEntry].prevEntry;
	unsigned int next = dataBufMapPtr->dataBuf[bufEntry].nextEntry;

	if(prev != DATA_BUF_NONE)
		dataBufMapPtr->dataBuf[prev].nextEntry = next;
	else
		list->headEntry = next;

	if(next != DATA_BUF_NONE)
		dataBufMapPtr->dataBuf[next].prevEntry = prev;
	else
		list->tailEntry = prev;

	dataBufMapPtr->dataBuf[bufEntry].prevEntry = DATA_BUF_NONE;
	dataBufMapPtr->dataBuf[bufEntry].nextEntry = DATA_BUF_NONE;
}

static void PushToLruHead(DATA_BUF_LRU_LIST* list, unsigned int bufEntry)
{
	dataBufMapPtr->dataBuf[bufEntry].prevEntry = DATA_BUF_NONE;
	dataBufMapPtr->dataBuf[bufEntry].nextEntry = list->headEntry;

	if(list->headEntry != DATA_BUF_NONE)
		dataBufMapPtr->dataBuf[list->headEntry].prevEntry = bufEntry;
	else
		list->tailEntry = bufEntry;

	list->headEntry = bufEntry;
}

#if (RBUF_ENABLE == 1)
static void PushToLruTail(DATA_BUF_LRU_LIST* list, unsigned int bufEntry)
{
	dataBufMapPtr->dataBuf[bufEntry].nextEntry = DATA_BUF_NONE;
	dataBufMapPtr->dataBuf[bufEntry].prevEntry = list->tailEntry;

	if(list->tailEntry != DATA_BUF_NONE)
		dataBufMapPtr->dataBuf[list->tailEntry].nextEntry = bufEntry;
	else
		list->headEntry = bufEntry;

	list->tailEntry = bufEntry;
}
#endif

unsigned int CheckDataBufHit(unsigned int reqSlotTag)
{
	unsigned int bufEntry, logicalSliceAddr;
	DATA_BUF_LRU_LIST* list;

	logicalSliceAddr = reqPoolPtr->reqPool[reqSlotTag].logicalSliceAddr;
	bufEntry = dataBufHashTablePtr->dataBufHash[FindDataBufHashTableEntry(logicalSliceAddr)].headEntry;

	while(bufEntry != DATA_BUF_NONE)
	{
		if(dataBufMapPtr->dataBuf[bufEntry].logicalSliceAddr == logicalSliceAddr)
		{
			//LRU update stays inside the list the entry belongs to
			list = LruListOf(bufEntry);
			RemoveFromLru(list, bufEntry);
			PushToLruHead(list, bufEntry);

#if (RBUF_ENABLE == 1)
			if(dataBufMapPtr->dataBuf[bufEntry].inReadList &&
				reqPoolPtr->reqPool[reqSlotTag].reqCode == REQ_CODE_WRITE)
			{
				//a write must not dirty a read-buffer entry: discard the (clean) copy,
				//the write then proceeds as a miss and takes an entry from the write list
				SelectiveGetFromDataBufHashList(bufEntry);
				dataBufMapPtr->dataBuf[bufEntry].logicalSliceAddr = LSA_NONE;
				RemoveFromLru(list, bufEntry);
				PushToLruTail(list, bufEntry);
				rbufWriteHitInvalidateCnt++;
				return DATA_BUF_FAIL;
			}
#endif

			return bufEntry;
		}
		else
			bufEntry = dataBufMapPtr->dataBuf[bufEntry].hashNextEntry;
	}

	return DATA_BUF_FAIL;
}

unsigned int AllocateDataBuf(unsigned int reqCode)
{
	DATA_BUF_LRU_LIST* list = &dataBufLruList;
	unsigned int evictedEntry;

#if (RBUF_ENABLE == 1)
	//reads take victims from the read list only, writes from the write list only
	if(reqCode == REQ_CODE_READ)
	{
		list = &rbufLruList;
		rbufReadAllocCnt++;
		if((rbufReadAllocCnt & 0xFFFF) == 0)
			xil_printf("[ R-Buf read alloc=%u write-hit-invalidate=%u ]\r\n", rbufReadAllocCnt, rbufWriteHitInvalidateCnt);
	}
#endif

	evictedEntry = list->tailEntry;

	if(evictedEntry == DATA_BUF_NONE)
		assert(!"[WARNING] There is no valid buffer entry [WARNING]");

	RemoveFromLru(list, evictedEntry);
	PushToLruHead(list, evictedEntry);

#if (RBUF_ENABLE == 1)
	//read-buffer entries are always clean, so a read never waits for an eviction write
	if(list == &rbufLruList)
		assert(dataBufMapPtr->dataBuf[evictedEntry].dirty == DATA_BUF_CLEAN);
#endif

	SelectiveGetFromDataBufHashList(evictedEntry);

	return evictedEntry;
}


void UpdateDataBufEntryInfoBlockingReq(unsigned int bufEntry, unsigned int reqSlotTag)
{
	if(dataBufMapPtr->dataBuf[bufEntry].blockingReqTail != REQ_SLOT_TAG_NONE)
	{
		reqPoolPtr->reqPool[reqSlotTag].prevBlockingReq = dataBufMapPtr->dataBuf[bufEntry].blockingReqTail;
		reqPoolPtr->reqPool[reqPoolPtr->reqPool[reqSlotTag].prevBlockingReq].nextBlockingReq  = reqSlotTag;
	}

	dataBufMapPtr->dataBuf[bufEntry].blockingReqTail = reqSlotTag;
}


unsigned int AllocateTempDataBuf(unsigned int dieNo)
{
	return dieNo;
}


void UpdateTempDataBufEntryInfoBlockingReq(unsigned int bufEntry, unsigned int reqSlotTag)
{

	if(tempDataBufMapPtr->tempDataBuf[bufEntry].blockingReqTail != REQ_SLOT_TAG_NONE)
	{
		reqPoolPtr->reqPool[reqSlotTag].prevBlockingReq = tempDataBufMapPtr->tempDataBuf[bufEntry].blockingReqTail;
		reqPoolPtr->reqPool[reqPoolPtr->reqPool[reqSlotTag].prevBlockingReq].nextBlockingReq  = reqSlotTag;
	}

	tempDataBufMapPtr->tempDataBuf[bufEntry].blockingReqTail = reqSlotTag;
}

void PutToDataBufHashList(unsigned int bufEntry)
{
	unsigned int hashEntry;

	hashEntry = FindDataBufHashTableEntry(dataBufMapPtr->dataBuf[bufEntry].logicalSliceAddr);

	if(dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry != DATA_BUF_NONE)
	{
		dataBufMapPtr->dataBuf[bufEntry].hashPrevEntry = dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry ;
		dataBufMapPtr->dataBuf[bufEntry].hashNextEntry = REQ_SLOT_TAG_NONE;
		dataBufMapPtr->dataBuf[dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry].hashNextEntry = bufEntry;
		dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry = bufEntry;
	}
	else
	{
		dataBufMapPtr->dataBuf[bufEntry].hashPrevEntry = REQ_SLOT_TAG_NONE;
		dataBufMapPtr->dataBuf[bufEntry].hashNextEntry = REQ_SLOT_TAG_NONE;
		dataBufHashTablePtr->dataBufHash[hashEntry].headEntry = bufEntry;
		dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry = bufEntry;
	}
}


void SelectiveGetFromDataBufHashList(unsigned int bufEntry)
{
	if(dataBufMapPtr->dataBuf[bufEntry].logicalSliceAddr != LSA_NONE)
	{
		unsigned int prevBufEntry, nextBufEntry, hashEntry;

		prevBufEntry =  dataBufMapPtr->dataBuf[bufEntry].hashPrevEntry;
		nextBufEntry =  dataBufMapPtr->dataBuf[bufEntry].hashNextEntry;
		hashEntry = FindDataBufHashTableEntry(dataBufMapPtr->dataBuf[bufEntry].logicalSliceAddr);

		if((nextBufEntry != DATA_BUF_NONE) && (prevBufEntry != DATA_BUF_NONE))
		{
			dataBufMapPtr->dataBuf[prevBufEntry].hashNextEntry = nextBufEntry;
			dataBufMapPtr->dataBuf[nextBufEntry].hashPrevEntry = prevBufEntry;
		}
		else if((nextBufEntry == DATA_BUF_NONE) && (prevBufEntry != DATA_BUF_NONE))
		{
			dataBufMapPtr->dataBuf[prevBufEntry].hashNextEntry = DATA_BUF_NONE;
			dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry = prevBufEntry;
		}
		else if((nextBufEntry != DATA_BUF_NONE) && (prevBufEntry == DATA_BUF_NONE))
		{
			dataBufMapPtr->dataBuf[nextBufEntry].hashPrevEntry = DATA_BUF_NONE;
			dataBufHashTablePtr->dataBufHash[hashEntry].headEntry = nextBufEntry;
		}
		else
		{
			dataBufHashTablePtr->dataBufHash[hashEntry].headEntry = DATA_BUF_NONE;
			dataBufHashTablePtr->dataBufHash[hashEntry].tailEntry = DATA_BUF_NONE;
		}
	}
}




