# 실험·분석 분담 (2026-10-09)

실험 담당이 회차를 돌려 데이터를 Google Drive에 올리고, 분석 담당이 받아서 해석한다.
관련 문서: `docs/experiment-plan-2026-10-09.md`(회차 절차), `docs/handoff-trace-log-2026-10-08.md`(코드와 기록 형식), `docs/progress-2026-10-09.md`(오늘 진행).

## 1. 역할

| 역할 | 하는 일 | 하지 않는 일 |
|---|---|---|
| **실험 담당** | 빌드 교체, 보드 부팅, fio 실행, JTAG 덤프, 데이터 업로드, `runlog.md` 기록 | 해석 결과를 보고 실험 순서를 바꾸지 않는다(이상이 있으면 분석 담당과 상의) |
| **분석 담당** | 업로드된 회차 데이터 해석, 값 점검(sanity), 정지 분해, 표·그림 초안 | 보드와 호스트를 쓰지 않는다 |

## 2. 데이터 흐름

```
[보드] --JTAG(Windows PC, XSCT mrd)--> <TAG>_trace.bin ----+
[호스트 PC] fio 결과 --tar--> <TAG>_host.tgz --------------+--> Google Drive --> 분석 담당 PC (python3)
[Windows PC] UART 부팅 로그 --> boot_<TAG>.txt ------------+
```

- 덤프는 JTAG이 연결된 Windows PC에서만 할 수 있다(호스트는 보드를 NVMe 디스크로만 본다).
- 보드 DRAM의 기록은 재부팅하면 사라지므로 **덤프를 마치기 전에 보드를 끄지 않는다.**
- 호스트 PC는 다음 부팅 때 꺼야 하므로 **fio 로그를 Drive에 올린 뒤에** 끈다.

## 3. Drive 폴더와 이름 규칙

```
3조/10-09/data/
  sbuf_m1_r1/
    sbuf_m1_r1_trace.bin       (덤프, M1은 약 17MB)
    sbuf_m1_r1_host.tgz        (fio 요약·지연 로그·dmesg 묶음)
    boot_sbuf_m1_r1.txt        (UART 부팅 로그)
  rbuf_m1_r1/ ...
runlog.md                      (회차마다 한 줄, 아래 5절)
```

- TAG 규칙: `빌드_실험_회차`. 빌드 `sbuf`|`rbuf`, 실험 `m1`|`m2`, 회차 `r1`|`r2`|`r3`.
- 회차마다 폴더를 따로 만든다. 한 폴더에 섞지 않는다.

## 4. 실험 담당: 회차마다 할 일

1. 해당 빌드로 보드 부팅. UART 배너에서 확인: `[ RBUF=0 ... ]`(S-Buf) 또는 `[ RBUF=1 RBUF_ENTRIES=8/128 ... ]`(R-Buf), 그리고 `TRACE=1`. 부팅 로그를 `boot_<TAG>.txt`로 저장.
2. "Turn on the host PC"가 나온 뒤 호스트 켜기, 장치 확인(`DEV`는 모델 `Cosmos+ OpenSSD`로 찾는다).
3. `~/m12`에서 fio 실행(약 3분). 한 줄씩 붙여넣는다(여러 줄을 한 번에 붙이면 중복·누락이 생긴다).
   ```
   TAG=sbuf_m1_r1
   sudo dmesg -C
   sudo DEV=$DEV TAG=$TAG RQD=1 ROT=60 fio --output=$TAG.txt rbuf_check.fio
   sudo dmesg | grep -iE "timeout|abort|reset" | tee ${TAG}_dmesg.txt
   ls ${TAG}_*
   ```
   M2는 `RQD=8 ROT=10`.
4. **보드를 끄지 않고** Windows PC의 XSCT에서 덤프.
   ```
   connect
   targets -set -filter {name =~ "ARM*#0"}
   mrd 0x00300000 8
   ```
   세 번째 워드가 recCount(N). 첫 워드 `45435254`, 두 번째 `00000003`, 네 번째(stopFlag)는 `0`이어야 한다. M1은 약 27만, M2는 약 16만이 정상.
   ```
   mrd -bin -file <TAG>_trace.bin 0x00300000 <1024 + N×16>
   ```
   파일 크기는 `4096 + N×64` 바이트여야 한다(S1: N=270,807, 17,335,744바이트). **덤프 시작과 끝 시각을 기록한다.**
5. 호스트에서 `dmesg` 전체와 인터럽트 상태를 저장한 뒤 묶기(`Disabling IRQ`, timeout 줄은 `grep timeout|abort|reset`에 안 걸리는 것도 있으므로 전체를 남긴다):
   ```
   sudo dmesg > ${TAG}_dmesg_full.txt
   cat /proc/interrupts | grep -i nvme > ${TAG}_interrupts.txt
   cd ~/m12 && tar czf <TAG>_host.tgz <TAG>*
   ```
6. 3개 파일을 회차 폴더에 업로드하고 `runlog.md`에 한 줄 추가.
7. 업로드를 확인한 뒤 호스트를 끄고 다음 회차 부팅.

## 5. `runlog.md` (회차마다 한 줄)

| 항목 | 예 |
|---|---|
| TAG, 시작 시각 | `sbuf_m1_r1`, 11:12 |
| 빌드 | S-Buf (`RBUF_ENABLE=0`), 커밋 `2340e73` |
| recCount, stopFlag | 270807, 0 |
| 덤프 걸린 시간 | (측정값) |
| fio 읽기 최대 지연 | 4.82 s |
| 이상한 점 | (없으면 "없음") |

## 6. 분석 담당: 받은 회차를 해석하는 법

준비: python3, `trace_parse.py`(zip의 `tools/`). 회차 폴더에서:

```
tar xzf <TAG>_host.tgz
python3 trace_parse.py <TAG>_trace.bin --fio-log <TAG>_ro_clat.2.log --fio-log <TAG>_reader_clat.3.log
```

- fio 로그 번호는 `ls`로 확인한다(prefill=1, ro=2, reader=3, writer=4). **ro를 먼저** 쓴다.
- 해석에 쓰는 보조 옵션: `--stall-ms 1000`(정지 기준), `--phys-ms <읽기만 실험의 p99>`(호출 수 규칙의 물리 시간 기준), `--csv out.csv`.

### 6-1. 먼저 확인할 값 (sanity)

| 점검 | 정상 |
|---|---|
| `time-order violations` | 약 0 |
| `saturated` | 거의 0 |
| `stopFlag`, `dropped` | 0, 0 |
| R-Buf 읽기 엔트리 플래그 | R-Buf 빌드 약 100%, S-Buf 빌드 0% |
| 버퍼 히트 | 1% 미만 |
| `fetch-before` 중앙값 | 작음(읽기만 구간에서 약 10 µs). **음수 개수 0** |
| `matched` | 대부분 짝지어져야 한다(fio 읽기 수에 가까움) |

음수가 많거나 `matched`가 낮으면 짝짓기 오류이므로 **해석을 믿지 말고 실험 담당에게 알린다.**

### 6-1b. 호스트 정지의 위치 (`trace_where.py`)

`trace_parse.py`의 `fetch-before`는 "호스트 − 펌웨어" 전체라서 명령을 가져오기 전과 DMA 이후를 구분하지 못한다. 구분은 `trace_where.py`로 한다(같은 폴더에 `trace_parse.py`가 있어야 한다).

```
python3 trace_where.py <TAG>_trace.bin --fio-log <TAG>_ro_clat.2.log --fio-log <TAG>_reader_clat.3.log --stall-ms 1000
```

- fio 로그와 펌웨어 XTime의 시계를 빠른 읽기(2 ms 미만)로 맞춘 뒤, 1초 이상 호스트 읽기마다 `before`(펌웨어가 가져오기 전), `fw`(펌웨어 구간), `after`(DMA 이후)로 나눈다.
- 출력의 `clock offset`과 `drift`(처음 10% 대비 마지막 10%의 어긋남)가 정지 길이(초 단위)보다 훨씬 작은지 먼저 본다.
- 한 LBA에 기록이 여러 건이면 짝짓기가 모호해지므로 그 정지는 따로 표시한다.
- `trace_lookup.py <TAG>_trace.bin <lba...>`는 특정 LBA의 펌웨어 기록만 본다(호스트 지연이 큰 읽기 몇 건을 빠르게 확인할 때).

### 6-2. 보고할 것

1. sanity 줄 전부
2. `firmware-internal read latency`(p50, p99, p99.9, max)
3. 호스트 지연 1초 이상 정지의 수, 각각의 `fetch-before`와 분해(buffer, dieq, loop, xferwait, nanddma)
4. 세 가지 보기의 차이: 팀 규칙(주), 폴링 보정(보조), 호출 수 규칙(보조). 판정은 팀 규칙이 기준이다.
5. 이상한 점

### 6-3. 분해 규칙 메모

- 주 결과는 **팀 규칙**(트리거, 전송, DMA 시간은 모두 NAND+DMA).
- 호출 수 규칙(보조): 구간의 평균 폴링 간격 = 길이 ÷ (스케줄러 호출 수+1)이 1 ms를 넘으면 물리 시간 초과분을 루프로 본다. 호출 수 규칙의 지위는 팀 확인이 필요하다.
- 같은 표 안에서 서로 다른 보기를 섞지 않는다.

## 7. S1에서 이미 나온 것 (분석 담당 참고)

| 항목 | 값 |
|---|---|
| 빌드 | S-Buf, `RBUF=0`, `TRACE=1` |
| 레코드 | 270,807건, `stopFlag` 0, `dropped` 0, 시간순서 위반 0, `saturated` 0 |
| R-Buf 엔트리 플래그 | 0.0% (S-Buf로 맞음) |
| 펌웨어 내부 지연 | p50 0.224 ms, p99 9.5 ms, p99.9 13.5 ms, **max 25.4 ms** |
| 펌웨어 기준 정지(≥1000 ms) | 없음 |
| p99 초과 2,708건 분해(팀 규칙) | 버퍼 55.2%, die 큐 42.6%, NAND+DMA 2.2%, 루프·읽기 전송 대기 약 0% |
| fio reader 읽기(14,175건) | **최대 지연 4.82 s**, 평균 5.4 ms, p99 18 ms |
| 쓰기 폭주 | 16GiB, 76 s, 215 MiB/s, `gcCnt` 0 |

- 호스트가 본 최대 4.82초와 펌웨어 내부 최대 25.4 ms가 크게 다르다. 이 차이는 펌웨어가 명령을 가져오기 **전**(fetch-before)일 수도 있고, 펌웨어가 DMA를 끝낸 **뒤**(완료 항목 게시, MSI 인터럽트 전달, 호스트 처리)일 수도 있다. 기록은 둘을 구분하지 못한다(`trace_parse.py`의 `fetch-before`는 "호스트 − 펌웨어" 전체이며 이름과 달리 두 구간을 합친 값이다). 요청 단위 짝짓기(`--fio-log`)로 크기를 보는 것이 첫 분석 과제이고, 위치 판정은 별도 근거가 필요하다.
- R1에서 호스트 `dmesg`에 `Disabling IRQ #150`(NVMe 인터럽트 비활성화)과 `I/O ... timeout, completion polled`가 나왔고 fio 최대 지연이 30.17 s(커널 I/O timeout 30 s)였다. 인터럽트가 꺼진 큐의 완료가 timeout 때 폴링으로만 회수된 호스트 쪽 인공물일 가능성이 있다. 이 가능성이 확인되기 전에는 호스트 최대 지연을 펌웨어 정지로 해석하지 않는다.
- 이 회차는 시험 회차를 겸한다. 짝짓기가 처음으로 실제 데이터에 적용된다.

## 8. 진행 순서와 동기화

| 단계 | 실험 담당 | 분석 담당 |
|---|---|---|
| 지금 | S1 데이터 업로드 | S1 해석(짝짓기 확인이 최우선), 결과 보고 |
| 분석 결과가 오기 전 | R1 진행 | - |
| 이후 | S2, R2, M2 S, M2 R, S3, R3 순으로 업로드 | 올라오는 대로 해석, 회차 간 비교는 모든 회차가 모인 뒤 |

- S1의 짝짓기에 문제가 있으면 다른 회차를 이어 돌리기 전에 고친다.
- 이상이 있는 회차(배너 불일치, `stopFlag` 1, 덤프 크기 불일치 등)는 해당 회차를 재실행 목록에 올린다.

## 9. 알려진 한계와 주의

- 오늘 첫 본 회차이므로 **덤프 시간, M1 recCount, 짝짓기, 쓰기 폭주 중 계측 안정성**이 처음 검증되는 항목이다.
- fetch-before 구간은 펌웨어 기록이 없고 호스트 지연에서 펌웨어 지연을 빼서 추정한다.
- 타이머는 500 MHz(`counts/s=500000000`). 시간 차이 단위는 약 0.128 µs(64 카운트), int32 범위는 약 275 s.
- M2는 `ROT=10`으로 돌린다(로그 용량). 이 결정은 리뷰어 승인을 받았고 팀 전달 확인이 필요하다.
- 부팅 로그의 Erase FAIL, bad block 출력은 오늘 두 부팅에서 같은 블록 번호로 반복되었다(보드 고유 출력으로 보임).
