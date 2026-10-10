#!/bin/bash
cd ~/m12 || exit 1
TAG=$1; RQD=$2; ROT=$3
[ -n "$TAG" ] && [ -n "$RQD" ] && [ -n "$ROT" ] || { echo "usage: ./run_one_uring.sh TAG RQD ROT"; exit 1; }
DEV=$(lsblk -dno NAME,MODEL | awk '/Cosmos/{print "/dev/"$1}')
[ -n "$DEV" ] && [ "$(echo "$DEV" | wc -l)" = 1 ] || { echo "DEV problem: [$DEV]"; exit 1; }
[ -e rbuf_check_uring.fio ] || { echo "rbuf_check_uring.fio not found"; exit 1; }
ls ${TAG}_* > /dev/null 2>&1 && { echo "files for $TAG already exist, stop"; exit 1; }
POLL=$(cat /sys/block/$(basename $DEV)/queue/io_poll)
{ sudo dmesg | grep -iE "poll queues"; echo "poll_queues=$(cat /sys/module/nvme/parameters/poll_queues) io_poll=$POLL"; } > ${TAG}_queues.txt
cat ${TAG}_queues.txt
[ "$POLL" = 1 ] || { echo "io_poll is not 1 on $DEV, stop"; exit 1; }
echo "DEV=$DEV TAG=$TAG RQD=$RQD ROT=$ROT (io_uring, interrupt)"
sudo dmesg -C
grep -i nvme /proc/interrupts > ${TAG}_interrupts_before.txt
date +%T > ${TAG}_start.txt
sudo DEV=$DEV TAG=$TAG RQD=$RQD ROT=$ROT fio --output=$TAG.txt rbuf_check_uring.fio
date +%T > ${TAG}_end.txt
grep -i nvme /proc/interrupts > ${TAG}_interrupts_after.txt
sudo dmesg > ${TAG}_dmesg_full.txt
sudo dmesg | grep -iE "timeout|abort|reset|Disabling IRQ|nobody cared" | tee ${TAG}_dmesg.txt
tar czf /tmp/${TAG}_host.tgz ${TAG}* && mv /tmp/${TAG}_host.tgz . && ls -l ${TAG}_host.tgz
echo "DONE $TAG: now dump from XSCT. Do NOT power off the board."
