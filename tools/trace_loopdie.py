#!/usr/bin/env python3
"""Is the die-queue wait real die/NAND busy time, or does the main loop notice a finished die late?

usage: trace_loopdie.py trace.bin [--ro-s 60] [--tail-ms 1.0]

Each SchedulingNandReq() call is one pass over all channels (status check, issue). The record field schedDieQ is the number
of passes between die-queue insertion (dEnqueue) and the read-trigger issue (dIssue). So over that window
    W        = dIssue - dEnqueue
    interval = W / (schedDieQ + 1)            average time between two passes
A die that finishes is noticed at most about one interval later. A read that waited behind `aheadCnt` requests on its die
(plus its own trigger) is therefore delayed by at most about (aheadCnt + 1) * interval by the loop:
    loop estimate = min(W, (aheadCnt + 1) * interval)       (upper estimate of the main-loop share)
    die  estimate = W - loop estimate                        (time the die/channel was really busy)
This is an estimate from averages (a single long gap between passes is not visible), so also look at 'passes/ms' and the
share of reads whose interval is above 0.1 ms / 1 ms. schedDieQ is clamped at 65535 (interval then is an upper bound).

Reads are split like trace_phases.py (boot = unmapped, ro = first --ro-s seconds of mapped reads, storm = the rest).
'tail' = storm reads with dieq window W >= --tail-ms (default 1 ms).
"""
import sys
import trace_parse as t


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p / 100.0))] if v else float("nan")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    ro_s = float(a[a.index("--ro-s") + 1]) if "--ro-s" in a else 60.0
    tail_ms = float(a[a.index("--tail-ms") + 1]) if "--tail-ms" in a else 1.0
    h, recs = t.load(a[0])
    if h["version"] < 3:
        sys.exit("needs format version 3 (schedDieQ)")
    unit = (1 << h["timeShift"]) * 1000.0 / h["countsPerSecond"]
    cps = float(h["countsPerSecond"])
    mapped = sorted((r for r in recs if not (r["flags"] & 0x11)), key=lambda r: r["tFetch"])   # NAND reads only
    if not mapped:
        sys.exit("no NAND reads")
    t0 = mapped[0]["tFetch"]
    phases = (("ro", [r for r in mapped if (r["tFetch"] - t0) / cps <= ro_s]),
              ("storm", [r for r in mapped if (r["tFetch"] - t0) / cps > ro_s]))
    for name, part in phases:
        if not part:
            print("%-5s none" % name)
            continue
        rows = []
        for r in part:
            w = max(0, r["dIssue"] - r["dEnqueue"]) * unit                 # ms
            calls = r["schedDieQ"]
            interval = w / (calls + 1.0)                                    # ms between passes
            loop = min(w, (r["aheadCnt"] + 1) * interval)
            rows.append((w, calls, interval, loop, r["aheadCnt"]))
        tot_w = sum(x[0] for x in rows)
        print("%-5s NAND reads=%d  enqueue->issue window: sum %.1f ms, mean %.3f ms, p99 %.3f ms, max %.3f ms" % (
            name, len(rows), tot_w, tot_w / len(rows), pct([x[0] for x in rows], 99), max(x[0] for x in rows)))
        print("      all reads: loop estimate %.1f%% of window, die estimate %.1f%%; interval median %.1f us p99 %.1f us max %.1f us; "
              "passes per ms (median) %.1f" % (
                  100.0 * sum(x[3] for x in rows) / (tot_w or 1.0), 100.0 * (1 - sum(x[3] for x in rows) / (tot_w or 1.0)),
                  1000.0 * pct([x[2] for x in rows], 50), 1000.0 * pct([x[2] for x in rows], 99), 1000.0 * max(x[2] for x in rows),
                  1.0 / max(pct([x[2] for x in rows], 50), 1e-9)))
        tail = [x for x in rows if x[0] >= tail_ms]
        if tail:
            tw = sum(x[0] for x in tail)
            print("      tail (window >= %.1f ms): reads=%d  window sum %.1f ms (%.0f%% of all window time)  loop estimate %.1f%%, die estimate %.1f%%" % (
                tail_ms, len(tail), tw, 100.0 * tw / (tot_w or 1.0), 100.0 * sum(x[3] for x in tail) / tw,
                100.0 * (1 - sum(x[3] for x in tail) / tw)))
            print("      tail interval: median %.1f us p99 %.1f us max %.1f us | reads with interval > 0.1 ms: %d, > 1 ms: %d | median passes %d, median ahead %d" % (
                1000.0 * pct([x[2] for x in tail], 50), 1000.0 * pct([x[2] for x in tail], 99), 1000.0 * max(x[2] for x in tail),
                sum(1 for x in tail if x[2] > 0.1), sum(1 for x in tail if x[2] > 1.0),
                pct([x[1] for x in tail], 50), pct([x[4] for x in tail], 50)))
        else:
            print("      no reads with window >= %.1f ms" % tail_ms)


if __name__ == "__main__":
    main()
