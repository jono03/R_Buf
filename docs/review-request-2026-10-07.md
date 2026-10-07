# 검토 요청: R-Buf 보드 실험 결과와 기준 소스 정리 (2026-10-07 오후, 1차 보고서 이후)

1차 보고서(`docs/progress-report-2026-10-07.md`) 이후에 한 일을 전부 모았다. **모든 수치는 1~2회 측정**이고, 결론이 아니라 검토를 부탁하기 위한 자료다. 기획 문서(`team-paper-idea`, `team-experiment-procedure`, `firmware-spec`, `firmware-decisions`)와 다르면 기획 문서가 우선한다. 해석이 들어간 부분은 **[가설]**, 데이터로 확인한 부분은 **[확인]**으로 표시했다.

검토를 부탁하는 항목은 §9에 번호를 붙여 모았다. 시간이 없으면 §9만 봐도 된다.

---

## 0. 한 줄 요약

- **[확인]** 문서 조건(동시 읽기 8)의 E1에서 R-Buf는 S-Buf보다 읽기 IOPS가 약 1.8~2.0배, 읽기 지연 배수가 16.9x → 7.9~8.7x로 좋아졌다. **논문과 같은 방향**이지만 개선 폭은 훨씬 작다(논문 8.8x → 1.1x). 읽기 p95는 15.3 ms → 12.4~13.6 ms로 약 11~19% 줄었다(논문 93%).
- **[확인]** 읽기 QD1 + 쓰기 최대 속도 조건에서 **R-Buf 이후에도 1초 이상 읽기 정지가 남는다.** S-Buf 4건(합 53.8 s), R-Buf 8건(합 56.4 s). 정지가 아닌 읽기는 R-Buf에서 크게 빨라졌지만(평균 약 5 ms → 약 1.9 ms) 긴 정지는 못 막았다.
- **[확인]** 정지 동안에도 쓰기는 14K IOPS로 정상 진행된다. 호스트 `dmesg`에 timeout/abort/reset이 없다.
- **[가설]** 정지의 원인은 버퍼 대기가 아니라 die 큐·스케줄러·채널 쪽일 가능성이 커졌다. 확정은 계측 로그가 있어야 한다.
- 실습실 펌웨어 원본을 저장소에 커밋했고(`lab-gftl3`), 그 위에 R-Buf 변경과 GC 진입 출력을 얹은 트리(`lab-rbuf`)를 만들었다. 계측 로그는 **아직 구현 전**이다.

---

## 1. 1차 보고서 이후 바뀐 것

### 1-1. 저장소 커밋 (브랜치 `claude/new-session-hkspsr`)

| 커밋 | 내용 |
|---|---|
| `a1a34a2` | `tools/e1.sh`: job별 iodepth, 호스트 timeout 확인 출력 추가 |
| `3c49e2b` | `source/software/lab-gftl3/src`: 실습실 `run-gftl3/src` 원본 (수정 없음, 마이크로코드 제외) |
| `1068998` | 마이크로코드 헤더 `t4nsc_ucode.h`, `t4nsc_pm.h` 추가 (소유자 요청으로 푸시) |
| `64af2de` | `source/software/lab-rbuf/src`: 실습실 원본 + R-Buf 변경 + GC 진입 출력 |

### 1-2. E1 스크립트(`tools/e1.sh`) 변경 (팀 피드백 반영)

동시 읽기를 8개 이하로 맞추기 위해 iodepth를 job별로 지정한다. 공통 `[global]`의 `iodepth=32`는 제거했다.

| 구성 | 변경 전 | 변경 후 |
|---|---|---|
| 읽기만 | 4 jobs, iodepth 32 | 4 jobs, iodepth 2 |
| 비교용 읽기만 | 2 jobs, iodepth 32 | 2 jobs, iodepth 4 |
| 섞기 읽기 | 2 jobs, iodepth 32 | 2 jobs, iodepth 4 |
| 섞기 쓰기 | 2 jobs, iodepth 32 | 2 jobs, iodepth 32 (그대로) |

읽기 4KB 랜덤(영역 0~8G), 쓰기 16KB 랜덤(영역 8G~16G), 읽기 영역만 사전 채움(`bs=128k`, iodepth 32), 각 60초.

### 1-3. 실습실 원본 확인으로 알게 된 것 **[확인]**

- `run-gftl3`는 순정이다(R-Buf 변경 없음).
- SDK Debug 설정이 `arm-none-eabi-gcc -Wall -O0 -g3`이고 **`-DNDEBUG`가 없다.** 따라서 `assert()`가 켜져 있다(R-Buf 읽기 칸 clean assert 포함). 1차 보고서의 "NDEBUG 미확인" 항목이 해결됐다.
- 공개판과 다른 실습실 파일: `ftl_config.{c,h}`, `nsc_driver.{c,h}`, `request_schedule.{c,h}`, `address_translation.c`, `data_buffer.{c,h}`, `request_transform.c`, `nvme/{host_lld,nvme_admin_cmd,nvme_io_cmd,nvme_main}.c`, `nvme/{host_lld,nvme}.h`. 실습실에만 있는 파일: `t4nsc_pm.h`, `t4nsc_ucode.h`.
- `garbage_collection.c`, `main.c`, `request_allocation.c`는 공개판과 같다.
- **스케줄러 우선순위(`request_schedule.c`)**: idle → status report → status check → read trigger → erase → write → **read transfer(맨 뒤)** 순으로 채널을 처리한다. 공개판과 같다. 채널이 쓰기로 바쁘면 읽기 전송이 밀릴 수 있는 구조다 **[가설: 읽기 정지의 후보 구간]**.
- 우리 저장소의 `data_buffer.c/h`, `request_transform.c`는 실습실 원본 대비 **R-Buf 변경분만** 다르다(`request_transform.c`는 `AllocateDataBuf()` → `AllocateDataBuf(reqCode)` 한 줄 + 카운터/훅). `ftl_config.h`는 실습실 파일에 R-Buf 스위치 4개만 추가했다.

### 1-4. GC 진입 출력 (spec 3절, "최우선")

`lab-rbuf/src/garbage_collection.c`: `GarbageCollection()` 맨 앞에 `gcCnt++; xil_printf("[GC] die %d cnt %d\r\n", dieNo, gcCnt);`. `garbage_collection.h`에 `extern unsigned int gcCnt;`. **SDK 반영·빌드·보드 확인은 아직 안 했다**(다음 세션).

---

## 2. 정합성 검증 현황

| 검증 | 빌드 | 결과 |
|---|---|---|
| 16KB randrw 1GB, QD16 (1차 보고서) | S-Buf, R-Buf | `err=0` |
| 16KB randwrite 1GB, QD32, `verify=crc32c` | S-Buf | `err=0` (읽기 24.4k IOPS, 쓰기 14.1k IOPS) |
| 16KB randwrite 1GB, QD32, `verify=crc32c` | R-Buf | `err=0` (읽기 20.7k IOPS, 쓰기 14.1k IOPS) |
| 좁은 영역 덮어쓰기: `--rw=randwrite --size=16m --io_size=256m --iodepth=32 --norandommap --serialize_overlap=1 --verify=crc32c --do_verify=1` | R-Buf | `err=0`, verify 에러 없음 |
| 좁은 영역 읽기·쓰기 혼합: `--rw=randrw --rwmixread=50 --size=16m --io_size=256m --iodepth=32 --norandommap --serialize_overlap=1 --verify=crc32c --verify_backlog=64` | R-Buf | `err=0`, verify 에러 없음 |

**한계 [확인]:**
- 좁은 영역 덮어쓰기(randwrite만)는 쓰기를 모두 끝낸 뒤 읽으므로 **읽기 칸 무효화 경로를 거의 거치지 않는다.** 혼합 버전은 무효화가 일어났을 가능성이 높지만(예상 수십 회) 횟수는 카운터 빌드(`VERIFY_PRINT=1`)가 없어 확인하지 못했다.
- 위 두 fio 옵션 조합은 기획서의 명령과 다르다(`--io_size`, `--verify_backlog` 추가). 문서의 정확한 명령과 맞는지 검토 부탁(§9-7).

**아직 안 한 것 (spec 6절 완료 조건):** 4KB randrw 64MB, 16KB randwrite 8GB 전체 verify, S-Buf에서의 좁은 영역 덮어쓰기, `VERIFY_PRINT=1` 빌드로 읽기 eviction 0·무효화 수 > 0 확인, 로그 덤프.

---

## 3. E1 결과 (문서 조건: 읽기 4KB 동시 8, 쓰기 16KB QD32 × 2)

### 3-1. 회차별 원자료

단위는 fio가 출력한 값 그대로(`clat`은 usec). "섞기"는 읽기 2 jobs × QD4 + 쓰기 2 jobs × QD32.

| 항목 | S-Buf 1회 | S-Buf 2회 | R-Buf 1회 | R-Buf 2회 |
|---|---|---|---|---|
| 읽기만(2 jobs) IOPS | 16.8k | 16.8k | 15.5k | 15.5k |
| 읽기만 평균 clat | 473.81 | 474.36 | 513.97 | 513.69 |
| 읽기만 p95 / p99 | 963 / 1270 | 971 / 1270 | 996 / 1270 | 996 / 1287 |
| 읽기만 최대 | 2252 | 2249 | 2703 | 2653 |
| 읽기만(4 jobs × QD2) IOPS / 평균 | 16.8k / 474.01 | 16.8k / 473.94 | 15.5k / 513.22 | 15.5k / 512.98 |
| 섞기 읽기 IOPS | 996 | 990 | 1786 | 1974 |
| 섞기 읽기 평균 clat | 8020.03 | 8067.80 | 4470.28 | 4045.55 |
| 섞기 읽기 p95 / p99 | 15270 / 18220 | 15270 / 18220 | 13566 / 18482 | 12387 / 17695 |
| 섞기 읽기 최대 | 37006 | 32952 | **328094** | 42655 |
| 섞기 쓰기 IOPS | 13.6k | 13.6k | 12.9k | 12.8k |
| 섞기 쓰기 평균 clat | 4693.23 | (미출력) | 4956.13 | 4984.56 |
| 섞기 쓰기 p95 / p99 | 10945 / 13042 | 10683 / 12911 | 24511 / 31851 | 29230 / 35390 |
| 섞기 쓰기 최대 | 37459 | (미출력) | 38560 | 54349 |

### 3-2. 논문 비교표 (`tools/e1_table.py`, R-Buf 2회 vs S-Buf 1회)

| 지표 | S-Buf | R-Buf (변화) | 논문 S-Buf → R-Buf |
|---|---|---|---|
| 읽기 지연 배수 (섞기 ÷ 읽기만, 평균) | 16.9x | 7.9x | 8.8x → 1.1x |
| 읽기 IOPS (섞기) | 996 | 1974 (+98%) | 5.4K → 28.1K (+420%) |
| 읽기 p95 (섞기) | 15.3 ms | 12.4 ms (-19%) | 133 → 9 ms (-93%) |
| 쓰기 IOPS (섞기) | 13600 | 12800 (-6%) | 5349 → 4156 (-22%) |

배수를 4회로 전부 계산하면: S-Buf 16.9x / 17.0x, R-Buf 8.7x / 7.9x.

### 3-3. 읽을 수 있는 것과 없는 것

- **[확인]** 방향은 논문과 같다. S-Buf 두 회차는 거의 같아서(IOPS 996/990, 평균 8.02/8.07 ms) S-Buf 쪽 재현성은 좋다.
- **[확인]** R-Buf는 두 회차 모두 S-Buf보다 낫지만 회차 간 차이가 있다(IOPS 1786/1974, 약 10%). R-Buf 1회차의 최대 328 ms는 2회차에서 재현되지 않았다(42.7 ms).
- **[확인]** 읽기 지연이 읽기만 대비 아직 약 8배 남는다. 논문(1.1x)처럼 간섭이 거의 사라진 것은 아니다.
- **[확인]** 쓰기 p95가 나빠졌다(S-Buf 약 11 ms → R-Buf 24~29 ms). 쓰기 평균 clat은 4.69 → 4.96~4.98 ms로 약 6% 느려졌다. **[가설]** 읽기 칸 8개를 떼어 쓰기 칸이 120개로 줄어서. 확인한 것은 아니다.
- **[확인]** 읽기만 기준도 R-Buf에서 8% 낮다(16.8k → 15.5k). **[가설]** 읽기 칸이 8개뿐이라 읽기 전용에서도 영향. 확인한 것은 아니다.
- 논문 대비 우리 조건 차이: 버퍼 2MB vs 32MB, 읽기 칸 8 vs 128, 보드 하드웨어. 표 아래에 명시해야 한다.

### 3-4. 반복 측정의 조건 (검토 필요)

- S-Buf 2회는 각각 **새 부팅**(Program FPGA 후)에서 돌렸다.
- R-Buf 2회는 **같은 부팅에서 연속**으로 돌렸다(2회차는 누적 쓰기 약 40GB로 GC 한도 약 49GB에 가까움). `rbuf_e1` 이름이 같아서 1회차 파일은 덮어써졌고, 1회차 값은 대화에 남은 출력에서 옮겼다.
- 즉 R-Buf 2회는 독립 반복이 아니다. 새 부팅 R-Buf 1~2회를 더 돌려야 한다(§9-2).
- R-Buf E1 두 번을 돌릴 때의 **UART 부팅 배너 로그를 저장하지 않았다.** 같은 날 직후 부팅(rbuf2 직전)에서 새 형식 `[ RBUF=1 RBUF_ENTRIES=8/128 TRACE=0 VERIFY=0 ]`를 확인했고, 그 전 R-Buf 부팅은 옛 형식(`[ R-Buf ON: read entries 8 of 128 ]`)일 수 있다. R-Buf 로직은 같지만, E1 R-Buf 회차의 정확한 빌드를 로그로 증명하지는 못한다. E1 이후 새 빌드로 재측정하는 것이 안전하다(§9-2).

---

## 4. 읽기 QD1 + 쓰기 최대 속도 (정지 관찰)

조건: 읽기 영역 8GiB 순차 채움 → 읽기 4KB QD1(영역 0~8g) 60초 단독 → 읽기 QD1 + 쓰기 16KB QD32(영역 8g~24g, 16GiB), `exitall=1`, 지연 로그 `write_lat_log`(시각 ms, 지연 ns).

### 4-1. 1초 이상 걸린 읽기 목록

시작 시각은 `완료 시각 - 지연`으로 계산한 값이며 job 시작 기준이다.

**S-Buf `sbuf1`** (이전 빌드, 실행 약 74 s)

| 완료 시각 (s) | 지연 (s) |
|---|---|
| 11.7 | 8.69 |
| 47.6 | 30.04 |
| 57.0 | 3.88 |
| 70.8 | 11.20 |
| **4건, 합 53.8 s (73%)** | 최대 30.04 |

**R-Buf `rbuf2`** (새 빌드, 배너 `RBUF=1` 확인, 실행 74.7 s)

| 완료 시각 (s) | 지연 (s) | 추정 시작 (s) |
|---|---|---|
| 21.4 | 21.05 | 0.35 |
| 28.4 | 6.02 | 22.4 |
| 33.6 | 3.06 | 30.5 |
| 45.3 | 5.36 | 39.9 |
| 48.7 | 3.11 | 45.6 |
| 62.7 | 13.64 | 49.0 |
| 67.2 | 3.12 | 64.1 |
| 70.9 | 1.01 | 69.9 |
| **8건, 합 56.4 s (75%)** | 최대 21.05 | |

### 4-2. 요약 비교

| 항목 | S-Buf `sbuf1` | R-Buf `rbuf_q1` (로그 없음, 이전 빌드) | R-Buf `rbuf2` (로그 있음) |
|---|---|---|---|
| 읽기만 IOPS / 평균 | 4,358 / - | 4,364 | 4,364 / 227.23 µs (최대 820 µs) |
| 섞기 중 읽기 횟수 | 약 3,800 | 약 8,000 | **9,621** |
| 섞기 읽기 평균 | 19.3 ms | 9.19 ms | 7.75 ms |
| 섞기 읽기 p50 / p99 / p99.9 | 4 ms / 17 ms / 3,876 ms | 0.70 ms / 9.1 ms / 83 ms | (백분위 줄 미수집) |
| 섞기 읽기 최대 | 30.0 s | 23.9 s | 21.05 s |
| 쓰기 IOPS / 평균 / 최대 | 14.2K / 2.248 ms / - | 14.2K / 2.244 ms / - | 14.0K / 2.275 ms / 26.0 ms |
| 1초 이상 정지 | 4건, 53.8 s | (로그 없음) | **8건, 56.4 s** |

### 4-3. 해석

- **[확인]** R-Buf에서도 정지 합계가 실행 시간의 약 4분의 3으로 S-Buf와 비슷하다. 건수는 4 → 8건으로 늘었다.
- **[확인]** 정지를 뺀 읽기는 R-Buf에서 크게 빨라졌다. R-Buf `rbuf2`: 정지 8건(56.4 s)을 뺀 읽기 9,613건이 약 18.2 s → 평균 약 1.9 ms. S-Buf는 같은 계산으로 약 5 ms. 그래서 읽기 횟수가 약 2.5배.
- **[확인]** 정지 동안 쓰기는 정상 속도(14.0K IOPS, 쓰기 최대 지연 26 ms)로 진행됐다. fio 진행 표시에 `r=` 없이 `w=14.1k IOPS`만 찍힌 초(읽기 0건)가 여러 번 있다.
- **[확인]** R-Buf 읽기가 쓰기 flush를 기다리지 않는 설계인데도 정지가 남았다. **[가설]** 정지 구간은 버퍼 층이 아니라 die 큐·스케줄러(읽기 전송이 우선순위 맨 뒤)·채널·NAND 쪽이다. 계측 로그 전에는 확정하지 않는다.
- **[관찰만]** `rbuf2`의 정지 중 3건이 3.06 / 3.11 / 3.12 s로 비슷하다. 우연일 수 있어 해석하지 않았다.
- **[주의]** 첫 정지가 읽기 시작 후 약 0.35 s 시점에 시작해 21 s 동안 이어졌다. 쓰기가 막 시작한 시점이다.

### 4-4. timeout 가능성

- **[확인]** `/sys/module/nvme_core/parameters/io_timeout` = 30. 실행 후 `dmesg | grep -iE "timeout|abort|reset"`이 `rbuf2`와 E1 4회 모두 비어 있다.
- **R-Buf 최대 21.05 s는 30 s보다 짧아서 timeout과 무관하다.**
- **S-Buf `sbuf1`의 30.04 s는 NVMe 기본 timeout(30 s)과 같아 호스트의 abort/reset 흔적일 수 있다는 의심이 남아 있다.** 그 실행에서는 `dmesg`를 확인하지 않았다. 새 빌드로 S-Buf QD1을 다시 돌려 `dmesg`까지 확인해야 판정할 수 있다(§9-3).

---

## 5. 팀 피드백(1007_2120)에 대한 반영 상태

| 피드백 | 상태 |
|---|---|
| E1 `iodepth` 수정 (읽기만 4 jobs × QD2, 섞기 읽기 2 jobs × QD4 + 쓰기 2 jobs × QD32) | 반영(`a1a34a2`) |
| 매 실행 뒤 `dmesg` 확인, `io_timeout` 값 확인 | 반영 (`e1.sh`가 출력, `rbuf2`는 수동 실행) |
| `rbuf2`(R-Buf + 지연 로그) 실행, 1초 이상 정지 목록 비교 | 완료 (§4) |
| `fix/lab-base`: 실습실 `src` 전체 수정 없이 커밋 후 3개 파일 변경 재적용 | 완료 (`lab-gftl3` + `lab-rbuf`). 브랜치는 `fix/lab-base`가 아니라 같은 브랜치의 디렉터리로 구성 |
| 실습실 `garbage_collection.c`에 GC 진입 출력 한 줄 | 코드 반영 (`lab-rbuf`), **SDK 반영·보드 확인 전** |
| `request_schedule.c` 스케줄러 우선순위가 공개판과 같은지 확인 | 완료 (§1-3) |
| 요청별 계측 로그(spec 3절 64B 레코드) | **미구현 (다음 세션)** |
| 10/8 JTAG 덤프 시험 | 미실시 |
| verify 3종 | 일부 (§2) |
| 읽기 칸 8→16→32→64 민감도 실험 하지 말 것 | 하지 않음 |
| 장치 가득 채움·4KB·QD32 실험은 12월로 | 하지 않음 |
| `NDEBUG` 확인 | 완료 (§1-3, 켜져 있지 않음 → assert 활성) |

---

## 6. 기획서(firmware-spec) 완료 조건 대비 (갱신)

| 항목 | 상태 |
|---|---|
| LRU 분리, 쓰기→읽기 칸 무효화, 읽기 칸 clean assert, 기존 구조 유지 | ✅ |
| 읽기 칸 8, 버퍼 총량 128칸 유지 | ✅ |
| `RBUF_ENABLE` 스위치 | ✅ |
| `TRACE_ENABLE`/`VERIFY_PRINT` 매크로 | ✅ (단 우리 `TRACE_ENABLE` 기본값은 0, spec은 1) |
| 부팅 배너 | ✅ 보드 확인 (`RBUF=0`, `RBUF=1` 형식, spec의 `RBUF/TRACE/VERIFY`에 `RBUF_ENTRIES`를 추가한 확장 형식) |
| 읽기가 일으킨 eviction 카운터 | ✅ 코드 반영, **`VERIFY_PRINT=1` 보드 확인 전** |
| GC 진입 출력 | ✅ 코드 반영(`lab-rbuf`), SDK 반영 전 |
| 측정 중 UART 출력 금지 (GC 진입 예외) | ✅ |
| fio verify 4종 (두 빌드) | 🟡 §2 참고 |
| 요청별 계측 로그 + 덤프 | ❌ |
| 기준 소스 = 실습실 원본 | ✅ (`lab-gftl3` 수정 없는 원본, `lab-rbuf` 변경 적용) |
| E1 방향 확인 | ✅ (각 2회, §3-4 조건 참고) |

---

## 7. 실험 중 있었던 일 (재현성·안전)

1. **장치 이름 확인 습관**: `nvme list | grep`을 `sudo` 없이 실행해 빈 결과가 나왔는데도 `/dev/nvme0n1`에 fio를 한 번 실행했다. 이후 `sudo nvme list`와 `lsblk`로 확인해 Cosmos가 맞고 시스템 SSD(`nvme1n1`)에는 쓰지 않았음을 확인했다. 앞으로 모든 명령은 `DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}')`로 모델명 조회 후 사용한다.
2. **터미널 붙여넣기**: 여러 줄을 붙이면 마지막 줄 끝에 줄바꿈이 없어 명령이 합쳐지거나 실행이 안 되는 일이 4번 있었다(`sbuf_e1`, `ovw16m`, `ovwmix`, `dmesg -C` 포함). 긴 fio 명령은 한 줄로 만들어 따로 붙이고, `bind 'set enable-bracketed-paste off'`를 먼저 한다.
3. **부팅 누적 쓰기량**: 새 부팅 직후가 아니면 GC 한도(약 49GB)에 가까워진다. E1(약 20GB) + verify + `rbuf2`(약 24GB)를 한 부팅에서 이어 하지 않는다.
4. **파일 덮어쓰기**: 같은 태그로 E1을 다시 돌리면 이전 파일이 덮어써진다. 회차마다 태그(`sbuf_e1b`, `rbuf_e1b` 등)를 바꾼다.
5. UART 로그의 `Erase FAIL`, `Read Transfer FAIL`, `bad block is detected`는 매 부팅 같은 위치에서 나오는 정상 로그다(부팅마다 전체 erase 후 불량 블록표 재작성).

---

## 8. 재현 명령

```bash
# 장치 확인 (필수)
bind 'set enable-bracketed-paste off'
DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}'); echo "DEV=$DEV"
sudo nvme list

# E1 (재부팅 + Program FPGA 직후 1회)
sudo dmesg -C
./e1.sh sbuf_e1 2>&1 | tee sbuf_e1_console.txt      # 또는 rbuf_e1
python3 e1_table.py sbuf_e1_ro2.txt sbuf_e1_mix.txt rbuf_e1_ro2.txt rbuf_e1_mix.txt

# 정합성 (16KB 랜덤 쓰기 1GB)
sudo fio --name=verify16k --filename=$DEV --direct=1 --ioengine=libaio --rw=randwrite --bs=16k --iodepth=32 --size=1G --randrepeat=0 --verify=crc32c --do_verify=1 --verify_fatal=1

# 좁은 영역 덮어쓰기 / 혼합
sudo fio --name=ovw16m --filename=$DEV --direct=1 --ioengine=libaio --rw=randwrite --bs=16k --size=16m --io_size=256m --iodepth=32 --norandommap --serialize_overlap=1 --randrepeat=0 --verify=crc32c --do_verify=1 --verify_fatal=1
sudo fio --name=ovwmix --filename=$DEV --direct=1 --ioengine=libaio --rw=randrw --rwmixread=50 --bs=16k --size=16m --io_size=256m --iodepth=32 --norandommap --serialize_overlap=1 --randrepeat=0 --verify=crc32c --verify_backlog=64 --verify_fatal=1

# QD1 + 쓰기 최대 (지연 로그, rbuf2.fio는 1차 보고서 §11의 구성)
sudo dmesg -C
sudo fio rbuf2.fio --output=rbuf2.txt
sudo dmesg | grep -iE "timeout|abort|reset"
awk -F', *' '$2>1000000000 {printf "done at %.1f s, latency %.2f s\n",$1/1000,$2/1e9; n++; s+=$2} END{printf "stalls(>=1s)=%d total=%.1f s\n",n,s/1e9}' rbuf2_reader_clat.3.log
```

---

## 9. 검토 요청 항목 (우선순위 순)

### A. 해석·주장 범위

1. **E1 해석이 기획서의 주장 범위와 맞는지.** "논문과 같은 방향의 개선, 단 폭은 작고 읽기 지연이 읽기만 대비 약 8배 남는다"를 논문 본문에서 어떻게 쓸지. 읽기 칸이 8개이고 동시 읽기도 정확히 8개라는 점(읽기 칸이 전부 점유될 수 있는 조건)이 개선 폭을 제한했을 가능성이 있다. **[가설]** 이 가능성을 논문에서 한계로 쓸지, 12월 F1(읽기 칸 수 조절)로 넘길지.
2. **반복 측정 정책.** 현재 S-Buf 2회(새 부팅 각각), R-Buf 2회(같은 부팅 연속, E1 로그 배너 미보존). 논문에는 각 빌드 3회 이상 새 부팅이 필요한지, 계측 빌드가 나오면 그 빌드로 3회씩 몰아서 재측정해도 되는지(내 제안).
3. **S-Buf 30.04 s 정지의 timeout 의심.** `sbuf1`은 `dmesg`를 안 봤다. 새 빌드로 S-Buf QD1(`sbuf2`)을 다시 돌려 `dmesg`까지 확인하는 것이 필요한지, 계측 빌드 측정에 합칠지.
4. **정지를 논문 주 결과로 쓸지.** 현재 근거는 "R-Buf 이후에도 정지 합계가 비슷하다 + 정지 중 쓰기는 정상"까지이고 원인 구간은 모른다. 계측 로그 이후에 구간을 확정한다는 방침이 맞는지.
5. **쓰기 p95 악화**(약 11 ms → 24~29 ms)와 **읽기만 기준 8% 하락**을 논문에서 어떻게 다룰지. 둘 다 읽기 칸 8개 확보로 쓰기 칸이 120개로 준 영향일 수 있다 **[가설]**.

### B. 구현·검증

6. **`lab-rbuf` 변경분 코드 리뷰.** `data_buffer.c/h`, `request_transform.c`가 기획서 3~4절(읽기 칸 clean, 무효화, 단일 hash)과 맞는지. 특히 쓰기가 읽기 칸에 적중할 때의 무효화(논문의 "플래그 전환"과 다름)가 허용되는 한계인지.
7. **verify 명령 형식.** 기획서의 "좁은 영역 덮어쓰기(`--size=16m --norandommap --serialize_overlap=1`)" 명령의 `--rw`, `--io_size`, `--verify_backlog` 값이 따로 정해져 있는지. 내가 쓴 `--io_size=256m`과 `--verify_backlog=64`가 의도와 맞는지.
8. **무효화 경로 확인 방법.** 현재 혼합 덮어쓰기는 통과했지만 무효화 횟수는 확인 못 했다. `VERIFY_PRINT=1` 빌드로 `invalidate > 0`을 확인하는 것으로 충분한지, 아니면 별도 테스트(쓰기 전 읽기를 고정한 시나리오)가 필요한지.
9. **GC 진입 출력 위치.** `GarbageCollection()` 맨 앞에 넣었다(spec 3절). `address_translation.c:679`의 호출부에서 조건(free block ≤ 1) 이후에만 호출되는지 확인 부탁. 측정 빌드에서도 UART 출력이 허용되는 예외라는 해석이 맞는지.
10. **`TRACE_ENABLE` 기본값.** spec은 1, 현재 코드는 0(미구현). 계측 구현 후 1로 바꿀 예정. 부팅 배너는 spec의 `RBUF/TRACE/VERIFY`에 `RBUF_ENTRIES`를 덧붙인 형식. 분석 스크립트가 배너 형식에 의존하는지.

### C. 저장소·범위

11. **실습실 마이크로코드 파일(`t4nsc_ucode.h`, `t4nsc_pm.h`)을 이 저장소에 올린 것.** 소유자 요청으로 푸시했다. 저장소의 공개 범위와 팀 정책(공유 가능 여부) 확인 부탁. 문제가 되면 커밋 이력에서 제거한다.
12. **디렉터리 구성.** 기준 소스는 `source/software/lab-gftl3`(수정 없음), 작업 트리는 `source/software/lab-rbuf`, 이전 `source/software/GreedyFTL-3.0.0`은 공개판 기반 R-Buf 초기 구현으로 남아 있다. 이 구성을 정리(이전 트리 제거 등)할지.
13. **1차 보고서 갱신.** `docs/progress-report-2026-10-07.md`의 §0, §8, §9는 오늘 오후 결과를 아직 반영하지 않았다. 이 문서로 대체할지, 1차 보고서를 갱신할지.

---

## 10. 다음 세션에서 할 일 (순서)

사용자 요청으로 이 단계는 다음 세션으로 넘긴다.

1. **GC 진입 출력 SDK 반영**: `run-rbuf`의 `garbage_collection.c`(함수 위 `unsigned int gcCnt = 0;`, 함수 안 `gcCnt++; xil_printf(...)`)와 `garbage_collection.h`(`extern unsigned int gcCnt;`) 수정 → Clean → Build → Problems 에러 0개 확인 → 정상 부팅 확인.
2. **계측 로그 구현(spec 3절)**: `TRACE_REC` 64B, 읽기 요청만, `reqSlotTag` 인덱스 임시 배열, 기록 지점(`nvme_io_cmd.c`, `ReqTransSliceToLowLevel()`, `PutToNandReqQ()`, `IssueNandReq()`, NAND 완료 확인, 호스트 DMA 발행·완료), 헤더와 카운터 5종, `TRACE_BASE_ADDR`(후보 `0x00300000`, 실습실 `memory_map.h`·`main.c` 페이지 테이블에서 미사용·uncached 확인 후 확정), 가득 차면 기록 중단.
3. **10/8 JTAG `xsct mrd` 덤프 시험**, 안 되면 로그 창 LBA → UART 축소 기록.
4. **verify 마무리**: 4KB randrw 64MB, 16KB randwrite 8GB, `VERIFY_PRINT=1` 빌드에서 읽기 eviction 0·무효화 > 0, S-Buf 쪽 동일 검증.
5. **계측 빌드로 재측정**: QD1(S-Buf·R-Buf, `dmesg` 포함)과 E1을 각 3회, 새 부팅마다. 구간 분해(버퍼 대기 / die 큐 / 메인 루프 / NAND·DMA).
6. 보고서·그래프·본문 정리 (마감 10/15).
