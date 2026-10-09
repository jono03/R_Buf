# 10/9 대화 정리 (코드 반영, 관문 통과, S1·R1 결과, 해석, 로드맵)

작성: 2026-10-09 실습실 진행 중. 기준 코드 커밋 `2340e73`(계측 코드) 이후 `trace_lookup.py`, `trace_where.py` 추가(`11df6cb`).
함께 보는 문서: `progress-2026-10-09.md`(진행 기록), `work-split-2026-10-09.md`(실험·분석 분담), `experiment-plan-2026-10-09.md`(회차 절차).

## 1. 오늘 한 일

| 단계 | 내용 | 결과 |
|---|---|---|
| 코드 | 검토 의견(1009) 반영: 호출 수 2구간(`schedDieQ`, `schedXferWait`), `TRACE_UART_LAST`, 호출 수 규칙 보조 보기 | 호스트 로직 테스트 통과, 구문 컴파일 통과 |
| SDK | `run-rbuf09`(복사본)의 `src`를 교체, `TRACE_ENABLE=1`, `RBUF_ENABLE` 0/1 번갈아 Clean → Build | **G1 통과** |
| FPGA | `Could not find FPGA device`(JTAG 연결), `DONE PIN is not HIGH`(전원 껐다 켜기) | 해결 |
| 부팅 | 배너로 확인: `RBUF=1 RBUF_ENTRIES=8/128 TRACE=1` / `RBUF=0 RBUF_ENTRIES=0/128 TRACE=1` | **G2 통과** |
| 시험 fio | 1GB 쓰기 + 4KB 랜덤 읽기 10초 QD1: 평균 232 µs, p99 245 µs | 에러 없음 |
| 덤프 | XSCT `mrd -bin -file`(코어 Running인 채로 가능) | **G3 통과** (2.7MB, 17MB 모두 크기 정확) |
| 해석 | Windows PC에 python 3.12.10(`winget`) 설치, `trace_parse.py` | **G4 통과** |
| 본 회차 | S1(S-Buf, M1), R1(R-Buf, M1) 덤프와 fio 완료 | 데이터 확보 |

## 2. 환경 메모

- 호스트(리눅스): fio, `~/m12`. 덤프는 JTAG이 연결된 Windows PC의 XSCT에서만 가능.
- UART 로그는 **SDK Terminal**(Xilinx 것, Eclipse Terminal 아님)에서 COM3, 115200.
- 호스트는 보드 부팅 완료(`Turn on the host PC`) 후에 켠다. 호스트를 끄기 전에 fio 로그를 Drive에 올린다.
- ELF는 빌드할 때마다 덮어써지므로 `C:\Users\User\elf_backup\`에 `rbuf-trace.elf`, `sbuf-trace.elf` 복사.
- 여러 줄 붙여넣기는 줄이 합쳐지거나 중복되는 일이 반복됨(`8connect` 오류, fio 두 번 실행 의심). 한 줄씩 붙여넣는다.
- 부팅 로그는 두 종류: 불량 블록 테이블이 없을 때는 전체 erase와 `Erase FAIL` 출력, 있을 때는 `Erase User block space`만.

## 3. 측정 결과

### 3-1. 펌웨어 내부 읽기 지연 (tFetch ~ DMA 끝)

| | S1 S-Buf | R1 R-Buf |
|---|---|---|
| 레코드 | 270,807 | 269,872 |
| p50 | 0.224 ms | 0.222 ms |
| p99 | 9.533 ms | **0.829 ms** |
| p99.9 | 13.474 ms | **8.970 ms** |
| max | 25.417 ms | **9.996 ms** |
| p99 초과 읽기의 대기 구성(팀 규칙) | 버퍼 55.2%, die 큐 42.6%, NAND+DMA 2.2% | die 큐 94.9%, NAND+DMA 4.9%, 버퍼 0.0% |
| R-Buf 엔트리 플래그 | 0.0% | 100.0% |
| 시간순서 위반, `saturated`, `dropped` | 0, 0, 0 | 0, 0, 0 |

- 호출 수 규칙 보기는 두 회차 모두 팀 규칙 보기와 같은 값이 나왔다.

### 3-2. 호스트가 본 1초 이상 읽기 정지 (fio reader 로그)

| 회차 | 건수 | 합 | 최대 |
|---|---|---|---|
| S1 S-Buf | 4 | 8.9 s | 4.82 s |
| R1 R-Buf | 11 | 83.8 s | 30.17 s (실험 종료 시점의 한 건, 이것을 빼면 10건 53.6 s) |
| 참고 10/7 S-Buf | 4 | 53.8 s | 30.04 s |
| 참고 10/7 R-Buf | 8 | 56.4 s | 21.05 s |

- 쓰기 폭주: S1 16GiB 76 s 215 MiB/s, R1 16GiB 76.6 s 214 MiB/s. `gcCnt` 0.
- R1은 reader 실행이 103.8 s로 쓰기(76.6 s)보다 27 s 길었다(S1은 같음).

### 3-3. R1에서 호스트 정지한 5건의 펌웨어 기록 (`trace_lookup.py`)

| 호스트 지연 | LBA | 펌웨어 `fw_total` |
|---|---|---|
| 13.23 s | 1378154 | 0.347 ms |
| 5.94 s | 1893736 | 0.370 ms |
| 14.24 s | 1682794 | 0.462 ms |
| 7.43 s | 70807 | 0.705 ms |
| 30.17 s | 1614737 | 1.236 ms |

- 5건 모두 LBA당 기록이 한 건뿐이라 일대일 대응. 기록 순번도 호스트 로그의 시간 순서와 같은 방향으로 늘어난다.

## 4. 해석 (확정과 가설을 구분)

**확정**
- R-Buf는 펌웨어 내부 읽기 대기를 줄였다(p99, max, 버퍼 대기 소멸). 남은 대기는 die 큐.
- 호스트가 본 1초 이상 정지는 S-Buf, R-Buf 모두 **펌웨어 서비스 구간 밖**에 있다. 펌웨어 내부 최대(25.4 ms, 10 ms)가 호스트 정지(≥1 s)보다 훨씬 작기 때문이고, 짝짓기 없이도 성립한다.
- 정지 건수와 합은 회차 간 변동이 크다(S-Buf만 8.9 s와 53.8 s). 한 회차끼리 비교해 "R-Buf가 정지를 늘렸다"고 쓸 수 없다. 반복 3회가 필요하다.

**가설(미확인)**
- 구간 밖의 위치: 명령을 가져오기 전(before-fetch)인지, DMA 이후 완료 전달(after-DMA)인지 모른다. `trace_parse.py`의 `fetch-before`는 이름과 달리 "호스트 − 펌웨어" 전체이며 두 구간을 합친 값이다. 앞서 "정지는 fetch-before"라고 한 표현은 철회한다.
- R1 호스트 `dmesg`: `[167.5] irq 150: nobody cared ... Disabling IRQ #150`(핸들러 `nvme_irq`), `[300.7] nvme0 I/O tag 96 QID 5 timeout, completion polled`. IRQ 150은 관리 큐(`nvme0q0`)이고 `/proc/interrupts`에서 약 199,893번(정상보다 훨씬 많음). I/O 큐(`q1~q7`) 인터럽트 합은 약 1,383,365로 완료 수(1,383,606)와 거의 같다. 일부 완료의 인터럽트가 잘못된 벡터로 가거나 유실되는 가설이 있으나 확인 못 함.
- 30.17 s 한 건은 reader 종료 시점의 마지막 읽기로, 커널 I/O timeout(30 s)이 회수한 것으로 보인다(가설). 나머지 4건(5.9~14.2 s)은 timeout으로 설명되지 않는다.
- 10/7 기록에도 `Disabling IRQ #150`이 한 번 있었고, S-Buf 30.04 s가 timeout과 같은 값이라는 의심이 있었다. 오늘 처음 생긴 문제가 아니다.

## 5. 논문 방향과의 관계

- 오늘 실험(M1: QD1 + 16GB 쓰기 폭주, S/R 각 3회 새 부팅; M2: QD8 각 1회)은 계획서와 `review-request` 기준에 맞는다.
- 주제("R-Buf 이후에도 남는 초 단위 정지가 어디서 생기는가")에 대해, 지금 데이터는 "펌웨어 서비스 구간 안이 아니다"라고 답한다. 구간 밖의 위치를 가려야 주 결과가 강해진다.

| `trace_where.py` 결과 | 논문 주장 | 추가 작업 |
|---|---|---|
| before-fetch 위주 | 펌웨어 내부 대기는 제거됐지만 명령 수신 단계에서 초 단위 지연(SSD 내부 원인) | 메인 루프 명령 처리 간격 기록 계측, 재측정 1회 |
| after-DMA 위주 | 펌웨어 내부는 10 ms 이내, 호스트 꼬리는 완료 전달(플랫폼 인터럽트) 경로. 측정 방법론 기여 | 폴링 입출력 대조, 인터럽트 문제 수정 후 재측정 |
| 섞임 | 가져오기 전 / 펌웨어 / 완료 전달 구간별 정지 시간 표 | 두 쪽의 증거를 모두 제시 |

- 증거 3가지: ① `trace_where.py` (시계 정렬로 before/fw/after 분해), ② 회차별 `/proc/interrupts` 전후와 `dmesg` 전체 (정지 건수와 인터럽트 이상의 상관), ③ 폴링 입출력 대조(호스트 설정 변경 필요, 내일).
- 위 표의 주장 문장은 증거가 나오기 전에는 쓰지 않는다.
- 팀 문서(README, firmware-spec, 절차 v8.2)는 저장소에 없어 확인하지 못했다. 다르면 팀 문서가 우선.

## 6. 오늘 만든 도구

| 도구 | 용도 |
|---|---|
| `tools/trace_lookup.py trace.bin <lba...>` | 특정 LBA의 펌웨어 기록 한 줄 조회(호스트 정지 몇 건을 빠르게 확인) |
| `tools/trace_where.py trace.bin --fio-log ro --fio-log reader` | fio 시계와 펌웨어 시계를 정상 읽기로 맞춰 정지를 before / fw / after로 나눔. 합성 데이터로만 검증, **실제 데이터는 아직 안 돌림** (fio 로그를 Windows PC로 옮겨야 함) |
| `~/m12/run_one.sh TAG RQD ROT` (호스트) | DEV 확인, 중복 방지, 인터럽트 전후, `dmesg` 전체, fio, 묶기를 한 줄로. **보드에서 돌려본 적 없음**(S2에서 첫 사용) |

## 7. 남은 일정 (오늘 안에 전부)

| 순서 | 회차 | 빌드 | 명령 |
|---|---|---|---|
| 0 | R1 업로드 마무리 | - | trace.bin, host.tgz, 부팅 로그 |
| 1 | S2 | S-Buf | `~/m12/run_one.sh sbuf_m1_r2 1 60` |
| 2 | R2 | R-Buf | `~/m12/run_one.sh rbuf_m1_r2 1 60` |
| 3 | M2 S | S-Buf | `~/m12/run_one.sh sbuf_m2_r1 8 10` |
| 4 | M2 R | R-Buf | `~/m12/run_one.sh rbuf_m2_r1 8 10` |
| 5 | S3 | S-Buf | `~/m12/run_one.sh sbuf_m1_r3 1 60` |
| 6 | R3 | R-Buf | `~/m12/run_one.sh rbuf_m1_r3 1 60` |

회차마다: 부팅 배너 확인 → 호스트 켜기 → `run_one.sh` → **보드를 끄기 전에** XSCT 덤프(`mrd 0x00300000 8`로 recCount N 확인, `mrd -bin -file <TAG>_trace.bin 0x00300000 <1024+N×16>`, 크기 4096+N×64) → 호스트 로그 업로드 후 호스트 끄기 → trace.bin 업로드는 다음 부팅과 병행. 회차당 약 15~18분(덤프 시간은 미측정, 이번에 측정).

## 8. 정해야 할 것, 모르는 것

| 항목 | 상태 |
|---|---|
| M2 `ROT=10` 팀 전달 확인 | 리뷰어 승인, 팀 전달 확인 필요 |
| 호출 수 규칙의 지위 | 보조 보기로 두었고 팀 확인 필요 |
| 정지 위치(before-fetch / after-DMA) | `trace_where.py` 실제 데이터 결과 대기 |
| 인터럽트 이상의 원인 | 원인과 S-Buf 쪽 재현 여부 모름. 회차마다 기록 중 |
| 덤프와 업로드 시간 | 미측정 |
| 호스트 설정 변경(폴링 입출력 대조) | 팀 확인 후, 오늘 6회차 뒤 또는 내일 |
| 메인 루프 간격 계측 코드 | 결과가 before-fetch일 때를 대비해 미리 준비 제안(오늘 측정에는 넣지 않음) |
