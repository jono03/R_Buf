#!/bin/bash
# E1 (team procedure 9.4 / 11): read-only vs mixed, our conditions:
#   read 4KB in [0, READ_SIZE), write 16KB in [READ_SIZE, READ_SIZE+WRITE_SIZE),
#   only the read area is prefilled, GC avoided by keeping total writes small.
# usage: ./e1.sh <tag>      e.g. ./e1.sh rbuf1   -> <tag>_*.txt
TAG=$1
[ -z "$TAG" ] && { echo "usage: $0 <tag>"; exit 1; }
DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}')
[ -z "$DEV" ] && { echo "OpenSSD not found"; exit 1; }
[ "$(echo "$DEV" | wc -l)" -ne 1 ] && { echo "multiple devices: $DEV"; exit 1; }
echo "DEV=$DEV"
READ_SIZE=${READ_SIZE:-8G}
WRITE_SIZE=${WRITE_SIZE:-8G}
RT=${RT:-60}

job() { # name numjobs rw bs offset size
cat <<EOF

[$1]
rw=$3
bs=$4
numjobs=$2
offset=$5
size=$6
EOF
}
global() {
cat <<EOF
[global]
ioengine=libaio
direct=1
filename=$DEV
time_based
runtime=$RT
iodepth=32
group_reporting=1
percentile_list=95:99
EOF
}

{ global; job reader 4 randread 4k 0 $READ_SIZE; } > e1_ro4.fio
{ global; job reader 2 randread 4k 0 $READ_SIZE; } > e1_ro2.fio
{ global; job reader 2 randread 4k 0 $READ_SIZE; job writer 2 randwrite 16k $READ_SIZE $WRITE_SIZE; } > e1_mix.fio

echo "== prefill read area ($READ_SIZE) =="; date
sudo fio --name=prefill --filename=$DEV --direct=1 --ioengine=libaio \
  --rw=write --bs=128k --iodepth=32 --offset=0 --size=$READ_SIZE \
  --output=${TAG}_prefill.txt || exit 1
echo "== read only, 4 jobs =="; date
sudo fio e1_ro4.fio --output=${TAG}_ro4.txt || exit 1
echo "== read only, 2 jobs =="; date
sudo fio e1_ro2.fio --output=${TAG}_ro2.txt || exit 1
echo "== mixed: read 2 + write 2 =="; date
sudo fio e1_mix.fio --output=${TAG}_mix.txt || exit 1
date; echo done
grep -H -E "IOPS=|clat \(usec\)|95th" ${TAG}_ro4.txt ${TAG}_ro2.txt ${TAG}_mix.txt
