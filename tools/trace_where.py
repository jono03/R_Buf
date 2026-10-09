#!/usr/bin/env python3
"""Where does a host-visible stall sit relative to the firmware's service window?

usage: trace_where.py trace.bin --fio-log ro_clat.2.log --fio-log reader_clat.3.log [--stall-ms 1000]

For every host read slower than --stall-ms (default 1000 ms) that is matched to a firmware record (order + LBA, like
trace_parse.py), split the host latency into
  before = firmware fetch time - host submit time      (command waited before the firmware started handling it)
  fw     = firmware tFetch .. host DMA end             (what trace_parse.py decomposes)
  after  = host completion time - firmware DMA end     (completion reporting / interrupt / host side)
The fio clock (ms since job start, one clock per job log) and the firmware XTime clock are aligned per log file with the
median of (firmware DMA end - fio completion time) over matched reads faster than --fast-ms (default 2 ms): for those
reads the host sees the completion about 10-30 us after the firmware finished, so the alignment error is small.
fio logs (write_lat_log, log_offset=1) store the COMPLETION time in the first column (a read that ends when the job
ends has a log time close to the job run time).
A clock drift check (median offset of the first / last 10% of the fast reads) is printed; it should be well below the
stall lengths being analysed.
"""
import sys
import trace_parse as t


def load_logs(paths):
    files = []
    for p in paths:
        part = []
        for line in open(p):
            f = [x.strip() for x in line.split(",")]
            if len(f) < 5 or not f[0].isdigit() or f[2] != "0":
                continue
            part.append((int(f[0]), int(f[1]) / 1e6, int(f[4])))
        part.sort()
        files.append(part)
    return files


def median(v):
    v = sorted(v)
    return v[len(v) // 2] if v else None


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    stall = float(a[a.index("--stall-ms") + 1]) if "--stall-ms" in a else 1000.0
    fast = float(a[a.index("--fast-ms") + 1]) if "--fast-ms" in a else 2.0
    paths = [a[i + 1] for i, x in enumerate(a) if x == "--fio-log"]
    h, recs = t.load(a[0])
    unit = (1 << h["timeShift"]) * 1000.0 / h["countsPerSecond"]
    cps = float(h["countsPerSecond"])
    by_lba = {}
    for r in recs:
        by_lba.setdefault(r["lba"], []).append(r)
    pos = {k: 0 for k in by_lba}
    files = load_logs(paths)
    unmatched = 0
    for fi, part in enumerate(files):
        pairs = []                                  # (fio time ms, host lat ms, record)
        for tm, lat, off in part:
            lst = by_lba.get(off // 4096)
            if lst is None or pos[off // 4096] >= len(lst):
                unmatched += 1
                continue
            pairs.append((tm, lat, lst[pos[off // 4096]]))
            pos[off // 4096] += 1
        diffs = [((r["tFetch"] * 1000.0 / cps) + r["dDmaEnd"] * unit - tm, tm) for tm, lat, r in pairs if lat < fast]
        if not diffs:
            print("%s: no fast matched reads, cannot align clocks" % paths[fi])
            continue
        off = median([d for d, _ in diffs])
        k = max(1, len(diffs) // 10)
        drift = median([d for d, _ in diffs[-k:]]) - median([d for d, _ in diffs[:k]])
        print("%s: matched %d of %d reads, clock offset %.3f ms, drift first->last 10%%: %+.3f ms"
              % (paths[fi], len(pairs), len(part), off, drift))
        rows = []
        for tm, lat, r in pairs:
            if lat < stall:
                continue
            fw_start = r["tFetch"] * 1000.0 / cps
            fw_end = fw_start + r["dDmaEnd"] * unit
            done = tm + off
            rows.append((tm, lat, fw_start - (done - lat), r["dDmaEnd"] * unit, done - fw_end, r))
        for tm, lat, before, fw, after, r in rows:
            where = "before-fetch" if before > after else "after-DMA"
            print("  fio t=%d ms  host=%.1f ms  before=%.1f  fw=%.3f  after=%.1f  -> %s  (lba=%d seq=%d)"
                  % (tm, lat, before, fw, after, where, r["lba"], r["seq"]))
        print("  stalls >= %.0f ms in this log: %d (before-fetch %d, after-DMA %d)" % (
            stall, len(rows), sum(1 for x in rows if x[2] > x[4]), sum(1 for x in rows if x[2] <= x[4])))
    print("unmatched fio reads: %d" % unmatched)


if __name__ == "__main__":
    main()
