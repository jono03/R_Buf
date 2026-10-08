#!/bin/bash
# Host-side logic test of trace_log.c (stub headers, fake clock). usage: tests/trace_host/run.sh
set -e
cd "$(dirname "$0")"
SRC=$(pwd)/../../source/software/lab-rbuf/src
TOOLS=$(pwd)/../../tools
B=$(mktemp -d)
cp test_dump.c host_pre.h ftl_config.h xil_printf.h xtime_l.h memory_map.h request_allocation.h data_buffer.h garbage_collection.h test.c "$B"/
cp "$SRC/trace_log.c" "$SRC/trace_log.h" "$B"/
cat > "$B/trace_mem.c" <<'EOM'
char traceMem[0x1000 + 64 * 8] __attribute__((aligned(4096)));
EOM
cd "$B"
gcc -std=gnu99 -Wall -Wextra -Wno-unused-parameter -m64 \
  -DTRACE_TIME_SHIFT=0 -DTRACE_MAX_RECORDS=8 \
  '-DTRACE_BASE_ADDR=((size_t)traceMem)' -include host_pre.h \
  test.c trace_log.c trace_mem.c -o trace_host_test
./trace_host_test

# UART dump -> bin -> parser (shift 6, 3 records, the third is a 2.7 s read)
gcc -std=gnu99 -Wall -Wno-format -m64 -DTRACE_UART_DUMP=1 -DTRACE_TIME_SHIFT=6 -DTRACE_MAX_RECORDS=8 \
  '-DTRACE_BASE_ADDR=((size_t)traceMem)' -include host_pre.h \
  test_dump.c trace_log.c trace_mem.c -o trace_dump_test 2>/dev/null
./trace_dump_test > dump.txt
test "$(grep -c '^\[TRC\] R ' dump.txt)" = "3" || { echo "FAIL: expected 3 [TRC] R lines"; exit 1; }
test "$(grep -c '^\[TRC\] BEGIN' dump.txt)" = "1" || { echo "FAIL: expected exactly one dump"; exit 1; }
python3 -I "$TOOLS/trace_uart2bin.py" dump.txt dump.bin
python3 -I "$TOOLS/trace_parse.py" dump.bin --stall-ms 1000 | tail -6
echo "UART DUMP PIPELINE OK"
