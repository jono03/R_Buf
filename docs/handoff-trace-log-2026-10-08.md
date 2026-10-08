# 인수인계: 요청별 계측 로그 (trace log) — 2026-10-08

이 문서는 계측 로그 코드를 이어서 SDK에 넣고, 빌드·부팅·덤프를 확인하는 사람을 위한 것이다.
**코드는 작성만 했고 보드에서 한 번도 돌려 보지 않았다.** ARM 컴파일러가 없는 환경에서 썼으므로 SDK 빌드 확인이 첫 작업이다.
기획·사양과 다르면 `firmware-spec.md`(코드), `team-experiment-procedure.md`(실험), `team-paper-idea.md`(결정과 이유)가 우선한다.

## 1. 한눈에 보기

| 항목 | 상태 |
|---|---|
| 코드 위치 | 저장소 `source/software/lab-rbuf/src/` (브랜치 `claude/new-session-hkspsr`, 커밋 `b33c5de`) |
| 기준 소스 | `source/software/lab-gftl3/src/` = 실습실 원본(수정 금지, diff 기준) |
| 새 파일 | `trace_log.h`, `trace_log.c` |
| 수정한 파일 | `ftl_config.h`, `data_buffer.c`, `garbage_collection.c/.h`, `request_transform.c`, `request_allocation.c`, `request_schedule.c`, `nvme/nvme_io_cmd.c` |
| PC 로직 테스트 | ✅ 통과 (`tests/trace_host/run.sh`) |
| 해석 스크립트 | ✅ 가짜 덤프로 검증 (`tools/trace_parse.py`) |
| SDK 빌드 | ❌ 아직 안 함 (**첫 할 일**) |
| 보드 부팅·동작 | ❌ 아직 안 함 |
| JTAG 덤프 | ❌ 시험 전 (`tools/trace_dump.md`의 명령은 미검증) |
| UART 출력 대안 | ❌ 코드 없음 (덤프가 안 될 때만 필요, 5절) |

## 2. 이 작업이 필요한 이유

논문 주 결과는 "R-Buf 이후에도 남는 초 단위 읽기 정지가 SSD 안 어디서 생기는가"다. 호스트 fio로는 읽기 전체 지연만 보이므로, 펌웨어 안에서 읽기 하나가 각 단계를 지나는 시각을 기록해 구간별로 나눈다.
실험은 M1(읽기 QD1)·M2(읽기 QD8) + 지속 쓰기 폭주이고, S-Buf와 R-Buf를 **같은 계측 코드가 들어간 빌드**로 측정한다(`RBUF_ENABLE`만 다름).

## 3. 해야 할 일 (순서대로)

### 3-1. SDK에 파일 넣고 빌드

1. 저장소의 `source/software/lab-rbuf/src/`에서 아래 10개를 SDK `run-rbuf/src/`에 덮어쓴다.
   `trace_log.h`, `trace_log.c`(새 파일), `ftl_config.h`, `data_buffer.c`, `garbage_collection.c`, `garbage_collection.h`, `request_transform.c`, `request_allocation.c`, `request_schedule.c`, `nvme/nvme_io_cmd.c`
2. `trace_log.c`가 새 파일이므로 SDK에서 `src` 우클릭 → **Refresh**(또는 Import)로 프로젝트에 인식시킨다.
3. `ftl_config.h`의 `RBUF_ENABLE`을 설정한다(S-Buf = 0, R-Buf = 1). 저장소 기본값은 0이다.
4. `run-rbuf` 우클릭 → **Clean Project** → **Build Project**. Problems 탭 에러가 0개여야 한다.
   - 에러가 나면 문구를 그대로 기록해서 수정한다. 새 코드에서 의심되는 곳: `trace_log.c`의 헤더 include(`request_allocation.h`, `data_buffer.h`, `garbage_collection.h`), 매크로 `TRACE_*` 사용 위치.

### 3-2. 부팅·동작 확인

1. 호스트 종료 → **Program FPGA** → `run-rbuf.elf` Launch(ELF 이름 확인) → UART 확인.
2. UART에 아래 두 줄이 나와야 한다.
   - `[ RBUF=… RBUF_ENTRIES=…/128 TRACE=1 VERIFY=0 ]`
   - `[ TRACE base=0x00300000 max=500000 shift=6 counts/s=… ]`
3. 호스트 켜고 `sudo nvme list`로 Cosmos+ 확인(번호는 부팅마다 바뀐다. 항상 모델명으로 찾는다).
4. 짧은 fio(예: 읽기 4KB 10초)로 평소처럼 동작하는지 확인. `dmesg`에 timeout/abort/reset이 없어야 한다.
5. **멈추거나 NVMe가 안 잡히면:** `request_transform.c`, `request_schedule.c`의 `TRACE_*` 호출을 하나씩 주석 처리하며 원인을 찾는다. 가장 의심할 곳은 `TraceInit()`이 있는 `data_buffer.c`의 `InitDataBuf()`(부팅 직후 0x00300000에 쓰므로 해당 영역이 uncached 미사용인지 재확인: `memory_map.h` RESERVED0, `main.c` TLB).

### 3-3. 덤프 시험 (10/8 Go/No-Go)

`tools/trace_dump.md` 참고. 요약:

```
# 짧은 fio 후, 보드를 끄지 말고
xsct
connect
targets -set -filter {name =~ "ARM*#0"}
mrd 0x00300000 8                                   # 헤더, recCount 확인
mrd -bin -file trace.bin 0x00300000 <워드수>       # 워드수 = 1024 + recCount*16
```
```
python3 tools/trace_parse.py trace.bin --csv trace.csv
```

- 헤더 `magic`이 `0x45435254`이면 덤프가 맞다.
- **통과 기준:** 레코드 수가 fio 읽기 수와 거의 같고, 읽기만 돌린 총 지연이 약 0.2~0.3 ms(기존 `rbuf2` 읽기만 평균 227 µs와 비슷)이며, 시각 필드가 아래 순서를 따른다.
  `dBufAlloc ≤ dEnqueue ≤ dIssue ≤ dTrigDone ≤ dXferIssue ≤ dNandDone ≤ dDmaStart ≤ dDmaEnd`
- 순서가 어긋난 레코드가 많으면 기록 지점이 잘못 연결된 것이다(6절 표 참고).
- **JTAG 덤프가 안 되면 5절.**

## 4. 코드 구조

### 4-1. 읽기 하나가 지나는 길과 기록 지점

호스트 읽기 하나는 요청 두 개로 나뉜다.

- **A:** 슬라이스 요청 (호스트 읽기의 `reqSlotTag`). 나중에 TxDMA 요청으로 바뀐다.
- **B:** `DataReadFromNand()`가 만드는 NAND 요청. 트리거(`REQ_CODE_READ`) → 완료 후 `REQ_CODE_READ_TRANSFER`로 바뀌어 전송 → 완료.

시각은 `reqSlotTag`로 인덱싱하는 별도 배열(`traceTmp[]`, `.bss` 약 90KB)에 모았다가 A의 호스트 DMA가 끝날 때 레코드 하나로 DRAM 로그에 쓴다. B→A 연결은 `traceOrigin[]`(B 슬롯 → A 슬롯).

| 레코드 필드 | 기록 지점 (파일: 함수) | 매크로 |
|---|---|---|
| `tFetch`, `lba` | `nvme/nvme_io_cmd.c: handle_nvme_io_read()` 시작(시각), `request_transform.c: ReqTransNvmeToSlice()` 슬라이스 생성(저장) | `TRACE_SET_FETCH`, `TRACE_BEGIN` |
| `dBufAlloc` | `request_transform.c: ReqTransSliceToLowLevel()`, 버퍼 hit 검사 직전 | `TRACE_BUF_ALLOC` |
| `flags` b0·b1 | 같은 함수, hit/miss 직후 | `TRACE_ENTRY` |
| `flags` b4 | `DataReadFromNand()`의 미매핑(`VSA_FAIL`) 분기 | `TRACE_UNMAPPED` |
| B→A 연결 | `DataReadFromNand()`에서 B 생성 직후 | `TRACE_LINK` |
| `dEnqueue`, `aheadCnt` | `request_allocation.c: PutToNandReqQ()` 맨 앞 (`aheadCnt` = 삽입 전 `nandReqQ[ch][way].reqCnt`) | `TRACE_ENQUEUE` |
| `dIssue`, `dDieLastDone` | `request_schedule.c: IssueNandReq()`의 `REQ_CODE_READ` 분기(트리거 발행). `dDieLastDone`은 그 die의 직전 요청 완료 시각 복사 | `TRACE_TRIG_ISSUE` |
| `dTrigDone` | `request_schedule.c: ExecuteNandReq()`, `reqCode`가 `READ_TRANSFER`로 바뀌기 직전 | `TRACE_TRIG_DONE` |
| `dXferIssue` | `IssueNandReq()`의 `REQ_CODE_READ_TRANSFER` 분기 | `TRACE_XFER_ISSUE` |
| `dNandDone`, die 완료 시각 | `ExecuteNandReq()`의 완료 분기, `GetFromNandReqQ()` 앞(`dNandDone`)과 뒤(die 완료 갱신) | `TRACE_NAND_DONE`, `TRACE_DIE_DONE` |
| `dDmaStart` | `request_transform.c: IssueNvmeDmaReq()`의 TxDMA 분기 | `TRACE_DMA_START` |
| `dDmaEnd` + 레코드 기록 | `request_transform.c: CheckDoneNvmeDmaReq()`, TxDMA 완료 확인 시 | `TRACE_DMA_END` |

- 쓰기 요청, 쓰기 RMW용 읽기(A가 쓰기)는 기록하지 않는다(`TraceBegin`이 `REQ_CODE_READ`만 받음).
- `TRACE_ENABLE`을 0으로 하면 모든 `TRACE_*`가 빈 문장으로 컴파일된다.

### 4-2. 저장 형식 (바꾸지 않는다: 분석 스크립트가 의존)

- 주소 `0x00300000`(`TRACE_BASE_ADDR`). 앞 4KB = `TRACE_HDR`, 그 뒤 `TRACE_REC`(64B 고정) 최대 500,000개(약 32MB). 가득 차면 덮어쓰지 않고 `stopFlag=1`, `dropped` 증가.
- 헤더: `magic`(`0x45435254`), `version`(2), `recCount`, `stopFlag`, `rbuf`, `trace`, `verify`, `rbufEntries`, `countsPerSecond`, `timeShift`, `maxRecords`, `recBytes`(64), `recOffset`(0x1000), 카운터(`gcCnt`, `bufEvictCnt`, `bufReadEvictCnt`, `rbufReadAllocCnt`, `rbufWriteHitInvalidateCnt`), `dropped`. 카운터는 레코드를 쓸 때마다 복사된다.
- 필드 순서·크기는 `trace_log.h`의 `TRACE_REC`가 기준이다(`sizeof == 64`를 컴파일 시 검사).
- `flags`: b0 버퍼 hit(NAND 없음), b1 R-Buf 칸 사용, b2 예약, b3 차이값 포화, b4 미매핑.

### 4-3. 명세와 다르게 한 점 (**팀 확인 필요**)

| 항목 | 명세 | 구현 | 이유 |
|---|---|---|---|
| 차이값 단위 | `XTime` count 그대로 | `(차이) >> 6` (`TRACE_TIME_SHIFT`), 헤더에 `timeShift` 기록 | int32에 count를 그대로 넣으면 약 6.4초에서 넘침. 우리가 볼 정지는 21~30초. `>> 6`이면 약 413초까지 표현 |
| `TRACE_ENABLE` 기본값 | 구현 후 1 | 1 | 명세대로 |
| 시각이 기록되지 않은 필드 | 명시 없음 | 0으로 저장 (hit/unmapped는 `flags`로 구분) | 해석 스크립트가 flags로 판별 |

덤프 해석에서 시간 단위는 `2^timeShift ÷ countsPerSecond`초다.

## 5. 덤프가 안 될 때 (미구현)

계획서 순서: JTAG `xsct mrd` → UART 출력 → 로그 창 LBA.

- **QD1(M1):** "I/O가 5초 없으면 새 레코드를 UART로 전부 출력". 실행당 읽기 약 1만 건 × 64B ≈ 640KB. 이 코드는 **아직 없다.** `TraceDmaEnd`에서 쌓은 레코드를 `main` 루프의 유휴 시점(예: `nvme_main.c`의 루프에서 5초 동안 새 명령이 없을 때)에 `xil_printf`로 hex 출력하는 함수를 추가해야 한다. 이때 출력 중 호스트 명령 처리가 밀리지 않도록 실험이 끝난 뒤에만 실행.
- **QD8(M2):** 레코드가 10배 이상이라 펌웨어 내부 지연(`dDmaEnd`)이 10 ms 이상인 레코드만 출력하도록 필터.
- UART 출력은 "측정 중 UART 금지" 규칙의 예외가 되므로 실험이 끝난 뒤 출력한다고 명시할 것.

## 6. 문제가 생겼을 때 의심할 곳

| 증상 | 의심 | 확인 방법 |
|---|---|---|
| 빌드 에러 | include 누락, 매크로 구문 | Problems 탭 문구 확인. `trace_log.c`는 `request_allocation.h`, `data_buffer.h`, `garbage_collection.h`가 필요 |
| 부팅 중 멈춤 | `TraceInit()`이 0x00300000을 못 씀 | 해당 영역 uncached·미사용 재확인 (`memory_map.h` RESERVED0 0x00300000~0x0FFFFFFF, `main.c` MB 2~383이 uncached) |
| NVMe가 안 잡힘 | 부팅 지연·덮어쓰기 | `TRACE_INIT()` 줄 주석 처리 후 재시도 |
| 레코드 0건 | `TRACE_BEGIN`이 호출 안 됨, `traceCurFetch`가 0 | `ReqTransNvmeToSlice`의 `TRACE_BEGIN` 3곳, `handle_nvme_io_read`의 `TRACE_SET_FETCH` 확인 |
| 읽기 수보다 레코드가 훨씬 적음 | `CheckDoneNvmeDmaReq` TxDMA 분기에서 `TRACE_DMA_END`가 안 불림 | 해당 분기 확인. `txDone` 이후에만 호출 |
| `dTrigDone`, `dNandDone` 등이 0 | B→A 연결 실패 (`TRACE_LINK`) | `DataReadFromNand()`에서 A의 `reqCode`가 아직 `REQ_CODE_READ`인 시점에 호출되는지 확인 |
| 시각 순서 뒤바뀜 | 기록 지점 위치 | 4-1 표대로 위치 재확인 |
| 평소보다 읽기가 많이 느림 | 계측 부담 | `TRACE_ENABLE=0` 빌드와 읽기만 IOPS 비교 (기존 4,364 IOPS) |

## 7. 측정 규칙 (M1·M2에서)

- 회차마다 새 부팅: 호스트 종료 → Program FPGA → Launch → 배너 확인 → 호스트 켜기. 부팅 배너와 UART 로그를 저장.
- 장치는 항상 `DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}')`로 찾는다.
- 한 부팅에 한 회차만(쓰기 24GB, GC 한도 약 49GB 안). UART에 `[GC]`가 없어야 한다.
- 실행 전 `sudo dmesg -C`, 후 `sudo dmesg | grep -iE "timeout|abort|reset"`.
- **덤프는 fio가 끝난 직후, 보드를 끄거나 재부팅하기 전에.** 재부팅하면 로그가 사라진다.
- 같은 표·그림에서 계측 있는 빌드와 없는 빌드(E1 등)를 섞지 않는다.
- fio 설정은 `team-experiment-procedure.md` 9.4절의 `rbuf_check.fio`(M1 `RQD=1`, M2 `RQD=8`).

## 8. 파일·도구

| 경로 | 용도 |
|---|---|
| `source/software/lab-rbuf/src/trace_log.h/.c` | 계측 로그 본체 |
| `tests/trace_host/run.sh` | PC에서 `trace_log.c` 로직 테스트 (스텁 헤더 + 가짜 시계, gcc만 필요) |
| `tools/trace_parse.py` | 덤프(`trace.bin`) → CSV + 구간 요약 + 정지 목록 |
| `tools/trace_dump.md` | 덤프 명령 (미검증) |
| `tools/e1.sh`, `tools/e1_table.py` | E1 (이미 완료, 추가 실행 없음) |
| `docs/progress-report-2026-10-07.md`, `docs/review-request-2026-10-07.md` | 이전 보고서·검토 요청 |
| 팀 문서 5종 | `README.md`, `firmware-spec.md`, `firmware-decisions.md`, `team-experiment-procedure.md`, `team-paper-idea.md` (저장소에는 없음, 공유 드라이브) |

## 9. 알려진 한계와 주의

- **계측 자체가 지연에 영향을 줄 수 있다.** 읽기 하나당 시각 읽기 약 10번 + 64B 레코드를 uncached DRAM에 기록한다. 읽기만 IOPS(4,364)와 비교해 확인한다.
- `dDieLastDone`은 폴링으로 확인한 시각이라 실제 완료보다 늦을 수 있다(논문에 한계로 명시). `dNandDone`, `dTrigDone`도 마찬가지로 메인 루프 지연이 섞인다.
- 읽기 하나가 슬라이스 여러 개로 나뉘는 명령(4KB 정렬이 아닌 읽기)은 슬라이스마다 같은 `tFetch`·`lba`를 가진다. 우리 fio(4KB 정렬)에서는 슬라이스 하나다.
- 버퍼 hit 읽기는 다른 읽기가 아직 NAND에서 가져오는 중인 칸에 hit할 수도 있다. 이 경우 `flags` b0이 켜지지만 `dDmaStart`가 늦을 수 있다.
- `traceTmp` 배열(약 90KB)은 `.bss`에 있다. 코드·데이터 영역(0x00100000~0x001FFFFF)에서 현재 약 180KB를 쓰므로 여유는 충분하지만, 다른 큰 배열을 추가하면 다시 확인한다.
- 이전 `GreedyFTL-3.0.0` 트리는 공개판 기반 초기 구현이라 쓰지 않는다. 작업 기준은 `lab-rbuf/src`.

## 10. 저장소 비공개 유지

README 규칙대로 저장소는 비공개로 유지한다. 실습실 원본과 마이크로코드 헤더(`t4nsc_ucode.h`, `t4nsc_pm.h`)가 들어 있다(공개 범위 확인 전).
