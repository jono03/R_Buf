#!/bin/sh
# Host-side (no board) check of the R-Buf LRU list logic in data_buffer.c.
# Random read/write mix; verifies list integrity, single hash copy per LSA,
# writes never land in the read list, read-list entries never dirty.
set -e
D=$(cd "$(dirname "$0")" && pwd); W=$(mktemp -d)
cp "$D"/*.c "$D"/*.h "$W"/ && cp "$D"/../../source/software/GreedyFTL-3.0.0/data_buffer.[ch] "$W"/
for r in 0 1; do gcc -DRBUF_ENABLE=$r -I"$W" "$W/test.c" "$W/data_buffer.c" -o "$W/t$r" && "$W/t$r"; done
