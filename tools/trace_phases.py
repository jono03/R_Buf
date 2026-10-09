#!/usr/bin/env python3
"""Split a trace dump into phases and print per-phase read latency (firmware-internal) and segment shares.

usage: trace_phases.py trace.bin [--ro-s 60]

rbuf_check.fio: 8 GiB prefill (no reads), then the read-only job 'ro' for ROT seconds (QD1 or QD8), then the reader of the
write storm. Reads fetched while the device still held no data (flag b4 'unmapped', host/boot probing) are phase 'boot'.
The first mapped read starts 'ro'; reads fetched within --ro-s seconds of it (default 60 = ROT of M1, use 10 for M2) are
'ro'; later reads are 'storm'.
Percentiles over ALL records mix the read-only reads with the storm reads, so they depend on how many reads the storm phase
managed to issue (a run whose reader stalled has few storm reads). Compare runs with the storm-phase numbers printed here.
(Do not split by the largest gaps: a host stall in a QD1 reader also shows up as a long gap between fetch times.)
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
    h, recs = t.load(a[0])
    unit = (1 << h["timeShift"]) * 1000.0 / h["countsPerSecond"]
    cps = float(h["countsPerSecond"])
    boot = [r for r in recs if r["flags"] & 0x10]
    mapped = sorted((r for r in recs if not (r["flags"] & 0x10)), key=lambda r: r["tFetch"])
    if not mapped:
        sys.exit("no mapped reads")
    t0 = mapped[0]["tFetch"]
    ro = [r for r in mapped if (r["tFetch"] - t0) / cps <= ro_s]
    storm = [r for r in mapped if (r["tFetch"] - t0) / cps > ro_s]
    keys = ["buffer", "dieq", "loop", "xferwait", "nanddma"]
    print("records %d: boot(unmapped) %d, ro %d, storm %d (ro window %.0f s from first mapped read)" % (
        len(recs), len(boot), len(ro), len(storm), ro_s))
    for name, part in (("boot", boot), ("ro", ro), ("storm", storm)):
        if not part:
            print("%-5s none" % name)
            continue
        tot = [r["dDmaEnd"] * unit for r in part]
        span = (max(r["tFetch"] for r in part) - min(r["tFetch"] for r in part)) / cps
        sh = {x: sum(t.segments(r, None)[x] for r in part) * unit for x in keys}
        grand = sum(sh.values()) or 1.0
        print("%-5s reads=%d span=%.1f s  fw p50=%.3f p95=%.3f p99=%.3f p99.9=%.3f max=%.3f ms  | %s" % (
            name, len(part), span, pct(tot, 50), pct(tot, 95), pct(tot, 99), pct(tot, 99.9), max(tot),
            " ".join("%s %.1f%%" % (x, 100.0 * sh[x] / grand) for x in keys)))


if __name__ == "__main__":
    main()
