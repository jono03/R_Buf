# 실험 계획서: M1·M2 계측 측정 (2026-10-09)

논문 주 실험이다. 쓰기가 NAND 처리 속도를 계속 넘는 **지속 쓰기 폭주**에서 R-Buf 이후에도 남는 초 단위 읽기 정지가 **어느 구간에서 생기는지** 계측 로그로 나눈다.
기획 문서(`team-paper-idea.md`, `team-experiment-procedure.md` 11·12절, `firmware-spec.md`, `README.md`)와 다르면 기획 문서가 우선한다. 이 문서는 그 내용을 하루 작업 순서로 풀어 쓴 것이다.

**전제:** 이 계획은 아래 0절의 관문이 모두 통과했다고 가정한다. 하나라도 안 되면 그 관문이 먼저다. 시간 수치는 추정이다.

## 0. 시작 전에 통과해야 하는 관문 (실험 전날 또는 당일 오전)

| # | 관문 | 통과 기준 | 안 되면 |
|---|---|---|---|
| G1 | SDK 빌드 | `trace-handoff` zip의 `firmware-src` 11개를 덮어쓰고 Clean → Build, Problems 에러 0개 | 에러 문구를 기록해 수정 |
| G2 | 부팅·동작 | UART에 `[ RBUF=.. TRACE=1 .. ]`와 `[ TRACE base=0x00300000 max=.. shift=6 .. ]`가 나오고 `nvme list`에 Cosmos+가 보이며 짧은 fio가 돈다 | `docs/handoff-trace-log-2026-10-08.md` 6절 |
| G3 | 덤프 | 짧은 fio 후 `trace.bin`을 꺼내 `trace_parse.py`가 해석(`magic=0x45435254`) | JTAG이 안 되면 UART 덤프 빌드(`-DTRACE_UART_DUMP=1 -DTRACE_UART_MIN_MS=1`) |
| G4 | 레코드 값 | 시각이 `dBufAlloc ≤ dEnqueue ≤ dIssue ≤ dTrigDone ≤ dXferIssue ≤ dNandDone ≤ dDmaStart ≤ dDmaEnd`, 읽기만 펌웨어 내부 지연 < 227 µs, `saturated` 거의 없음 | 기록 지점 수정 |
| G5 | 팀 결정 | M2의 `ro` 구간 길이(아래 2절), 폴링 보정 보기의 지위(아래 8절) | 결정 전에는 M2를 돌리지 않는다 |
| G6 | 실습실·보드 | 10/9(휴일) 출입 가능, JTAG·UART 연결 확인 | 일정이 하루씩 밀림 |

## 1. 준비물

- 빌드 두 개: **S-Buf**(`RBUF_ENABLE 0`)와 **R-Buf**(`RBUF_ENABLE 1`), 둘 다 `TRACE_ENABLE 1`, `VERIFY_PRINT 0`. 두 빌드는 `RBUF_ENABLE`만 달라야 한다.
  - 빌드 후 `Debug/run-rbuf.elf`를 `sbuf_trace_<커밋>.elf`, `rbuf_trace_<커밋>.elf`로 복사해 두고 Launch에서 경로를 직접 고른다(회차마다 다시 빌드하지 않기 위함, 이 SDK에서 되는지는 첫 회차에 확인. 안 되면 회차마다 `RBUF_ENABLE`을 바꿔 다시 빌드).
- 호스트: fio 3.28, python3, `lsblk`, `nvme-cli`. 저장소의 `tools/trace_parse.py`, `tools/trace_uart2bin.py`.
- JTAG(`xsct`) 또는 UART 로그 저장(SDK Terminal의 로그 저장 기능, 저장 방법은 첫 회차에 확인).
- 작업 폴더: 호스트 `~/m12/` (아래 구조).

```
~/m12/
  rbuf_check.fio  trace_parse.py  trace_uart2bin.py
  sbuf_m1_r1/  rbuf_m1_r1/  sbuf_m1_r2/ ...  sbuf_m2_r1/  rbuf_m2_r1/
      <TAG>.txt (fio 출력)  <TAG>_ro_clat.2.log  <TAG>_reader_clat.3.log  <TAG>_writer_iops.4.log
      <TAG>_uart.txt  <TAG>_trace.bin  <TAG>.csv  <TAG>_parse.txt  <TAG>_dmesg.txt
  runlog.md   (7절 표)
```

## 2. fio (`rbuf_check.fio`)

팀의 `rbuf_check.fio`(README 6절)를 그대로 쓴다. **차이는 `[ro]`의 `runtime`을 환경변수 `ROT`로 바꾼 것 하나뿐이다**(M1은 60으로 팀 파일과 같다).

```
cat > rbuf_check.fio <<'EOF'
[global]
ioengine=libaio
direct=1
filename=${DEV}
group_reporting=1
lat_percentiles=1
percentile_list=50:99:99.9

[prefill]
rw=write
bs=128k
iodepth=32
offset=0
size=8g

[ro]
stonewall
rw=randread
bs=4k
iodepth=${RQD}
offset=0
size=8g
time_based
runtime=${ROT}
write_lat_log=${TAG}_ro
log_offset=1

[reader]
stonewall
rw=randread
bs=4k
iodepth=${RQD}
offset=0
size=8g
startdelay=2
time_based
runtime=3600
write_lat_log=${TAG}_reader
log_offset=1

[writer]
rw=randwrite
bs=16k
iodepth=32
offset=8g
size=16g
exitall=1
write_iops_log=${TAG}_writer
log_avg_msec=1000
EOF
```

| 실험 | `RQD` | `ROT` | 계측 레코드 예상 | 비고 |
|---|---|---|---|---|
| M1 | 1 | 60 | `ro` 약 26만 + 폭주 구간 약 1만 = 약 27만 | 로그 최대 50만 건 안 |
| M2 | 8 | **10 (제안)** | `ro` 약 16만 + 폭주 구간 수만 | `ROT=60`이면 `ro`만 93~100만 건이라 50만 건을 채워 **폭주 구간 기록이 사라진다** (G5) |

- 로그 파일 번호는 fio 파일 안의 job 순서다: prefill=1, ro=2, reader=3, writer=4. **`ls`로 실제 이름을 확인**한다.
- 부팅당 쓰기 24GB(채우기 8 + 폭주 16)라 GC 한도(약 49GB) 안이다. **한 부팅에 한 회차만.**
- 읽기 동시성은 R-Buf 읽기 칸 수 8 이하다(M1 1, M2 8).

## 3. 회차별 절차 (S1 R1 S2 R2 S3 R3, 이어서 M2 S R)

### 3-1. 부팅

1. 호스트 PC를 종료한다.
2. SDK: **Program FPGA**(`sys_top_wrapper.bit`) → Launch(해당 ELF) → 이전 세션을 종료할지 물으면 Yes.
3. UART 로그를 파일로 저장하기 시작한다(`<TAG>_uart.txt`).
4. 부팅 줄을 확인한다.
   - `[ RBUF=0|1 RBUF_ENTRIES=0|8/128 TRACE=1 VERIFY=0 ]`: 빌드가 맞는지(RBUF 값)
   - `[ TRACE base=0x00300000 max=500000 shift=6 counts/s=… ]`
5. `Turn on the host PC`가 나오면 호스트를 켠다.

### 3-2. 호스트 확인

```
cd ~/m12
bind 'set enable-bracketed-paste off'
DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}'); echo "DEV=$DEV"
sudo nvme list
```

`DEV=`가 비었거나 두 줄이면 중단한다(시스템 SSD `SSSTC CL4-8D512`와 번호가 부팅마다 바뀐다).

### 3-3. 실행

```
TAG=sbuf_m1_r1        # 빌드_실험_회차: sbuf|rbuf, m1|m2, r1|r2|r3
sudo dmesg -C
sudo DEV=$DEV TAG=$TAG RQD=1 ROT=60 fio --output=$TAG.txt rbuf_check.fio    # M2: RQD=8 ROT=10
sudo dmesg | grep -iE "timeout|abort|reset" | tee ${TAG}_dmesg.txt
ls ${TAG}_*
```

- 약 3분(prefill 36 s + `ro` + 폭주 약 75 s). 실행 중에는 아무것도 하지 않는다.
- **끝나면 보드를 끄거나 재부팅하지 않는다**(DRAM의 로그가 사라진다).
- UART 덤프 빌드면 fio 종료 5초 뒤부터 UART로 출력이 나온다. 끝날 때까지(`[TRC] END`) 기다린다.

### 3-4. 덤프 (JTAG, 보드 시험 전, `tools/trace_dump.md`)

```
xsct
connect
targets -set -filter {name =~ "ARM*#0"}
mrd 0x00300000 8                     # 헤더, 세 번째 워드 = recCount (N)
mrd -bin -file <TAG>_trace.bin 0x00300000 <워드 수>     # 워드 수 = 1024 + N*16
```

- UART 덤프 빌드면: 저장한 UART 로그에서 `python3 tools/trace_uart2bin.py <TAG>_uart.txt <TAG>_trace.bin`.
- **첫 회차에서 어느 방법이 되는지 확인하고 이후 같은 방법으로 통일한다.**

### 3-5. 해석과 점검

```
python3 -I trace_parse.py ${TAG}_trace.bin \
    --fio-log ${TAG}_ro_clat.2.log --fio-log ${TAG}_reader_clat.3.log \
    --csv ${TAG}.csv | tee ${TAG}_parse.txt
cat ${TAG}_ro_clat.2.log ${TAG}_reader_clat.3.log | wc -l      # fio 읽기 수
```

회차 점검표(전부 통과해야 그 회차를 쓴다):

| 점검 | 기준 | 안 되면 |
|---|---|---|
| 부팅 배너 | `RBUF` 값이 의도한 빌드 | 회차 폐기 |
| UART에 `[GC]` | 없음 | 회차 폐기(GC 배제 조건 위반) |
| `dmesg` | timeout·abort·reset 없음 | 기록 후 판단 |
| 헤더 `stopFlag`, `dropped` | 0, 0 | 로그가 가득 참 → 그 회차는 불완전, 용량 조정 후 재실행 |
| 레코드 수 | fio 읽기 수와 거의 같음(차이가 크면 매칭 오류) | 기록 지점 점검 |
| `bufReadEvictCnt` | R-Buf = 0, S-Buf > 0 | R-Buf가 0이 아니면 구현 오류. 중단하고 알림 |
| `saturated` | 거의 없음 | 시간 단위 점검 |
| `ro` 구간 읽기만 | 기존 `rbuf2`와 비슷(QD1: 약 4,364 IOPS) | 계측 부담 의심 |
| 쓰기 | 폭주 구간 IOPS 약 14K, writer가 16GB를 마치고 종료 | 기록 후 판단 |

### 3-6. 보관

`~/m12/<TAG>/` 폴더에 그 회차의 모든 파일을 옮긴다. `runlog.md`(7절)에 한 줄을 적는다. **회차 하나가 끝날 때마다 구글 드라이브 백업.**

## 4. 실행 순서와 우선순위

**순서(계획서 고정):** M1은 S1 → R1 → S2 → R2 → S3 → R3, 이어서 M2 S → R. 빌드가 번갈아 바뀌므로 순서 효과(보드 온도 등)가 한쪽으로 쏠리지 않는다.

시간이 부족하면 아래 순서로 자른다(위쪽이 더 중요).

| 단계 | 회차 | 의미 |
|---|---|---|
| A | M1 S1, R1 | 파이프라인 확인 + 주 대비. 이게 안 되면 나머지는 의미 없음 |
| B | M1 S2, R2 | 반복 2회(범위 표시 가능) |
| C | M2 S, R | 주장 범위(읽기 동시성) 결정 |
| D | M1 S3, R3 | 계획서의 3회 |

## 5. 하루 일정 (추정, 시작 09:00 가정)

| 시간 | 내용 | 비고 |
|---|---|---|
| 09:00~10:00 | 관문 G1~G6 최종 확인, 호스트 준비(`~/m12`, fio 파일, 도구) | 전날 못 한 것이 있으면 여기서 처리 |
| 10:00~10:50 | **M1 S1** (파이프라인 끝까지: 덤프 → 해석 → 점검) | 덤프 방법 확정 |
| 10:50~11:30 | M1 R1 | |
| 11:30~12:10 | M1 S2 | |
| 12:10~12:50 | M1 R2 | 점심 |
| 12:50~13:30 | M2 S | 팀 결정(ROT) 반영 |
| 13:30~14:10 | M2 R | |
| 14:10~14:50 | M1 S3 | |
| 14:50~15:30 | M1 R3 | |
| 15:30~ | 전체 점검, 폐기·재실행 판단, 데이터 백업, 첫 분석 시작 | 예비 시간 |

회차당 약 40분으로 잡았다(부팅·fio 약 15분 + 덤프·해석·점검 약 25분, 덤프 시간은 미확인). 막힘이 없을 때의 값이다.

## 6. 문제가 생기면

| 상황 | 대응 |
|---|---|
| 첫 회차 덤프가 안 됨 | UART 덤프 빌드로 전환. M1은 `TRACE_UART_MIN_MS=1`(1 ms 이상만. 줄 수는 측정 전이라 모르지만 폭주 구간 읽기가 약 1만 건이므로 1만 줄 이하, 약 2~3분) |
| UART 덤프도 안 됨 | 계측 없는 빌드(`TRACE_ENABLE=0`)로 M1을 6회 새로 측정(절차 문서 11절 사용 규칙). 주장은 "R-Buf로도 정지가 남는다"까지 |
| `stopFlag=1` | `TRACE_MAX_RECORDS`를 늘리거나 `ROT`를 줄여 그 회차 재실행 |
| `[GC]`가 찍힘 | 그 회차 폐기, 재부팅 후 재실행 |
| NVMe가 안 잡힘 | `Program FPGA` 후 재Launch. 반복되면 호스트 재부팅 |
| `dmesg`에 timeout | 어느 회차인지 기록. S-Buf의 30초 정지가 timeout이었는지 판정에 쓰인다 |
| 회차끼리 결과가 크게 다름 | 폐기하지 말고 그대로 기록하고 한 번 더 실행 |
| 시간 부족 | 4절 순서대로 자름 |

## 7. 실행 기록 (`runlog.md`, 회차마다 한 줄)

| TAG | 빌드(RBUF) | 커밋 | 부팅 배너 | GC | dmesg | recCount / fio 읽기 수 | stopFlag | 읽기 eviction | 정지(≥1 s, 호스트) | 사용 가능 | 메모 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sbuf_m1_r1 | 0 | | | | | | | | | | |

## 8. 분석 계획 (10/10, 측정 후)

판정 규칙은 **실험 전에 고정**한다(절차 문서 12.4절). 데이터를 보고 바꾸지 않는다.

1. **1층 정지 사건:** 호스트 지연이 1초 이상인 읽기마다 구간(fetch 전 / 버퍼 / die 큐 / 루프 / 읽기 전송 대기 / NAND+DMA)을 보고 정지 시간의 대부분이 어느 구간인지 사건별로 표시.
2. **2층 p99 이상:** 폭주 구간에서 p99보다 느린 읽기들의 구간별 시간 합 ÷ 전체 합. 한 구간 비중 > 50%이고 같은 구성 3회 모두 1위이면 지배 원인, 아니면 혼합.
3. 두 층이 같은 구간을 가리키면 확정, 엇갈리면 둘 다 보고하고 정지 사건(1층)을 주 결과로.
4. 케이스 판정: A(die 큐), B(루프), 혼합, N1(읽기 전송 대기), N2(fetch 전). 판정 문장은 측정 후에 채운다.
5. **두 보기:** `trace_parse.py`는 팀 규칙 보기(주)와 폴링 보정 보기(보조)를 함께 출력한다. 보정 기준값(0.3 ms)은 추정이다. 보정 보기를 주 결과로 격상할지는 **팀이 데이터를 보기 전에** 정한다(G5).
6. 루프 굶주림 판정: 긴 대기에 `schedTrig`·`schedXfer`(스케줄러 호출 횟수)가 거의 없으면 루프가 폴링하지 않은 것, 많으면 NAND/die가 실제로 바쁜 것. **"루프가 늦게 알아챈다"는 가설은 이 값으로 판정하기 전에는 결론에 쓰지 않는다.**
7. 산출: 그림 1(정지·p99 이상 읽기의 구간 구성, S-Buf/R-Buf), 그림 2(읽기 지연 시계열 + 초당 쓰기 IOPS, 대표 1회), 표 2(읽기만 / 폭주 QD1 / 폭주 QD8별 p50·p99·p99.9, 정지 건수·시간 비율, 정지 아닌 읽기 평균, 쓰기 IOPS).
8. S-Buf에서는 버퍼 대기가 보여야 한다(구현 확인). R-Buf에서 버퍼 대기가 0에 가까워야 한다(성질 확인). 아니면 구현 오류.
9. 계측 부담: M1 R-Buf의 `ro` 구간 읽기만 IOPS를 계측 없는 `rbuf2`(4,364 IOPS, 정지 시간 비율 75%)와 비교해 한 문장으로 쓴다.

## 9. 같은 표·그림 안에서 섞지 않는 것

- 계측 있는 빌드(M1·M2)와 없는 빌드(E1, 이전 QD1 `sbuf1`·`rbuf_q1`)의 값을 같은 표·그림에 섞지 않는다. `rbuf2`는 계측 부담 확인과 서론의 예비 실험 한 문장에만 쓴다.
- 폐기한 회차는 지우지 않고 사유와 함께 `runlog.md`에 남긴다.

## 10. 팀 확인이 필요한 것 (측정 전)

| # | 질문 | 제안 |
|---|---|---|
| 1 | M2 `ro` 구간 길이 (로그 용량) | `ROT=10`. 코드 변경 없음, JTAG 덤프도 빠름 |
| 2 | 폴링 보정 보기를 주 결과로 쓸지 | 팀 규칙 보기를 주로, 보정 보기는 보조(데이터를 보기 전에 확정) |
| 3 | 레코드 형식 version 3(`pad` 4바이트에 스케줄러 호출 수) | 승인 요청 |
| 4 | 덤프 방법(JTAG/UART) 실패 시 계측 없는 빌드로 가는 기준 | 첫 회차 결과로 판단 |
| 5 | 저장소에 실습실 마이크로코드 포함(비공개 유지 확인) | README는 비공개 유지로 되어 있음 |

## 11. 알려진 한계 (논문에 적을 것)

- M1 각 3회, M2 각 1회라 반복이 적다.
- `tDieLast`·`tNandDone`·`tTrigDone` 등은 폴링으로 확인한 시각이라 실제 완료보다 늦을 수 있다.
- 계측이 지연에 주는 영향은 `rbuf2` 비교로만 확인한다.
- 버퍼 2MB, 읽기 칸 8, 쓰기 16KB, GC 배제, 읽기·쓰기 영역 분리, 읽기 QD1·8 조건에서의 결과다.
