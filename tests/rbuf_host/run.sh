#!/bin/sh
# Host-side (no board) check of the R-Buf LRU list logic in data_buffer.c.
# Random read/write mix; verifies list integrity, single hash copy per LSA,
# writes never land in the read list, read-list entries never dirty.
set -e
D=$(cd "$(dirname "$0")" && pwd); W=$(mktemp -d)
cp "$D"/*.c "$D"/*.h "$W"/ && cp "$D"/../../source/software/GreedyFTL-3.0.0/data_buffer.[ch] "$W"/
gcc -DRBUF_ENABLE=0 -I"$W" "$W/test.c" "$W/data_buffer.c" -o "$W/t0" && "$W/t0"
for n in 4 16 32; do gcc -DRBUF_ENABLE=1 -DRBUF_ENTRY_COUNT=$n -I"$W" "$W/test.c" "$W/data_buffer.c" -o "$W/t1" && "$W/t1"; done
# VERIFY_PRINT path: compile + run once with stubbed XTime (syntax/behaviour of the counter print)
gcc -DRBUF_ENABLE=1 -DVERIFY_PRINT=1 -I"$W" "$W/test.c" "$W/data_buffer.c" -o "$W/tv" && "$W/tv" | grep -c "CNT" | sed "s/^/VERIFY_PRINT counter lines: /"
