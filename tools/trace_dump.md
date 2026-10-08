# 계측 로그 덤프와 해석 (TRACE_ENABLE=1 빌드)

로그는 보드 DRAM의 `0x00300000`부터 있다(uncached). 앞 4KB = 헤더(`TRACE_HDR`), 그 뒤 64B 레코드.
레코드 수는 헤더의 `recCount`(3번째 32비트 워드)에 있다.

## 1. 덤프 (JTAG, xsct) — 10/8 시험 항목, 아직 보드에서 시험하지 않음

실험(fio)이 **끝난 뒤**, 보드를 끄지 말고 호스트 PC가 아니라 보드에 JTAG이 연결된 PC에서:

```
xsct
connect
targets -set -filter {name =~ "ARM*#0"}
# 1) 헤더만 먼저 읽어 recCount 확인 (워드 8개)
mrd 0x00300000 8
# 2) recCount = N 이면 워드 수 = (0x1000 + N*64)/4 = 1024 + N*16
mrd -bin -file trace.bin 0x00300000 <워드 수>
```

- `mrd`는 기본 32비트 워드 단위다. 워드 수는 위 식으로 계산한다(예: N = 10000 → 161024).
- 읽기 중 CPU가 도는 상태에서 DRAM을 읽는 것이 되는지는 보드에서 확인 필요. 안 되면 `stop`으로 CPU를 멈춘 뒤 읽는다(그 뒤 이 실행은 끝난 것으로 본다).
- xsct 구문이 이 SDK 버전과 다르면 `help mrd`로 확인. 안 되면 spec 5절 대안(UART 출력)으로.

## 1-2. UART 덤프 (JTAG이 안 될 때, `TRACE_UART_DUMP=1` 빌드)

실험이 끝나고 5초 동안 I/O가 없으면 보드가 로그를 UART로 한 번 출력한다(약 1만 건에 2분).
SDK Terminal 출력을 파일로 저장한 뒤:

```
python3 tools/trace_uart2bin.py uart_log.txt trace.bin
```

QD8처럼 레코드가 많으면 `-DTRACE_UART_MIN_MS=10`으로 빌드해 10 ms 이상 레코드만 출력한다.

## 2. 해석

```
python3 tools/trace_parse.py trace.bin --csv trace.csv \
    --fio-log <TAG>_ro_clat.1.log --fio-log <TAG>_reader_clat.2.log
```

`--fio-log`(fio `write_lat_log`, `log_offset=1`)를 주면 호스트 지연으로 정지를 고르고 fetch 전 대기를 계산한다(fio 로그 파일 이름의 번호는 실행마다 다를 수 있으니 `ls`로 확인). 호스트 지연 없이도 실행되지만 fetch 전(N2) 정지는 보이지 않는다.

- 헤더 값(카운터: GC, 읽기 eviction, 읽기 칸 할당, 무효화), 레코드 수, 중단 플래그 출력.
- 읽기별 구간(buffer / dieq / loop / xferwait / nanddma)과 p99 이상·1초 이상 정지 읽기의 구간 비중, 정지 목록.
- 시간 단위는 `2^timeShift` XTime count(기본 timeShift 6 ≈ 0.19 us). 헤더의 `countsPerSecond`로 환산한다.
- 호스트 fio 지연 로그와의 짝짓기(fetch 전 대기)는 절차 문서 12.1대로 요청 순서 + LBA로 별도 수행.

## 3. 확인할 것 (매 회차)

- UART 부팅 줄: `[ RBUF=… TRACE=1 … ]`, `[ TRACE base=0x00300000 max=500000 shift=6 counts/s=… ]`
- `[GC]` 줄이 없을 것
- 덤프 헤더: `magic=0x45435254`, `stopFlag=0`, R-Buf 빌드에서 `bufReadEvictCnt=0`
