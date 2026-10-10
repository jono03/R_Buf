#!/usr/bin/env python3
"""check_wrap.py <TAG>_trace.bin [N]

Tests whether R-Buf read buffer waits come from LRU wrap-around (head-of-line blocking):
reads take the LRU tail of the read list without checking that it is idle, so read k reuses
the slot of read k-N (N = read slots). If read k-N is still in flight, read k waits for it.

For each N in [N-1, N, N+1, 2N] it prints how much buffer wait is explained by
"read k-N had not finished when read k got its slot". The mechanism holds if the share is
high at the true N and drops sharply at the other N (control).
Format: trace record v3 (64 B, '<IIQ7iHHiiHHHH'), header 19 words.
"""
import sys, struct

REC = struct.Struct('<IIQ7iHHiiHHHH')
F_HIT, F_RBUF = 0x0001, 0x0002

d = open(sys.argv[1], "rb").read()
h = struct.unpack_from("<19I", d, 0)
n, cps, sh, off, nslot = h[2], h[8], h[9], h[12], h[7]
if len(sys.argv) > 2:
    nslot = int(sys.argv[2])
ms = lambda c: c * 1000.0 / cps
recs = [REC.unpack_from(d, off + 64 * i) for i in range(min(n, (len(d) - off) // 64))]
# r: 0 seq, 1 lba, 2 tFetch, 3 dBufAlloc, 4 dEnqueue, 5 dDieLastDone, 6 dIssue, 7 dNandDone, 8 dDmaStart, 9 dDmaEnd, 10 flags
al = [r for r in recs if (r[10] & F_RBUF) and not (r[10] & F_HIT)]
al.sort(key=lambda r: r[2] + (r[3] << sh))                    # allocation order = tBuf
t_buf = [r[2] + (r[3] << sh) for r in al]
t_enq = [r[2] + (r[4] << sh) for r in al]
t_end = [r[2] + (r[9] << sh) for r in al]
wait = [ms(e - b) for b, e in zip(t_buf, t_enq)]
W = 0.05                                                      # ms, "waited" threshold
tot_wait = sum(wait)
waited = [k for k in range(len(al)) if wait[k] > W]
print("trace: %d records, %d read-list allocations, rbufEntries(header)=%d, testing N=%d" % (len(recs), len(al), h[7], nslot))
print("buffer wait: total %.1f ms, reads waiting > %.2f ms: %d (%.2f%%)" % (tot_wait, W, len(waited), 100.0 * len(waited) / max(1, len(al))))
print("| N | reads with k-N in flight | of waited reads, explained | of wait time, explained | median |enq(k) - end(k-N)| ms |")
print("|---|---|---|---|---|")
for N in sorted(set([max(1, nslot - 1), nslot, nslot + 1, 2 * nslot])):
    busy = [k >= N and t_end[k - N] > t_buf[k] for k in range(len(al))]
    nb = sum(busy)
    expl = [k for k in waited if busy[k]]
    wt = sum(wait[k] for k in expl)
    gap = sorted(abs(ms(t_enq[k] - t_end[k - N])) for k in expl)
    med = gap[len(gap) // 2] if gap else float("nan")
    print("| %d%s | %d (%.2f%%) | %.1f%% | %.1f%% | %.3f |" % (
        N, " (true)" if N == nslot else "", nb, 100.0 * nb / max(1, len(al)),
        100.0 * len(expl) / max(1, len(waited)), 100.0 * wt / max(1e-9, tot_wait), med))
