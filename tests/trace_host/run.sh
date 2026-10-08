#!/bin/bash
# Host-side logic test of trace_log.c (stub headers, fake clock). usage: tests/trace_host/run.sh
set -e
cd "$(dirname "$0")"
SRC=$(pwd)/../../source/software/lab-rbuf/src
B=$(mktemp -d)
cp host_pre.h ftl_config.h xil_printf.h xtime_l.h memory_map.h request_allocation.h data_buffer.h garbage_collection.h test.c "$B"/
cp "$SRC/trace_log.c" "$SRC/trace_log.h" "$B"/
cat > "$B/trace_mem.c" <<'EOM'
char traceMem[0x1000 + 64 * 8] __attribute__((aligned(4096)));
EOM
cd "$B"
gcc -std=gnu99 -Wall -Wextra -Wno-unused-parameter -m64 \
  -DTRACE_TIME_SHIFT=0 -DTRACE_MAX_RECORDS=4 \
  '-DTRACE_BASE_ADDR=((size_t)traceMem)' -include host_pre.h \
  test.c trace_log.c trace_mem.c -o trace_host_test
./trace_host_test
