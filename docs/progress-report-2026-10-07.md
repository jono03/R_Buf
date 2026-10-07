# R-Buf 재구현·검증 진행 기록 (2026-10-07, 팀 공유용)

R-Buf 최소 재구현과 보드 실험을 오늘까지 한 내용을 순서대로 정리한 문서. **측정값은 대부분 1회 측정**이고, 결론이 아니라 현재 상태와 다음 할 일을 공유하는 용도다. 팀 기획 문서(`team-paper-idea`, `team-experiment-procedure`, `firmware-spec`, `firmware-decisions`)와 다르면 기획 문서가 우선한다.

## 0. 한 줄 요약

- R-Buf(읽기용·쓰기용 LRU 분리) **최소 재구현은 동작**하고, fio verify 1종과 PC 로직 테스트를 통과했다.
- 쓰기가 최대 속도로 몰리는 조건(읽기 QD1)에서 R-Buf는 **읽기 지연 분포를 크게 줄였다** (중앙값 약 5.7배, p99 약 1.9배, p99.9 약 47배, 기존·R-Buf 각 1회).
- 같은 조건에서 **읽기 하나가 수 초~수십 초 멈추는 현상이 기존(S-Buf)·R-Buf 둘 다에 남아 있다** (기존 최대 30.0 s, R-Buf 최대 23.9 s). R-Buf만의 버그가 아니라 이 펌웨어의 성질로 보이고, 논문의 "R-Buf 이후 남는 대기" 후보다.
- 반면 기획서 조건이 아닌 워크로드(4KB 쓰기, 장치 전체 채움)에서는 R-Buf가 **읽기에서 오히려 나빴다** → 아직 논문 방향과 같다고 말할 수 없다.
- 기획서의 완료 조건(verify 4종, 카운터, E1 방향 확인)은 **아직 다 못 채웠다**. 아래 §8 체크리스트 참고.

## 1. 환경

| 항목 | 값 |
|---|---|
| 보드 | Cosmos+ OpenSSD, NAND 컨트롤러 `T4NFC_HLPER` (공개판 GreedyFTL과 다름), 채널 레지스터 `T4REGS` |
| 구성 | 4채널 × 2way → `USER_DIES = 8`, 2048 블록/die, SLC 256 페이지/블록, 노출 용량 약 61.8 GB (`storage capacity 58952 MB`) |
| 버퍼 | `16 × USER_DIES = 128칸 × 16KB = 2MB`. R-Buf 읽기 칸 = `1 × USER_DIES = 8칸` (128KB), 쓰기 120칸 |
| 호스트 | Ubuntu, fio 3.28, 시스템 SSD 512GB(SSSTC)가 같이 있음 (아래 §7 안전 주의) |
| 빌드 | Xilinx SDK. `run-gftl3`(원본), `run-rbuf`(원본 복사본, R-Buf 작업용) |
| 부팅 동작 | 부팅마다 전체 erase + 매핑 초기화(빈 장치). 백그라운드 GC 없음, GC는 쓰기 경로에서 동기 실행 |

실습실 `ftl_config.h`는 공개판과 다르다(`NUMBER_OF_CONNECTED_CHANNEL 4`, `USER_WAYS 2`, `NSC_x_UCODEADDR` 등). **공개판 `ftl_config.h`로 통째로 덮어쓰면 `NSC_0_UCODEADDR undeclared` 오류가 난다.** 이 저장소의 `board-config/ftl_config.h`가 실습실 설정에 스위치만 추가한 파일이다.

## 2. 저장소 상태

브랜치 `claude/new-session-hkspsr` (원격 `jono03/R_Buf`). 문서 사양의 `fix/lab-base`(실습실 펌웨어 전체 원본 커밋)는 **아직 아니다**: 저장소에는 공개판 GreedyFTL-3.0.0 + 보드 설정만 있고, 실습실 고유 파일(`ftl_config.c`, `nsc_driver.*` 등)은 없다.

| 커밋 | 내용 |
|---|---|
| `4915b3c` | 순정 GreedyFTL-3.0.0 + GPLv3 `LICENSE` (첫 커밋은 순정) |
| `9aae966` | 최소 R-Buf 구현(`RBUF_ENABLE`), 호스트 로직 테스트 |
| `9b45101` | `board-config/ftl_config.h` (4ch×2way) |
| `0e78c7d`, `1ecb4e2` | 부팅·진단 출력, `RBUF_ENTRY_COUNT` 조절 매크로 |
| `94599c3`, `12853b4` | `tools/e1.sh`(E1 fio), `tools/e1_table.py`(논문 형식 비교표) |
| `67550f1` | 호스트 테스트: 쓰기 직후 읽기는 쓰기 칸 dirty 항목에 hit |
| `e7e28f1` 이후 | 사양 카운터(읽기가 일으킨 eviction), 부팅 배너, `VERIFY_PRINT`/`TRACE_ENABLE` 매크로, 측정 중 UART 출력 제거 |

## 3. R-Buf 구현 (원 논문 §4.2의 재구현)

저자 코드(rw-rbuf)는 하드웨어 레지스터가 달라 쓰지 않았다. 논문 설계를 순정 버퍼 위에 다시 만들었다.

- **바꾼 것(`data_buffer.c/h`, `request_transform.c`)**: 버퍼 엔트리 배열 앞 `RBUF_ENTRY_COUNT`개를 읽기 LRU 리스트, 나머지를 쓰기 LRU 리스트로 분리. `AllocateDataBuf(reqCode)`: 읽기는 읽기 리스트 꼬리, 쓰기는 쓰기 리스트 꼬리에서 자리를 받음. hit 시 LRU 갱신은 자기 리스트 안에서만. 엔트리에 소속 비트(`inReadList`) 추가.
- **그대로 둔 것**: 버퍼 배열·hash·blocking 체인·eviction·NAND 읽기 경로·완료 경로·메모리 맵.
- **쓰기가 읽기 칸에 hit할 때**: 읽기 칸을 hash에서 제거·무효화하고 쓰기는 쓰기 칸을 새로 받음(논문 §4.2.3의 "플래그 전환 + 최우선 처리"와 다름, 한계로 명시).
- **읽기 칸은 항상 clean**: `assert(dirty == CLEAN)`로 보호.
- **스위치(`ftl_config.h`)**: `RBUF_ENABLE`(0 = 기존, 1 = R-Buf), `RBUF_ENTRY_COUNT`(기본 `1*USER_DIES`), `TRACE_ENABLE`(미구현, 0), `VERIFY_PRINT`(검증 빌드에서만 1).

### 논문 R-Buf와 다른 점 (논문에 밝혀야 할 것)

| 항목 | 논문 | 우리 |
|---|---|---|
| 구조 | 읽기·쓰기 버퍼 분리 | 같은 배열의 LRU 리스트 분리 (hash 등 공유) |
| 읽기 칸 | 2MB (128칸) | 128KB (8칸) |
| 버퍼 총량 | 32MB | 2MB |
| 쓰기가 읽기 칸에 hit | 플래그 전환 | 무효화 |

## 4. 검증 현황

| 검증 | 결과 |
|---|---|
| PC 로직 테스트 `tests/rbuf_host/run.sh` (읽기 칸 4/16/32, 20만 회 무작위, 리스트 무결성·단일 hash·읽기 칸 clean·쓰기 후 읽기는 쓰기 칸 hit) | 통과 |
| 보드 fio verify (16KB randrw, 1GB, QD16) 기존·R-Buf 각각 | `err=0` 통과 |
| R-Buf 실행 중 `assert`(읽기 칸 dirty) | 멈춘 적 없음 (단, SDK 빌드에 `NDEBUG`가 켜져 있는지는 미확인) |
| 읽기 칸이 실제로 쓰이는지 | 이전 진단 출력 `read alloc`이 계속 증가, `write-hit-invalidate`는 0~9 (읽기·쓰기 영역 분리라 예상대로) |
| **미검증** | 좁은 영역 덮어쓰기 verify(`--size=16m --norandommap --serialize_overlap=1`), 4KB randrw 64MB verify, 16KB randwrite 8GB 전체 verify, 읽기 eviction 카운터 보드 확인, 로그 덤프 |

## 5. 보드 실험 결과

### 5-1. 4KB 쓰기 · 장치 전체 채움 (⚠️ 기획서 조건이 아님)

`dd`로 전체 채운 직후, 4KB, QD32, 60초. 12월 F1(원 논문 조건)에 가까운 조건이다.

| 항목 | 기존(S-Buf) | R-Buf (읽기 칸 8) |
|---|---|---|
| 읽기만 2 jobs IOPS / 평균 지연 / p95 | 23.3K / 2.75 ms / 6.8 ms | 16.7K / 3.83 ms / 10.2 ms |
| 섞기(읽기 2 + 쓰기 2) 읽기 IOPS(합) | 약 6.4K | 약 4.1K |
| 섞기 읽기 평균 지연 / p95 | 10.05 ms / 21.4 ms | 15.7 ms / 45.3 ms |
| 섞기 쓰기 IOPS(합) | 약 6.4K | 약 7.0K |

- 기존 빌드: 섞기에서 읽기와 쓰기가 **같은 속도(6.4K / 6.4K)와 같은 p95(약 21 ms)로 묶임** → 논문 Table 3의 S-Buf와 같은 모양(읽기·쓰기 동일 성능). 읽기만 대비 읽기 IOPS는 약 3.7배 감소.
- 기존 빌드 B를 재채움 없이 3회 연속 돌리면 읽기 6.4K → 1.3K → 0.73K로 무너짐(GC/여유 블록 고갈). **B는 매번 채움 직후 1회만 유효.**
- R-Buf는 이 조건에서 읽기가 더 나쁨. 추정 원인: 동시 읽기 64개인데 읽기 칸이 8개뿐이라 칸을 기다림. 확인은 읽기 칸 크기 실험 필요(미실행).
- 주의: 한 번은 R-Buf 결과가 기존과 완전히 같게 나왔는데, 원인은 `run-rbuf/Debug`에 복사된 옛 `run-gftl3.elf`를 올린 것이었다(§7). 그 결과는 폐기.

### 5-2. 읽기 QD1 + 쓰기 최대 속도 (기획서 E2에 가까움)

읽기 영역 8GiB만 순차 채움(229 MiB/s, 35.8 s), 읽기 4KB QD1 offset 0~8g, 쓰기 16KB QD32 offset 8g~24g(16GiB), `exitall`. 누적 쓰기 24GiB로 예산(약 49GB) 안.

| 항목 | 기존(S-Buf) `sbuf1` | R-Buf `rbuf_q1` |
|---|---|---|
| 읽기만 IOPS / p50 / p99.9 / 최대 | 4,358 / 227 µs / 379 µs / 1.23 ms | 4,364 / 227 µs / 343 µs / 0.78 ms |
| 섞기 중 읽기 횟수(약 74초) | 약 3,800 | 약 8,000 |
| 섞기 읽기 p50 | 4 ms | 0.70 ms |
| 섞기 읽기 p99 | 17 ms | 9.1 ms |
| 섞기 읽기 p99.9 | 3,876 ms | 83 ms |
| 섞기 읽기 평균 / 최대 | 19.3 ms / **30.0 s** | 9.19 ms / **23.9 s** |
| 쓰기 IOPS / 평균 지연 | 14.2K / 2.248 ms | 14.2K / 2.244 ms |

- 읽기만 값이 두 빌드에서 같아 비교 기준이 같다는 것은 확인됨.
- 기존 빌드의 백분위 `4 / 17 / 3876`은 **ms 단위로 가정**했다(fio 단위 줄을 확인하지 못함). `grep "clat percentiles" sbuf1.txt`로 확인 필요.
- 기존 빌드 지연 로그(`sbuf1_reader_clat.3.log`)에서 1초 이상 걸린 읽기가 4건: 완료 시각/지연 = 11.7 s/8.69 s, 47.6 s/30.04 s, 57.0 s/3.88 s, 70.8 s/11.20 s. **합 53.8 s로 실행 74 s의 약 73%**. 정지는 실행 전체에 흩어져 있고 시작·종료 아티팩트가 아님.
- R-Buf는 같은 지연 로그를 아직 안 뽑았다(`rbuf2` 예정). R-Buf의 수십 초 정지 횟수·합계는 미확인.
- 단일 회차 결과. 평균·IOPS는 수십 초 정지 한 번에 좌우되므로 비교는 p99·p99.9·최대 위주로.

## 6. 해석과 한계

- **말할 수 있는 것**: 쓰기가 몰리는 조건(QD1 읽기, 16KB 쓰기)에서 R-Buf가 읽기 지연 분포를 줄였다. 쓰기 처리량 손실은 이 조건에서 보이지 않음(논문 Table 3의 쓰기 −22%와는 다름).
- **말할 수 없는 것**: (1) "버퍼 eviction 대기가 없어져서 줄었다"는 원인 — 계측(구간 분해)과 읽기 eviction 카운터로 확인 전. (2) 논문과 같은 방향 — 문서 조건 E1(읽기만 vs 섞기 QD32, 읽기 4 jobs / 2 jobs)을 아직 안 돌림. (3) 5-1에서는 반대 방향이 나옴.
- **수십 초 정지**: 기존과 R-Buf 둘 다에 있다. R-Buf는 설계상 읽기가 eviction을 기다리지 않는데도 24 s 정지가 남았다면 그 정지는 버퍼 층이 아니라 die 큐·메인 루프·NAND 층에서 생긴 것이다(가설). 기획서의 "R-Buf 이후 남는 대기" 주 결과 후보. 원인 규명 전에는 고치는 대상이 아니라 분석 대상.
- 비교 조건 차이(논문과): 버퍼 2MB vs 32MB, 읽기 칸 8 vs 128, 16KB 쓰기, GC 배제, 읽기 영역만 채움. 표 아래에 명시해야 한다.
- 모든 값은 **1회 측정**. 방향이 일관되는지 각 빌드 2~3회 반복 필요.

## 7. 작업하면서 알게 된 함정 (팀원 필독)

1. **보드를 새로 올릴 때는 Program FPGA를 먼저 한다.** 보드 전원을 껐다 켰거나, 호스트가 NVMe 초기화에 실패한 뒤에는 펌웨어(ELF)만 다시 올려서는 호스트가 장치를 못 잡았다(`Device not ready; aborting reset, CSTS=0x1`, 보드 로그는 Identify(`OPC: 6`) 직후 중단). **Xilinx → Program FPGA(`sys_top_wrapper_hw_platform_0`, `sys_top_wrapper.bit`) 후** 올리면 정상. 순서: 호스트 종료 → Program FPGA → Launch → 로그에 `Turn on the host PC` → 호스트 켜기.
2. **장치 번호는 부팅마다 바뀐다.** 어떤 부팅에서는 OpenSSD가 `nvme0n1`, 어떤 부팅에서는 시스템 SSD가 `nvme0n1`이었다. **`nvme0n1`을 외워서 `dd`/fio에 쓰면 시스템 디스크가 지워진다.** 항상 모델명으로 찾는다.
   ```
   DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}'); echo "DEV=$DEV"
   ```
   비어 있거나 두 줄이면 중단. 시스템 SSD 모델은 `SSSTC CL4-8D512`.
3. **Launch할 때 ELF 선택 창에서 `run-rbuf.elf`인지 확인.** 프로젝트를 복사하면 `Debug/`에 옛 `run-gftl3.elf`가 따라오고 기본 선택이 그것이라 R-Buf 대신 기존 펌웨어가 올라간 적이 있다. 부팅 배너로 확인한다(`[ R-Buf OFF ]` / `[ RBUF=1 ... ]`).
4. 프로젝트를 복사해서 쓰면 **Clean Project 후 빌드**(옛 `.o`·의존성 파일 영향 방지).
5. 빌드마다 R-Buf 로그/배너로 어느 빌드인지 확인. 결과 파일 이름에 빌드(`sbuf`/`rbuf`)와 회차를 넣는다.
6. 터미널 붙여넣기에서 `^[[200~`가 명령 앞에 붙어 명령이 깨지는 일이 있었다. 먼저 `bind 'set enable-bracketed-paste off'`.
7. 부팅마다 전체 erase → **회차마다 재부팅 + 채움**. 누적 쓰기가 용량의 약 80%(약 49GB)를 넘으면 GC가 켜져 측정이 무너진다.
8. `dmesg`에 `irq 150: nobody cared` / `Disabling IRQ #150`이 한 번 떴다(초기화 실패 반복 뒤). 호스트 재부팅 후 `dmesg | grep -i -E "nobody cared|Disabling IRQ|Device not ready"`가 비어 있어야 정상.

## 8. 기획서(firmware-spec) 완료 조건 대비

| 항목 | 상태 |
|---|---|
| LRU 분리, 쓰기→읽기 칸 무효화, 읽기 칸 clean assert, 기존 구조 유지 | ✅ |
| 읽기 칸 8, 버퍼 총량 128칸 유지 (기본값) | ✅ |
| `RBUF_ENABLE` 스위치 | ✅ |
| `TRACE_ENABLE`/`VERIFY_PRINT` 매크로, 부팅 배너(`RBUF/TRACE/VERIFY`) | ✅ 코드 반영(**보드 확인 전**) |
| 읽기가 일으킨 eviction 카운터 | ✅ 코드 반영(**보드 확인 전**). GC 진입 카운터는 실습실 `garbage_collection.c` 필요로 ❌ |
| 측정 중 UART 출력 금지 | ✅ 코드 반영 (`VERIFY_PRINT` 0이면 출력 없음) |
| fio verify 4종 (두 빌드) | ❌ 1종만 통과 |
| 요청별 계측 로그 + 덤프 | ❌ 미구현 |
| 기준 소스 = 실습실 원본(`fix/lab-base`) | ❌ 저장소에 실습실 원본 미커밋 |
| E1 방향 확인(문서 조건) | ❌ 미실행 |

## 9. 다음 할 일 (순서)

1. **카운터 빌드 반영**: `data_buffer.h/c`, `ftl_config.h`, `request_transform.c` 교체 → Clean → Build (에러 0개) → 두 빌드 부팅 배너 확인.
2. **verify 3종 추가**(좁은 영역 덮어쓰기 / 4KB randrw 64MB / 16KB randwrite 8GB) 기존·R-Buf 각각. `VERIFY_PRINT=1` 빌드로 R-Buf `readEvict = 0`, 덮어쓰기에서 `invalidate > 0` 확인.
3. **E1(문서 조건)**: `tools/e1.sh`를 기존·R-Buf로 각각 실행 → `tools/e1_table.py`로 논문 형식 표(읽기 지연 배수, 읽기 IOPS, p95, 쓰기 IOPS) 작성.
4. **정지 규명**: R-Buf로 같은 QD1 fio를 지연 로그 포함해 재실행(`rbuf2`)하고 1초 이상 지연 목록을 기존과 비교. 이후 `request_transform.c`에 구간 시각 기록(버퍼 의존성 대기 vs 나머지) 추가, 필요하면 실습실 `src` 압축본을 받아 `fix/lab-base` + 문서 사양의 5구간 로그.
5. 회차 반복(기존·R-Buf 각 2~3회)으로 방향 일관성 확인.

## 10. 팀 결정이 필요한 것

- **읽기 칸 수 A4**: 문서는 1×USER_DIES(8칸) 유지. 5-1 결과(읽기 칸 부족 의심) 때문에 `RBUF_ENTRY_COUNT`(기본값은 문서 사양 그대로)를 조절 가능하게만 해 두었다. 8 → 16 → 32 → 64 민감도 실험을 논문 한계/보강으로 할지.
- 5-1처럼 기획서 조건이 아닌 워크로드 결과(R-Buf 열세)를 논문에 어떻게 다룰지(12월 F1로 넘김?).
- 수십 초 정지를 논문 주 결과로 쓸지, 메인 루프·die 큐 처방은 12월로 미룰지.

## 11. 재현 명령

```bash
# 장치 확인 (필수)
bind 'set enable-bracketed-paste off'
DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}'); echo "DEV=$DEV"

# 정합성(16KB randrw 1GB)
sudo fio --name=verify --filename=$DEV --direct=1 --ioengine=libaio --rw=randrw --bs=16k --size=1g \
  --iodepth=16 --verify=crc32c --verify_backlog=1024 --verify_fatal=1

# 문서 조건 E1 (읽기 영역 8GB만 채움, 16KB 쓰기): 재부팅 직후 1회
./tools/e1.sh <tag>        # 결과: <tag>_ro4.txt, <tag>_ro2.txt, <tag>_mix.txt
python3 tools/e1_table.py sbuf_ro4.txt sbuf_mix.txt rbuf_ro4.txt rbuf_mix.txt

# PC 로직 테스트
./tests/rbuf_host/run.sh
```

QD1 + 쓰기 최대 속도 fio(5-2)는 `[prefill] rw=write bs=128k offset=0 size=8g` → `[ro] stonewall rw=randread bs=4k iodepth=1 offset=0 size=8g time_based runtime=60` → `[reader] stonewall rw=randread bs=4k iodepth=1 offset=0 size=8g startdelay=2 time_based runtime=3600 write_lat_log=<tag>_reader log_offset=1` + `[writer] rw=randwrite bs=16k iodepth=32 offset=8g size=16g exitall=1` 구성이다 (`filename=$DEV`, `lat_percentiles=1`, `percentile_list=50:99:99.9`).
