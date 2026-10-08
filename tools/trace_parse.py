#!/usr/bin/env python3
"""Parse a firmware trace dump (trace_log.c) into a CSV and print a segment summary.

usage: trace_parse.py trace.bin [--csv out.csv] [--stall-ms 1000]

trace.bin = raw memory dump starting at TRACE_BASE_ADDR (0x00300000): 4KB header + 64B records
(see tools/trace_dump.md). Segments follow team-experiment-procedure 12.2:

  buffer   = dEnqueue - dBufAlloc                (buffer entry wait, incl. eviction / row-address dependency)
  dieq     = max(0, dDieLastDone - dEnqueue)     (waiting for the previous request on that die)
  loop     = dBufAlloc + (dIssue - max(dEnqueue, dDieLastDone)) + (dDmaStart - dNandDone)
  xferwait = dXferIssue - dTrigDone              (read transfer waits behind other channel work)
  nanddma  = (dTrigDone - dIssue) + (dNandDone - dXferIssue) + (dDmaEnd - dDmaStart)

Records without NAND access (buffer hit / unmapped, flags b0/b4): buffer = dDmaStart - dBufAlloc.
'fetch before' (host latency minus firmware time) needs the fio log and is not computed here.
"""
import struct
import sys

HDR_FMT = "<19I"
HDR_NAMES = ["magic", "version", "recCount", "stopFlag", "rbuf", "trace", "verify", "rbufEntries",
             "countsPerSecond", "timeShift", "maxRecords", "recBytes", "recOffset", "gcCnt",
             "bufEvictCnt", "bufReadEvictCnt", "rbufReadAllocCnt", "rbufWriteHitInvalidateCnt", "dropped"]
REC_FMT = "<IIQ7iHHii8s"
REC_NAMES = ["seq", "lba", "tFetch", "dBufAlloc", "dEnqueue", "dDieLastDone", "dIssue", "dNandDone",
             "dDmaStart", "dDmaEnd", "flags", "aheadCnt", "dXferIssue", "dTrigDone", "pad"]
MAGIC = 0x45435254

assert struct.calcsize(REC_FMT) == 64


def load(path):
    data = open(path, "rb").read()
    h = dict(zip(HDR_NAMES, struct.unpack_from(HDR_FMT, data, 0)))
    if h["magic"] != MAGIC:
        sys.exit("bad magic 0x%08X (expected 0x%08X): wrong dump address/size?" % (h["magic"], MAGIC))
    if h["recBytes"] != 64:
        sys.exit("unexpected record size %d" % h["recBytes"])
    n = h["recCount"]
    need = h["recOffset"] + n * 64
    if len(data) < need:
        print("warning: dump has %d bytes but header says %d records (%d bytes); using what is there"
              % (len(data), n, need), file=sys.stderr)
        n = max(0, (len(data) - h["recOffset"]) // 64)
    recs = []
    for i in range(n):
        v = struct.unpack_from(REC_FMT, data, h["recOffset"] + i * 64)
        recs.append(dict(zip(REC_NAMES, v)))
    return h, recs


def segments(r):
    """segment lengths in ticks (units of 2**timeShift XTime counts)"""
    flags = r["flags"]
    seg = dict(buffer=0, dieq=0, loop=0, xferwait=0, nanddma=0)
    if flags & (0x0001 | 0x0010):              # buffer hit or unmapped: no NAND request
        seg["loop"] = r["dBufAlloc"]
        seg["buffer"] = max(0, r["dDmaStart"] - r["dBufAlloc"])
        seg["nanddma"] = r["dDmaEnd"] - r["dDmaStart"]
        return seg
    start = max(r["dEnqueue"], r["dDieLastDone"])
    seg["loop"] = r["dBufAlloc"] + max(0, r["dIssue"] - start) + max(0, r["dDmaStart"] - r["dNandDone"])
    seg["buffer"] = max(0, r["dEnqueue"] - r["dBufAlloc"])
    seg["dieq"] = max(0, r["dDieLastDone"] - r["dEnqueue"])
    seg["xferwait"] = max(0, r["dXferIssue"] - r["dTrigDone"])
    seg["nanddma"] = (max(0, r["dTrigDone"] - r["dIssue"]) + max(0, r["dNandDone"] - r["dXferIssue"])
                      + max(0, r["dDmaEnd"] - r["dDmaStart"]))
    return seg


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1))))
    return sorted_vals[i]


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    path = args[0]
    csv_path = args[args.index("--csv") + 1] if "--csv" in args else None
    stall_ms = float(args[args.index("--stall-ms") + 1]) if "--stall-ms" in args else 1000.0

    h, recs = load(path)
    unit_ms = (1 << h["timeShift"]) * 1000.0 / h["countsPerSecond"]
    print("header: " + ", ".join("%s=%d" % (k, h[k]) for k in HDR_NAMES if k not in ("magic", "recBytes", "recOffset")))
    print("records parsed: %d, unit = %.6f ms" % (len(recs), unit_ms))
    if h["stopFlag"]:
        print("WARNING: log was full, %d records dropped" % h["dropped"])
    if not recs:
        return

    rows = []
    for r in recs:
        s = segments(r)
        total = r["dDmaEnd"]
        rows.append((r, s, total))

    if csv_path:
        with open(csv_path, "w") as f:
            f.write("seq,lba,flags,aheadCnt,total_ms,buffer_ms,dieq_ms,loop_ms,xferwait_ms,nanddma_ms\n")
            for r, s, total in rows:
                f.write("%d,%d,0x%04x,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n" % (
                    r["seq"], r["lba"], r["flags"], r["aheadCnt"], total * unit_ms,
                    s["buffer"] * unit_ms, s["dieq"] * unit_ms, s["loop"] * unit_ms,
                    s["xferwait"] * unit_ms, s["nanddma"] * unit_ms))
        print("csv written: %s" % csv_path)

    totals = sorted(t * unit_ms for _, _, t in rows)
    print("firmware-internal read latency (tFetch..DMA end): p50=%.3f ms p99=%.3f ms p99.9=%.3f ms max=%.3f ms"
          % (pct(totals, 50), pct(totals, 99), pct(totals, 99.9), totals[-1]))
    print("flags: buf-hit=%d unmapped=%d rbuf-entry=%d saturated=%d"
          % (sum(1 for r, _, _ in rows if r["flags"] & 1), sum(1 for r, _, _ in rows if r["flags"] & 0x10),
             sum(1 for r, _, _ in rows if r["flags"] & 2), sum(1 for r, _, _ in rows if r["flags"] & 8)))

    keys = ["buffer", "dieq", "loop", "xferwait", "nanddma"]

    def summarize(sel, title):
        if not sel:
            print("%s: none" % title)
            return
        tot = {k: sum(s[k] for _, s, _ in sel) * unit_ms for k in keys}
        grand = sum(tot.values()) or 1.0
        print("%s (%d reads): " % (title, len(sel)) + ", ".join(
            "%s %.1f%% (%.1f ms)" % (k, 100.0 * tot[k] / grand, tot[k]) for k in keys))

    summarize(rows, "all reads")
    p99 = pct(totals, 99)
    summarize([x for x in rows if x[2] * unit_ms > p99], "slower than p99")
    stalls = [x for x in rows if x[2] * unit_ms >= stall_ms]
    summarize(stalls, "stalls >= %.0f ms" % stall_ms)

    print("\nstall list (seq, total ms, dominant segment, per-segment ms):")
    for r, s, total in stalls:
        dom = max(keys, key=lambda k: s[k])
        print("  seq %d  %.1f ms  -> %s  [%s]  ahead=%d flags=0x%04x" % (
            r["seq"], total * unit_ms, dom,
            " ".join("%s=%.1f" % (k, s[k] * unit_ms) for k in keys), r["aheadCnt"], r["flags"]))


if __name__ == "__main__":
    main()
